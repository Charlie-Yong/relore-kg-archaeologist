"""P4: project-local collection, storage and retrieval using the bundled relore.

These are development/data interfaces, not the final BuildJob/QueryResult pipeline.
No daemon, original deployment, model service or target-project code is executed.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import relore
from relore.github.client import GitHubClient, GitHubError
from relore.github.fetch_thread import ThreadPayload, fetch_thread
from relore.ingest.index_thread import index_payload
from relore.search import SearchQuery, open_backend, search_best
from relore.store import schema
from relore.store.dialect import make_engine
from relore.store.migrations import migrate
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor" / "relore" / "relore"
VERSION = "0.3.19"
COMMIT = "06a1c99c4653e9db899a18e96d8ff0ee6b419815"
INTERFACE = "collector_v1"
PROFILE = "collector_smoke_v1"
CAPTURE = "historykg.collector.capture.v1"


class CollectionBlocked(RuntimeError):
    """A request budget or external rate limit stopped this bounded collection."""


class UnsupportedRepository(ValueError):
    """A valid response establishes that this repo is outside project scope."""


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(type(value).__name__)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _result(status: str = "ok", **fields: Any) -> dict[str, Any]:
    return {"interface_version": INTERFACE, "status": status, **fields}


def _source() -> dict[str, Any]:
    location = Path(relore.__file__).resolve()
    bundled = location.is_relative_to(SOURCE.resolve()) and relore.__version__ == VERSION
    return {
        "version": relore.__version__,
        "expected_version": VERSION,
        "commit": COMMIT,
        "bundled": bundled,
        "module_path": str(location),
    }


def _require_source() -> None:
    if not _source()["bundled"]:
        raise ValueError("请从项目根目录运行 python -m pip install -r requirements.txt")


def normalize_repo(value: str, *, require_url: bool = False) -> str:
    pattern = r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)"
    match = re.fullmatch(r"https://github\.com/" + pattern + r"(?:\.git)?/?", value)
    if match is None and not require_url:
        match = re.fullmatch(pattern, value)
    if match is None or any(part in {".", ".."} for part in match.group(1).split("/")):
        raise ValueError("仅支持公开GitHub仓库地址 https://github.com/owner/repo")
    return match.group(1).lower()


def _engine(database_url: str | None) -> Engine:
    _require_source()
    url = database_url or os.environ.get("RELORE_DATABASE_URL")
    if not url:
        path = ROOT / ".local" / "collector" / "index.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        url = "sqlite:///" + path.as_posix()
    return make_engine(url)


def _counts(engine: Engine, repo: str | None = None) -> dict[str, int]:
    threads = select(func.count()).select_from(schema.threads)
    documents = select(func.count()).select_from(
        schema.documents.join(schema.threads, schema.documents.c.thread_id == schema.threads.c.id)
    )
    if repo is not None:
        threads = threads.where(schema.threads.c.repo == repo)
        documents = documents.where(schema.threads.c.repo == repo)
    with engine.connect() as conn:
        return {"threads": conn.scalar(threads), "documents": conn.scalar(documents)}


def _database_error(exc: Exception) -> dict[str, Any]:
    # Driver messages may include a connection string; do not publish credentials in JSON.
    return _result(
        "error",
        error={
            "code": "database_error",
            "type": type(exc).__name__,
            "message": "数据库操作失败，请检查RELORE_DATABASE_URL及数据库服务。",
        },
    )


def initialize_database(database_url: str | None = None) -> dict[str, Any]:
    """Create/migrate the configured collector index, without touching other databases."""
    engine = None
    try:
        engine = _engine(database_url)
        migrate(engine)
        return _result(backend=engine.dialect.name, counts=_counts(engine))
    except ValueError as exc:
        return _result("error", error={"code": "configuration", "message": str(exc)})
    except SQLAlchemyError as exc:
        return _database_error(exc)
    finally:
        if engine is not None:
            engine.dispose()


def doctor(database_url: str | None = None) -> dict[str, Any]:
    """Inspect the actual imported source and database; never contact a hosted daemon."""
    engine = None
    try:
        engine = _engine(database_url)
        tables = inspect(engine).get_table_names()
        ready = {"threads", "documents", "schema_migrations"}.issubset(tables)
        return _result(
            source=_source(),
            backend=engine.dialect.name,
            schema_ready=ready,
            counts=_counts(engine) if ready else None,
            token_configured=bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")),
            hint=None
            if ready
            else "ingest会自动初始化数据库；Python调用方也可先运行initialize_database。",
        )
    except ValueError as exc:
        return _result(
            "error", source=_source(), error={"code": "configuration", "message": str(exc)}
        )
    except SQLAlchemyError as exc:
        return {**_database_error(exc), "source": _source()}
    finally:
        if engine is not None:
            engine.dispose()


class _RequestBudget:
    """Count each network attempt, including retries and pagination, and freeze responses."""

    def __init__(self, limit: int, initial_requests: int = 0, responses: list | None = None):
        self.limit = limit
        self.used = initial_requests
        self.responses: list[dict[str, Any]] = list(responses or [])
        self.checkpoint = lambda: None

    def before_request(self, request: httpx.Request) -> None:
        if self.used >= self.limit:
            raise CollectionBlocked(f"已达到GitHub请求上限{self.limit}次。")
        self.used += 1
        self.checkpoint()

    def after_response(self, response: httpx.Response) -> None:
        response.read()
        self.responses.append(
            {
                "url": str(response.request.url),
                "status": response.status_code,
                "retrieved_at": _now(),
                "body": response.text,
                "headers": {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() in {"link", "content-type"}
                },
                "rate_limit_remaining": response.headers.get("x-ratelimit-remaining"),
            }
        )
        self.checkpoint()


def _retry_wait(seconds: float) -> None:
    if seconds > 10:
        raise CollectionBlocked(f"GitHub要求等待{int(seconds)}秒，请在额度恢复后重试。")
    time.sleep(seconds)


class _ResumableClient(httpx.Client):
    """Replay successful frozen GET pages; only uncaptured pages use the network."""

    def __init__(self, *args, captured_responses: list, **kwargs):
        super().__init__(*args, **kwargs)
        self.captured = {
            r["url"]: r for r in captured_responses if r["status"] == 200 and "headers" in r
        }

    def send(self, request, *args, **kwargs):
        captured = self.captured.get(str(request.url))
        if captured is not None:
            # Bypasses network hooks: a replay is neither a new attempt nor a new capture.
            return httpx.Response(
                captured["status"],
                text=captured["body"],
                request=request,
                headers=captured.get("headers", {}),
            )
        return super().send(request, *args, **kwargs)


def _select_threads(client: GitHubClient, repo: str, issues: int, prs: int) -> list[dict]:
    selected = []
    for kind, limit, endpoint in [("pr", prs, "pulls"), ("issue", issues, "issues")]:
        if not limit:
            continue
        candidates = client.get_json(
            f"repos/{repo}/{endpoint}",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 100},
        )
        candidates = [x for x in candidates if kind == "pr" or "pull_request" not in x]
        candidates.sort(key=lambda x: (x.get("updated_at") or "", x["number"]), reverse=True)
        selected.extend({"kind": kind, "number": x["number"]} for x in candidates[:limit])
    return selected


def collect_repo(
    repo_url: str,
    *,
    database_url: str | None = None,
    max_issues: int = 1,
    max_prs: int = 1,
    max_requests: int = 60,
    output_dir: str | Path | None = None,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    selected: list[dict] | None = None,
    resume_capture: str | Path | None = None,
    initial_requests: int = 0,
    initial_http_responses: list[dict] | None = None,
    profile_version: str = PROFILE,
) -> dict[str, Any]:
    """Discover and index a bounded public Python repo sample, saving a replayable capture.

    ``transport`` is injectable for offline consumers/tests. A failed collection keeps
    already indexed threads; gaps and status distinguish it from a complete sample.
    """
    try:
        repo = normalize_repo(repo_url, require_url=True)
        if min(max_issues, max_prs) < 0 or not 1 <= max_issues + max_prs <= 40:
            raise ValueError("讨论单元总上限须在1到40之间。")
        if not 1 <= max_requests <= 300:
            raise ValueError("GitHub请求上限须在1到300之间。")
        if not 0 <= initial_requests <= max_requests:
            raise ValueError("已用请求数必须位于请求上限内。")
        if selected is not None:
            selected = list({(x["kind"], x["number"]): dict(x) for x in selected}.values())
            if len(selected) > 40 or any(
                x["kind"] not in {"issue", "pr"}
                or not isinstance(x["number"], int)
                or x["number"] <= 0
                for x in selected
            ):
                raise ValueError("selected只允许至多40条合法线程。")
    except ValueError as exc:
        return _result("unsupported", error={"code": "input", "message": str(exc)})

    engine = None
    payloads: list[ThreadPayload] = []
    selected_threads: list[dict] = list(selected or [])
    gaps: list[dict] = []
    captured = list(initial_http_responses or [])
    prior_payloads = []
    if resume_capture is not None:
        previous = json.loads(Path(resume_capture).read_text(encoding="utf-8"))
        if previous.get("format") != CAPTURE or normalize_repo(previous["repo"]) != repo:
            raise ValueError("续作快照格式或仓库不一致。")
        old_selected = previous["result"]["selected"]
        if selected is not None and selected != old_selected:
            raise ValueError("续作必须沿用冻结selected清单。")
        selected_threads = old_selected
        prior_payloads = previous["payloads"]
        captured = previous["http_responses"]
        initial_requests = previous["result"]["github_requests"]
        if initial_requests > max_requests:
            raise ValueError("续作请求上限不能小于已有耗用。")
    budget = _RequestBudget(max_requests, initial_requests, captured)
    token = (
        token
        if token is not None
        else (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "historykg-collector/1.4.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status = "ok"
    counts = {"threads": 0, "documents": 0}
    directory = (
        Path(output_dir)
        if output_dir
        else ROOT
        / ".local"
        / "collector"
        / "runs"
        / (dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6])
    )
    capture_path = directory / "capture.json"

    def checkpoint():
        _write_json(
            capture_path,
            {
                "format": CAPTURE,
                "repo": repo,
                "retrieved_at": _now(),
                "relore_commit": COMMIT,
                "checkpoint": True,
                "result": _result(
                    "partial" if payloads else "blocked",
                    repo=repo,
                    profile_version=profile_version,
                    selected=selected_threads,
                    indexed_threads=len(payloads),
                    counts=counts,
                    gaps=[*gaps, {"reason": "interrupted_or_running"}],
                    github_requests=budget.used,
                    max_requests=max_requests,
                    authenticated=bool(token),
                    capture_path=str(capture_path),
                ),
                "payloads": [dataclasses.asdict(p) for p in payloads],
                "http_responses": budget.responses,
            },
        )

    budget.checkpoint = checkpoint
    try:
        engine = _engine(database_url)
        migrate(engine)
        for raw in prior_payloads:
            payload = ThreadPayload(**{**raw, "unread": set(raw.get("unread", []))})
            if normalize_repo(payload.repo) != repo:
                raise ValueError("续作线程仓库不一致。")
            if not payload.unread:
                with engine.begin() as conn:
                    index_payload(conn, payload)
                payloads.append(payload)
        with _ResumableClient(
            captured_responses=captured,
            transport=transport,
            headers=headers,
            timeout=30,
            event_hooks={"request": [budget.before_request], "response": [budget.after_response]},
        ) as http:
            client = GitHubClient(token, client=http, max_retries=2, sleep=_retry_wait)
            metadata = client.get_json(f"repos/{repo}")
            if metadata.get("private"):
                raise UnsupportedRepository("本入口只支持公开仓库。")
            if metadata.get("language") != "Python":
                languages = client.get_json(f"repos/{repo}/languages")
                if "Python" not in languages:
                    raise UnsupportedRepository("当前项目范围为包含Python源码的公开仓库。")
            if selected is None and not selected_threads:
                selected_threads = _select_threads(client, repo, max_issues, max_prs)
            checkpoint()
            complete_numbers = {p.number for p in payloads}
            for item in selected_threads:
                if item["number"] in complete_numbers:
                    continue
                try:
                    payload = fetch_thread(client, repo, item["number"])
                    with engine.begin() as conn:
                        index_payload(conn, payload)
                    payloads.append(payload)
                    counts = _counts(engine, repo)
                    if payload.unread:
                        gaps.append({**item, "reason": "unread", "parts": sorted(payload.unread)})
                    checkpoint()
                except GitHubError as exc:
                    gaps.append({**item, "reason": "fetch_failed", "http_status": exc.status})
            counts = _counts(engine, repo)
        status = "partial" if gaps else ("ok" if payloads else "empty")
        if gaps and not payloads:
            status = "error"
    except CollectionBlocked as exc:
        status = "partial" if payloads else "blocked"
        gaps.append({"reason": "request_limit_or_rate_limit", "message": str(exc)})
    except GitHubError as exc:
        status = "partial" if payloads else ("unsupported" if exc.status == 404 else "error")
        gaps.append({"reason": "github_error", "http_status": exc.status})
    except httpx.TransportError as exc:
        status = "partial" if payloads else "error"
        gaps.append({"reason": "network_error", "type": type(exc).__name__})
    except UnsupportedRepository as exc:
        status = "unsupported"
        gaps.append({"reason": "unsupported_repository", "message": str(exc)})
    except ValueError as exc:
        status = "partial" if payloads else "error"
        gaps.append({"reason": "response_or_configuration_error", "type": type(exc).__name__})
    except SQLAlchemyError as exc:
        status = "error"
        gaps.append({"reason": "database_error", "type": type(exc).__name__})
    finally:
        if engine is not None:
            engine.dispose()

    result = _result(
        status,
        repo=repo,
        profile_version=profile_version,
        selected=selected_threads,
        indexed_threads=len(payloads),
        counts=counts,
        gaps=gaps,
        github_requests=budget.used,
        max_requests=max_requests,
        authenticated=bool(token),
        capture_path=str(capture_path),
    )
    _write_json(
        capture_path,
        {
            "format": CAPTURE,
            "repo": repo,
            "retrieved_at": _now(),
            "relore_commit": COMMIT,
            "result": result,
            "payloads": [dataclasses.asdict(p) for p in payloads],
            "http_responses": budget.responses,
        },
    )
    return result


def index_threads(
    payloads: list[ThreadPayload],
    *,
    database_url: str | None = None,
) -> dict[str, Any]:
    """P1/P2 replay seam: index these same frozen thread payloads without any network."""
    engine = None
    try:
        payloads = [dataclasses.replace(p, repo=normalize_repo(p.repo)) for p in payloads]
        repos = {p.repo for p in payloads}
        if len(repos) > 1:
            raise ValueError("每次回放只接收同一仓库的讨论。")
        engine = _engine(database_url)
        migrate(engine)
        written = 0
        for payload in payloads:
            with engine.begin() as conn:
                written += index_payload(conn, payload).stats.wrote
        repo = next(iter(repos), None)
        return _result(
            "partial" if any(p.unread for p in payloads) else ("ok" if payloads else "empty"),
            repo=repo,
            indexed_threads=len(payloads),
            documents_written=written,
            counts=_counts(engine, repo),
            gaps=[{"number": p.number, "parts": sorted(p.unread)} for p in payloads if p.unread],
        )
    except ValueError as exc:
        return _result("error", error={"code": "input_or_configuration", "message": str(exc)})
    except SQLAlchemyError as exc:
        return _database_error(exc)
    finally:
        if engine is not None:
            engine.dispose()


def replay_capture(path: str | Path, *, database_url: str | None = None) -> dict[str, Any]:
    """Replay a collector capture and preserve the original collection's coverage gaps."""
    capture = json.loads(Path(path).read_text(encoding="utf-8"))
    if capture.get("format") != CAPTURE:
        raise ValueError("不支持的采集快照格式。")
    payloads = [
        ThreadPayload(**{**p, "unread": set(p.get("unread", []))}) for p in capture["payloads"]
    ]
    if any(normalize_repo(p.repo) != normalize_repo(capture["repo"]) for p in payloads):
        raise ValueError("采集快照仓库不一致。")
    result = index_threads(payloads, database_url=database_url)
    result["collection_status"] = capture["result"]["status"]
    result["collection_gaps"] = capture["result"]["gaps"]
    if result["status"] == "ok" and capture["result"]["status"] == "partial":
        result["status"] = "partial"
    if result["status"] == "empty" and capture["result"]["status"] not in {"ok", "empty"}:
        result["status"] = capture["result"]["status"]
    return result


def search_history(
    repo: str,
    query: str,
    *,
    database_url: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """P2 retrieval seam. Return relore hits, including original snippets and source URLs."""
    engine = None
    try:
        repo = normalize_repo(repo)
        if not query.strip() or not 1 <= limit <= 10:
            raise ValueError("关键词不能为空，limit须在1到10之间。")
        engine = _engine(database_url)
        backend = open_backend(engine)
        hits, note = search_best(backend, SearchQuery(repos=(repo,), text=query, limit=limit))
        return _result(
            "ok" if hits else "empty",
            repo=repo,
            query=query,
            hits=[dataclasses.asdict(hit) for hit in hits],
            note=note,
        )
    except ValueError as exc:
        return _result("unsupported", error={"code": "input_or_configuration", "message": str(exc)})
    except SQLAlchemyError as exc:
        return _database_error(exc)
    finally:
        if engine is not None:
            engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="项目历史采集器：基于开源relore二次开发")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查本地源码、配置和数据库")
    ingest = sub.add_parser("ingest", help="从公开Python仓库URL有限采集并建立索引")
    ingest.add_argument("repo_url")
    ingest.add_argument("--max-issues", type=int, default=1)
    ingest.add_argument("--max-prs", type=int, default=1)
    ingest.add_argument("--max-requests", type=int, default=60)
    ingest.add_argument("--out", type=Path)
    search = sub.add_parser("search", help="查询本项目本地索引")
    search.add_argument("query")
    search.add_argument("--repo", required=True)
    search.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "ingest":
            result = collect_repo(
                args.repo_url,
                max_issues=args.max_issues,
                max_prs=args.max_prs,
                max_requests=args.max_requests,
                output_dir=args.out,
            )
        else:
            result = search_history(args.repo, args.query, limit=args.limit)
    except OSError as exc:
        result = _result("error", error={"code": "local_io", "type": type(exc).__name__})
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return {"ok": 0, "empty": 0, "partial": 3, "blocked": 3}.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
