"""Bounded URL discovery. Network/retries use the P4 collector's relore client."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from historykg import collector
from historykg.ids import canonical_json, normalize_repo, stable_id
from historykg.io import read_json, write_json

PROFILE = {
    "profile_version": "course_small_v1",
    "plan_version": "discovery_v1",
    "max_candidates_per_kind": 100,
    "max_units": 40,
    "max_prs": 20,
    "max_releases": 3,
    "max_commits": 40,
    "max_file_states": 24,
    "max_file_snapshots": 24,
    "max_requests": 300,
    "selection": "merged PR first, explicit local issues, recent issues",
}

_REF = re.compile(
    r"https://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/(?P<url_kind>issues|pull)/(?P<url_num>\d+)"
    r"|(?<![\w/])(?:(?P<short_repo>[\w.-]+/[\w.-]+))?#(?P<short_num>\d+)",
    re.I,
)
_CLOSE = re.compile(r"\b(?:fix(?:e[sd])?|clos(?:e[sd]|ing)|resolv(?:e[sd]|ing))\s*:?[ \t]*$", re.I)


def parse_references(text: str, repo: str) -> list[dict]:
    refs = []
    for match in _REF.finditer(text):
        target = normalize_repo(match["url_repo"] or match["short_repo"] or repo)
        refs.append(
            dict(
                raw=match.group(),
                start=match.start(),
                end=match.end(),
                target_repo=target,
                number=int(match["url_num"] or match["short_num"]),
                object_type="PullRequest"
                if match["url_kind"] == "pull"
                else "Issue"
                if match["url_kind"]
                else "unknown",
                semantics="claims_to_close"
                if _CLOSE.search(text[max(0, match.start() - 30) : match.start()])
                else "reference",
                resolution="out_of_scope" if target != repo else "pending",
            )
        )
    return refs


class SnapshotClient:
    """Persist every attempt/response and reuse successful GETs after interruption."""

    def __init__(
        self, path: Path, *, max_requests=300, initial_requests=0, token=None, transport=None
    ):
        self.path = Path(path)
        self.state = (
            read_json(path)
            if self.path.exists()
            else {"github_requests": initial_requests, "http_responses": []}
        )
        self.limit = max_requests
        self.token = (
            token if token is not None else os.getenv("GITHUB_TOKEN", os.getenv("GH_TOKEN", ""))
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "historykg/1.4.1",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        self.http = collector._ResumableClient(
            captured_responses=self.state["http_responses"],
            headers=headers,
            timeout=30,
            transport=transport,
            event_hooks={"request": [self.before], "response": [self.after]},
        )
        self.client = collector.GitHubClient(
            self.token, client=self.http, max_retries=2, sleep=collector._retry_wait
        )

    def before(self, request):
        if self.state["github_requests"] >= self.limit:
            raise collector.CollectionBlocked("GitHub请求上限已耗尽")
        self.state["github_requests"] += 1
        write_json(self.path, self.state)

    def after(self, response):
        response.read()
        self.state["http_responses"].append(
            dict(
                url=str(response.request.url),
                status=response.status_code,
                retrieved_at=collector._now(),
                body=response.text,
                rate_limit_remaining=response.headers.get("x-ratelimit-remaining"),
                headers={
                    key: response.headers[key]
                    for key in ("link", "content-type")
                    if key in response.headers
                },
            )
        )
        write_json(self.path, self.state)

    def get(self, endpoint, params=None):
        url = "https://api.github.com/" + endpoint.lstrip("/")
        query = sorted((str(k), str(v)) for k, v in (params or {}).items())
        for response in reversed(self.state["http_responses"]):
            parts = urlsplit(response["url"])
            if (
                parts.scheme + "://" + parts.netloc + parts.path == url
                and sorted(parse_qsl(parts.query)) == query
                and response["status"] == 200
            ):
                import json

                return json.loads(response["body"])
        return self.client.get_json(endpoint, params=params)

    def close(self):
        self.http.close()


def discover(
    repo_url: str,
    *,
    snapshot_dir: str | Path,
    dataset_id: str,
    profile: dict | None = None,
    token=None,
    transport=None,
) -> dict:
    profile = {**PROFILE, **(profile or {})}
    for key, upper in (
        ("max_candidates_per_kind", 100),
        ("max_units", 40),
        ("max_prs", 40),
        ("max_requests", 300),
    ):
        if not isinstance(profile[key], int) or not 1 <= profile[key] <= upper:
            raise ValueError(f"profile {key}须在1到{upper}之间")
    repo = normalize_repo(repo_url, require_url=True)
    directory = Path(snapshot_dir)
    directory.mkdir(parents=True, exist_ok=True)
    client = SnapshotClient(
        directory / "discovery_http.json",
        max_requests=profile["max_requests"],
        token=token,
        transport=transport,
    )
    try:
        metadata = client.get(f"repos/{repo}")
        if metadata.get("private"):
            raise collector.UnsupportedRepository("仅支持公开仓库")
        if metadata.get("language") != "Python" and "Python" not in client.get(
            f"repos/{repo}/languages"
        ):
            raise collector.UnsupportedRepository("仓库没有Python源码支持")
        params = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": profile["max_candidates_per_kind"],
        }
        prs = client.get(f"repos/{repo}/pulls", params)
        issues = [x for x in client.get(f"repos/{repo}/issues", params) if "pull_request" not in x]

        def order(x):
            return x.get("updated_at") or "", x["number"]

        prs.sort(key=lambda x: (bool(x.get("merged_at")), *order(x)), reverse=True)
        issues.sort(key=order, reverse=True)
        selected_prs = prs[: min(profile["max_prs"], profile["max_units"])]
        selected = [
            {
                "kind": "pr",
                "number": p["number"],
                "reason": "merged_priority" if p.get("merged_at") else "recent_pr",
            }
            for p in selected_prs
        ]
        seen = {p["number"] for p in selected}
        references = []
        for pr in selected_prs:
            for ref in parse_references(
                (pr.get("title") or "") + "\n" + (pr.get("body") or ""), repo
            ):
                ref["from_number"] = pr["number"]
                if ref["target_repo"] == repo:
                    if ref["number"] in seen:
                        ref["resolution"] = "selected"
                    elif len(selected) < profile["max_units"]:
                        selected.append(
                            {
                                "kind": "issue",
                                "number": ref["number"],
                                "reason": "explicit_reference",
                            }
                        )
                        seen.add(ref["number"])
                        ref["resolution"] = "selected"
                    else:
                        ref["resolution"] = "over_limit"
                references.append(ref)
        for issue in issues:
            if len(selected) >= profile["max_units"]:
                break
            if issue["number"] not in seen:
                selected.append(
                    {"kind": "issue", "number": issue["number"], "reason": "recent_issue"}
                )
                seen.add(issue["number"])
        snapshot = dict(
            dataset_id=dataset_id,
            repo=repo,
            repo_metadata=metadata,
            profile=profile,
            selected=selected,
            selected_prs=selected_prs,
            references=references,
            candidate_counts={"prs": len(prs), "issues": len(issues)},
            unselected=[
                {"number": p["number"], "kind": kind, "reason": "profile_limit"}
                for kind, records in (("pr", prs), ("issue", issues))
                for p in records
                if p["number"] not in seen
            ],
            default_branch_sha=None,
            plan_id=stable_id("plan", repo, dataset_id, canonical_json(profile)),
        )
        write_json(directory / "snapshot.json", snapshot)
        write_json(directory / "plan.json", snapshot)
        return {
            "status": "ok",
            "artifacts": {
                "snapshot": str(directory / "snapshot.json"),
                "plan": str(directory / "plan.json"),
            },
            "counts": {"selected_units": len(selected)},
            "gaps": [],
            "usage": {"github_requests_total": client.state["github_requests"]},
        }
    finally:
        client.close()
