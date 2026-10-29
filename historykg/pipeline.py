"""P1's sole persistent single-worker URL build orchestration.

The UI calls start/get/resume. Stage algorithms stay in their owning modules.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import importlib
import os
import sqlite3
import threading
import uuid
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from historykg import collector
from historykg.contracts import CONTRACT_VERSION, STAGES, BuildJob, BuildRequest
from historykg.ids import canonical_json, dataset_id, normalize_repo, text_hash
from historykg.ingest.capture import finalize_relations, map_capture
from historykg.ingest.discovery import PROFILE, SnapshotClient, discover
from historykg.io import (
    build_subjects,
    collect_records,
    merge_sources,
    read_json,
    validate_dataset,
    write_json,
    write_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="historykg")
_FUTURES: dict[str, concurrent.futures.Future] = {}
_THREAD_LOCK = threading.Lock()


def _now():
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def load_config(config: dict | None = None) -> dict:
    if config is None:
        path = Path(os.getenv("HISTORYKG_PROJECT_CONFIG", ROOT / ".local/project.json"))
        config = read_json(path) if path.exists() else {}
    return {
        "jobs_root": str(ROOT / ".local/jobs"),
        "data_root": str(ROOT / "data"),
        "profile": PROFILE,
        "database_url": os.getenv("RELORE_DATABASE_URL"),
        "extract_module": "historykg.extract",
        "load_module": "historykg.graph",
        "model": {},
        "budget": {},
        **config,
    }


def _registry(config):
    root = Path(config["jobs_root"])
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "registry.sqlite3", timeout=30)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS jobs "
        "(id TEXT PRIMARY KEY, request_key TEXT, status TEXT, path TEXT)"
    )
    return conn


def _save(job, directory, config):
    job["updated_at"] = _now()
    BuildJob.model_validate(job)
    write_json(directory / "job.json", job)
    with _registry(config) as conn:
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (job["status"], job["job_id"]))


def _find(job_id, config):
    # job IDs are opaque local identities, never filesystem paths.
    if not job_id or any(c not in "0123456789abcdef-" for c in job_id):
        raise ValueError("非法job_id")
    directory = Path(config["jobs_root"]) / job_id
    if not (directory / "job.json").is_file():
        raise KeyError("未知构建任务")
    return directory


def get_build(job_id: str, *, config: dict | None = None) -> dict:
    config = load_config(config)
    return read_json(_find(job_id, config) / "job.json")


def _enqueue(directory, config):
    identity = str(directory.resolve())
    with _THREAD_LOCK:
        future = _FUTURES.get(identity)
        if future is None or future.done():
            _FUTURES[identity] = _EXECUTOR.submit(_run, directory, config)


def start_build(
    request: BuildRequest | dict, *, config: dict | None = None, background: bool = True
) -> dict:
    config = load_config(config)
    request = request if isinstance(request, BuildRequest) else BuildRequest.model_validate(request)
    repo = normalize_repo(request.repo_url, require_url=True)
    if request.profile != "course_small_v1":
        raise ValueError("未知构建profile；当前仅支持course_small_v1")
    profile = {**PROFILE, **config.get("profile", {})}
    frozen_config = {**config, "profile": profile}

    # Secrets belong in the environment, never persisted in a job snapshot.
    def reject_secrets(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key.lower()
                    in {"api_key", "token", "github_token", "deepseek_api_key", "authorization"}
                    and item
                ):
                    raise ValueError("凭据必须用环境变量配置，不能写入任务配置")
                reject_secrets(item)
        elif isinstance(value, list):
            for item in value:
                reject_secrets(item)

    reject_secrets(frozen_config)
    key = text_hash(canonical_json({"request": request.model_dump(), "config": frozen_config}))
    with _registry(config) as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT path FROM jobs WHERE request_key=? "
            "AND status IN ('queued','running','blocked') ORDER BY rowid DESC LIMIT 1",
            (key,),
        ).fetchone()
        if active:
            directory = Path(active[0])
            existing = read_json(directory / "job.json")
            # A refresh observes the same task; blocked jobs require explicit resume.
            if existing["status"] in {"queued", "running"}:
                _enqueue(directory, config)
            return existing
        job_id = uuid.uuid4().hex
        directory = Path(config["jobs_root"]) / job_id
        directory.mkdir(parents=True)
        job = dict(
            contract_version=CONTRACT_VERSION,
            job_id=job_id,
            repo=repo,
            profile_version=profile["profile_version"],
            dataset_id=None,
            status="queued",
            stage="discover",
            created_at=_now(),
            updated_at=_now(),
            counts={},
            coverage={},
            gaps=[],
            usage={"github_requests": 0},
            artifacts={"job_dir": str(directory)},
            error=None,
            resume_from="discover",
            completed_stages=[],
        )
        write_json(directory / "job.json", job)
        write_json(directory / "request.json", request.model_dump())
        write_json(directory / "config.json", frozen_config)
        conn.execute("INSERT INTO jobs VALUES (?,?,?,?)", (job_id, key, "queued", str(directory)))
    if background:
        _enqueue(directory, config)
    else:
        _run(directory, config)
    return read_json(directory / "job.json")


def resume_build(job_id: str, *, config: dict | None = None, background: bool = True) -> dict:
    supplied_config = config is not None
    config = load_config(config)
    directory = _find(job_id, config)
    job = read_json(directory / "job.json")
    if job["status"] in {"ready", "partial", "unsupported"}:
        return job
    frozen = read_json(directory / "config.json")
    if supplied_config:
        if config.get("database_url"):
            frozen["database_url"] = config["database_url"]
        frozen["graph"] = {**frozen.get("graph", {}), **config.get("graph", {})}
    job.update(status="queued", error=None)
    _save(job, directory, config)
    if background:
        _enqueue(directory, frozen)
    else:
        _run(directory, frozen)
    return read_json(directory / "job.json")


class StageBlocked(RuntimeError):
    pass


def _claim_worker(directory):
    lock = directory.parent / "worker.lock"
    stream = lock.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if lock.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        return None
    stream.seek(0)
    stream.truncate()
    stream.write(f"{os.getpid()}:{directory.name}".encode("ascii"))
    stream.flush()
    return stream


def _call(module, function, *args, **kwargs):
    try:
        entry = getattr(importlib.import_module(module), function)
    except (ModuleNotFoundError, AttributeError) as exc:
        raise StageBlocked(f"等待模块接口 {module}.{function}") from exc
    result = entry(*args, **kwargs)
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json")
    if not isinstance(result, dict):
        raise ValueError(f"{module}.{function}必须返回dict")
    return result


def _stage(job, directory, config):
    stage = job["stage"]
    profile = config["profile"]
    snapshot_dir = directory / "snapshot"
    root = Path(job["artifacts"]["dataset_dir"])
    if stage == "discover":
        return discover(
            "https://github.com/" + job["repo"],
            snapshot_dir=snapshot_dir,
            dataset_id=job["dataset_id"],
            profile=profile,
        )
    if stage == "collect":
        snapshot = read_json(snapshot_dir / "snapshot.json")
        initial = read_json(snapshot_dir / "discovery_http.json")
        capture_path = directory / "collection/capture.json"
        import inspect

        if "selected" not in inspect.signature(collector.collect_repo).parameters:
            raise StageBlocked(
                "等待P4 collector selected/resume_capture扩展，不能以smoke替代正式profile"
            )
        result = collector.collect_repo(
            "https://github.com/" + job["repo"],
            database_url=config.get("database_url"),
            selected=snapshot["selected"],
            resume_capture=capture_path if capture_path.exists() else None,
            initial_requests=initial["github_requests"],
            initial_http_responses=initial["http_responses"],
            max_requests=profile["max_requests"],
            output_dir=capture_path.parent,
            profile_version=profile["profile_version"],
        )
        job["usage"]["github_requests"] = result.get("github_requests", initial["github_requests"])
        if result["status"] in {"blocked", "unsupported", "error"}:
            return {**result, "artifacts": {"capture": str(capture_path)}}
        # Official timeline metadata shares the same total request budget and cache.
        metadata = SnapshotClient(
            snapshot_dir / "metadata_http.json",
            max_requests=profile["max_requests"],
            initial_requests=job["usage"]["github_requests"],
        )
        metadata_gaps = []
        try:
            capture = read_json(capture_path)
            for payload in capture.get("payloads", []):
                if payload["thread_type"] == "issue":
                    endpoint = f"repos/{job['repo']}/issues/{payload['number']}/timeline"
                    try:
                        # All event pages, with the same GET retry/request boundary.
                        list(metadata.client.paginate(endpoint))
                    except (collector.CollectionBlocked, collector.GitHubError) as exc:
                        metadata_gaps.append(
                            {
                                "reason": "issue_timeline_unread",
                                "number": payload["number"],
                                "type": type(exc).__name__,
                            }
                        )
                        break
        finally:
            job["usage"]["github_requests"] = metadata.state["github_requests"]
            metadata.close()
        mapped = map_capture(
            capture_path, dataset_dir=root, dataset_id=job["dataset_id"], snapshot_dir=snapshot_dir
        )
        mapped["gaps"] += metadata_gaps
        if metadata_gaps:
            mapped["status"] = "partial"
        mapped["usage"] = {"github_requests_total": job["usage"]["github_requests"]}
        mapped["artifacts"]["capture"] = str(capture_path)
        return mapped
    if stage == "code":
        budget = {
            **config.get("budget", {}),
            "max_requests": profile["max_requests"],
            "github_requests": job["usage"].get("github_requests", 0),
        }
        result = _call(
            "historykg.code",
            "run_code_stage",
            snapshot_dir,
            dataset_dir=root,
            profile=profile,
            budget=budget,
        )
        job["usage"]["github_requests"] = budget["github_requests"]
        if result.get("status") in {"ok", "partial", "empty"}:
            merge_sources(root)
            finalize_relations(root)
            build_subjects(root)
            _manifest(root, job, frozen=False)
            checked = validate_dataset(root)
            result["module_counts"] = result.get("counts", {})
            result["counts"] = {**result.get("counts", {}), **checked["counts"]}
            result["coverage"] = _dataset_coverage(root, profile, checked["counts"])
            if checked["status"] != "ok":
                result.update(
                    status="error",
                    error={"code": "code_record_validation", "errors": checked["errors"]},
                )
        return result
    if stage == "extract":
        budget = {**config.get("budget", {}), **job["usage"]}
        if not any(
            budget.get(key)
            for key in (
                "max_requests",
                "max_model_requests",
                "max_tokens",
                "max_total_tokens",
                "max_cost_cny",
                "max_total_cny",
            )
        ):
            raise StageBlocked("缺少已批准的非空模型请求/token/费用上限")
        result = _call(
            config["extract_module"],
            "run_extract_stage",
            root,
            config=config.get("model", {}),
            budget=budget,
        )
        return result
    if stage == "validate":
        _manifest(root, job, frozen=True)
        result = validate_dataset(root)
        write_json(directory / "validation.json", result)
        return {
            **result,
            "artifacts": {"validation": str(directory / "validation.json")},
            "gaps": result.get("errors", []),
            "coverage": _dataset_coverage(root, profile, result["counts"]),
        }
    return _call(config["load_module"], "load_dataset", root, config=query_config(config))


def query_config(config: dict) -> dict:
    return {
        "database_url": config.get("database_url"),
        "answer": config.get("answer", config.get("model", {})),
        "budget": config.get("budget", {}),
        **config.get("graph", {}),
    }


def _dataset_coverage(root, profile, counts):
    sources = collect_records(root, "sources.jsonl", shards=False)
    units = collect_records(root, "source_units.jsonl", shards=False)
    entities = collect_records(root, "entities.jsonl")
    timestamps = sorted(s["occurred_at"] for s in sources if s.get("occurred_at"))
    completeness = Counter(unit["completeness"] for unit in units)
    manifest = read_json(Path(root) / "manifest.json")
    return {
        **counts,
        "discussion_units": len(units),
        "complete_units": completeness["complete"],
        "partial_units": completeness["partial"],
        "unread_units": completeness["unread"],
        "file_snapshots": len({e["id"] for e in entities if e["type"] == "File"}),
        "time_range": {
            "earliest": timestamps[0] if timestamps else None,
            "latest": timestamps[-1] if timestamps else None,
        },
        "profile_limits": {
            key: profile[key]
            for key in (
                "max_units",
                "max_requests",
                "max_releases",
                "max_commits",
                "max_file_snapshots",
            )
            if key in profile
        },
        "gap_counts": dict(
            Counter(
                g.get("reason", "unspecified")
                for g in manifest.get("gaps", [])
                if isinstance(g, dict)
            )
        ),
    }


def _manifest(root, job, *, frozen):
    old = read_json(root / "manifest.json")
    old.pop("files", None)
    old.pop("sources", None)
    return write_manifest(
        root,
        **{
            **old,
            "frozen": frozen,
            "job_id": job["job_id"],
            "usage": job["usage"],
            "gaps": job["gaps"],
            "actual_llm_extraction": job["coverage"].get("actual_llm_extraction", False),
        },
    )


def _completion_status(stage, result):
    status = result.get("status", "ok")
    # The first collect checkpoint predates the coverage/status correction.
    # Its immutable source records remain valid; only the old status is normalized.
    gaps = result.get("gaps", [])
    if (
        stage == "collect"
        and status == "partial"
        and gaps
        and all(
            isinstance(gap, dict)
            and (
                gap.get("severity") == "coverage"
                or gap.get("reason") == "explicit_reference_over_limit"
            )
            for gap in gaps
        )
    ):
        return "ok"
    return status


def _run(directory, config, stop_after=None):
    worker_lock = _claim_worker(directory)
    if worker_lock is None:
        return  # Another process owns the sole worker; persisted queued work remains resumable.
    job = read_json(directory / "job.json")
    try:
        if job["dataset_id"] is None:
            job["dataset_id"] = dataset_id(job["repo"], job["profile_version"], job["job_id"])
            job["artifacts"]["dataset_dir"] = str(
                Path(config["data_root"]) / job["dataset_id"].replace(":", "-")
            )
        for stage in STAGES:
            if stage in job.get("completed_stages", []):
                checkpoint = read_json(directory / f"checkpoint_{stage}.json")
                for filename, digest in checkpoint.get("files", {}).items():
                    path = Path(filename)
                    if not path.is_file() or text_hash(path.read_text(encoding="utf-8")) != digest:
                        raise ValueError("已冻结阶段产物变化，不能在旧job混用新输入")
                continue
            job.update(status="running", stage=stage, resume_from=stage, error=None)
            _save(job, directory, config)
            result = _stage(job, directory, config)
            job["artifacts"].update(result.get("artifacts", {}))
            job["counts"].update(result.get("counts", {}))
            job["coverage"].update(result.get("coverage", {}))
            job.setdefault("stage_counts", {})[stage] = result.get(
                "module_counts", result.get("counts", {})
            )
            for key in (
                "sources",
                "source_units",
                "entities",
                "relations",
                "evidence",
                "subjects",
                "file_snapshots",
            ):
                if key in job["coverage"]:
                    job["counts"][key] = job["coverage"][key]
            job["gaps"].extend(g for g in result.get("gaps", []) if g not in job["gaps"])
            usage = result.get("usage", {})
            if "github_requests_total" in usage:
                job["usage"]["github_requests"] = usage["github_requests_total"]
            for key, value in usage.items():
                if key not in {"github_requests", "github_requests_total"}:
                    job["usage"][key] = value
            if result.get("status") in {"blocked", "unsupported", "error", "failed"}:
                job["status"] = (
                    "failed" if result["status"] in {"error", "failed"} else result["status"]
                )
                job["error"] = result.get("error") or {
                    "code": "stage_" + result["status"],
                    "stage": stage,
                }
                _save(job, directory, config)
                return
            if stage == "extract":
                actual = result.get(
                    "actual_llm_extraction", usage.get("actual_llm_extraction", False)
                )
                job["coverage"]["actual_llm_extraction"] = bool(actual)
                if not actual:
                    raise StageBlocked("extract未返回真实LLM抽取执行证明")
            if stage == "index_graph":
                if (
                    result.get("dataset_id") != job["dataset_id"]
                    or not result.get("graph_ready")
                    or not result.get("retrieval_ready")
                ):
                    raise ValueError("图与共同检索尚未同时就绪或dataset不匹配")
                if not job["counts"].get("sources"):
                    raise ValueError("空来源不能发布可查询数据集")
                job["coverage"].update(graph_ready=True, retrieval_ready=True)
            job.setdefault("completed_stages", []).append(stage)
            job.setdefault("stage_statuses", {})[stage] = _completion_status(stage, result)
            checkpoint_files = []
            dataset_root = Path(job["artifacts"]["dataset_dir"])
            if stage == "discover":
                checkpoint_files = [directory / "snapshot/plan.json"]
            elif stage == "collect":
                checkpoint_files = [
                    directory / "collection/capture.json",
                    directory / "snapshot/code-input/sources.jsonl",
                ]
            elif stage in {"code", "extract"}:
                checkpoint_files = sorted(
                    (dataset_root / ("p3" if stage == "code" else "p4")).glob("*.jsonl")
                )
            elif stage == "validate":
                checkpoint_files = [directory / "validation.json"]
            hashes = {
                str(path): text_hash(path.read_text(encoding="utf-8"))
                for path in checkpoint_files
                if path.is_file()
            }
            write_json(
                directory / f"checkpoint_{stage}.json",
                {
                    "stage": stage,
                    "completed_at": _now(),
                    "result": result,
                    "files": hashes,
                    "input_hash": text_hash(
                        canonical_json(
                            {
                                "dataset_id": job["dataset_id"],
                                "profile": config["profile"],
                                "completed_stages": job["completed_stages"],
                            }
                        )
                    ),
                },
            )
            _save(job, directory, config)
            if stop_after == stage and stage != "index_graph":
                next_stage = STAGES[STAGES.index(stage) + 1]
                job.update(
                    status="blocked",
                    stage=next_stage,
                    resume_from=next_stage,
                    error={
                        "code": "developer_checkpoint",
                        "message": "已完成指定开发阶段，可resume继续",
                    },
                )
                _save(job, directory, config)
                return
        stage_statuses = dict(job.get("stage_statuses", {}))
        for stage in job["completed_stages"]:
            if stage not in stage_statuses:
                stage_statuses[stage] = _completion_status(
                    stage, read_json(directory / f"checkpoint_{stage}.json")["result"]
                )
        job["stage_statuses"] = stage_statuses
        job.update(
            status="partial" if "partial" in stage_statuses.values() else "ready", resume_from=None
        )
        _save(job, directory, config)
    except (StageBlocked, collector.CollectionBlocked) as exc:
        job.update(status="blocked", error={"code": "dependency_or_budget", "message": str(exc)})
        _save(job, directory, config)
    except collector.UnsupportedRepository as exc:
        job.update(
            status="unsupported", error={"code": "unsupported_repository", "message": str(exc)}
        )
        _save(job, directory, config)
    except Exception as exc:
        # Provider/driver errors may contain secrets. Record an actionable type, not raw text.
        job.update(
            status="failed",
            error={"code": "stage_exception", "stage": job["stage"], "type": type(exc).__name__},
        )
        _save(job, directory, config)
    finally:
        worker_lock.close()


def wait_build(job_id: str, *, config: dict | None = None) -> dict:
    """CLI waits for its one worker; browser callers use get_build polling."""
    config = load_config(config)
    directory = _find(job_id, config)
    future = _FUTURES.get(str(directory.resolve()))
    if future:
        future.result()
    return get_build(job_id, config=config)


def run_stage(job_id: str, stage: str, *, config: dict | None = None) -> dict:
    """Development CLI seam, executing through one stage in the same orchestration."""
    if stage not in STAGES:
        raise ValueError("未知stage")
    config = load_config(config)
    directory = _find(job_id, config)
    _run(directory, read_json(directory / "config.json"), stop_after=stage)
    return get_build(job_id, config=config)
