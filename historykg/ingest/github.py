"""GitHub reads for the course profile. The caller owns the request budget and capture."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com/"
FULL_HISTORY = "full_history_v1"
FULL_MAX_REQUESTS = 5000


class CollectionBlocked(RuntimeError):
    """A request budget or GitHub rate limit stopped collection."""


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class GitHubClient:
    def __init__(self, client: httpx.Client, *, sleep: Callable[[float], None]):
        self.http = client
        self.sleep = sleep

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        url = httpx.URL(API).join(path)
        if (url.scheme, url.host, url.port) != ("https", "api.github.com", None) or url.userinfo:
            raise GitHubError("分页链接超出 GitHub API 范围。")
        for attempt in range(3):
            try:
                response = self.http.get(url, params=params)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                self.sleep(2**attempt)
                continue
            status = response.status_code
            if status == 200:
                return response
            headers = response.headers
            if status in (403, 429):
                retry_after = headers.get("retry-after")
                exhausted = headers.get("x-ratelimit-remaining") == "0"
                rate_limited = status == 429 or "rate limit" in response.text.lower()
                if retry_after or exhausted or rate_limited:
                    if attempt == 2:
                        raise CollectionBlocked("GitHub 限流，额度恢复后可续采。")
                    try:
                        if retry_after:
                            wait = max(1.0, float(retry_after))
                        elif exhausted and "x-ratelimit-reset" in headers:
                            wait = max(1.0, int(headers["x-ratelimit-reset"]) - time.time() + 1)
                        else:
                            wait = 60.0
                    except ValueError:
                        wait = 60.0
                    self.sleep(wait)
                    continue
            if status >= 500 and attempt < 2:
                self.sleep(2**attempt)
                continue
            raise GitHubError(f"GitHub API 返回 HTTP {status}。", status=status)
        raise AssertionError("unreachable")

    def get_json(self, path: str, params: dict | None = None):
        return self._get(path, params).json()

    def pages(self, path: str, params: dict | None = None) -> Iterator[dict]:
        url, params = path, {"per_page": 100, **(params or {})}
        while url:
            response = self._get(url, params)
            rows = response.json()
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise GitHubError("GitHub 讨论分页应返回对象列表。")
            yield from rows
            url, params = response.links.get("next", {}).get("url"), None


@dataclass
class ThreadPayload:
    """One issue or PR and its attached text, compatible with the frozen capture format."""

    repo: str
    number: int
    thread_type: str
    thread: dict
    issue_comments: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    review_comments: list[dict] = field(default_factory=list)
    unread: set[str] = field(default_factory=set)

    @classmethod
    def from_capture(cls, row: dict) -> ThreadPayload:
        return cls(**{**row, "unread": set(row.get("unread", []))})

    def objects(self) -> Iterator[tuple[str, str, dict]]:
        yield "body", str(self.number), self.thread
        for kind, items in (
            ("issue_comment", self.issue_comments),
            ("review", self.reviews),
            ("review_comment", self.review_comments),
        ):
            for item in items:
                yield kind, str(item["id"]), item


def discussion_mapping(source: dict) -> dict | None:
    """Read an origin key from either a current or an archived source document."""
    return source.get("discussion_mapping") or source.get("relore_mapping")


_TEXT_FIELDS = {
    "id",
    "body",
    "html_url",
    "author_association",
    "created_at",
    "updated_at",
    "submitted_at",
    "in_reply_to_id",
}
_THREAD_FIELDS = {
    "number",
    "title",
    "state",
    "closed_at",
    "merged_at",
    "merged",
    "merge_commit_sha",
}


def _keep_text(raw: dict, extra: set[str] | None = None) -> dict:
    # Full JSON stays in the HTTP capture. The thread carries only downstream fields.
    kept = {key: raw[key] for key in _TEXT_FIELDS | (extra or set()) if key in raw}
    if login := (raw.get("user") or {}).get("login"):
        kept["user"] = {"login": login}
    return kept


def fetch_thread(client: GitHubClient, repo: str, number: int) -> ThreadPayload:
    issue_path = f"repos/{repo}/issues/{number}"
    pr_path = f"repos/{repo}/pulls/{number}"
    issue = client.get_json(issue_path)
    if not isinstance(issue, dict) or issue.get("number") != number:
        raise GitHubError("GitHub 返回的讨论编号不符。")
    is_pr = "pull_request" in issue
    unread: set[str] = set()
    merged = issue
    if is_pr:
        try:
            detail = client.get_json(pr_path)
            if not isinstance(detail, dict) or detail.get("number") != number:
                raise GitHubError("GitHub 返回的 PR 编号不符。")
            merged = {**issue, **detail}
        except GitHubError as exc:
            if exc.status not in {404, 410}:
                raise
            unread.add("pr_detail")

    def comments(kind: str, path: str) -> list[dict]:
        by_id = {}
        try:
            for row in client.pages(path):
                by_id[row["id"]] = _keep_text(row)
        except GitHubError as exc:
            if exc.status not in {404, 410, 422}:
                raise
            unread.add(kind)
        return list(by_id.values())

    return ThreadPayload(
        repo=repo,
        number=number,
        thread_type="pr" if is_pr else "issue",
        thread=_keep_text(merged, _THREAD_FIELDS),
        issue_comments=comments("issue_comment", issue_path + "/comments")
        if issue.get("comments") != 0
        else [],
        reviews=comments("review", pr_path + "/reviews") if is_pr else [],
        review_comments=comments("review_comment", pr_path + "/comments") if is_pr else [],
        unread=unread,
    )


def fetch_closing_prs(
    client: GitHubClient, repo: str, issue_numbers: list[int], *, batch_size: int = 25
) -> list[dict]:
    """Read official GitHub GraphQL closedByPullRequestsReferences for closed issues."""
    if not issue_numbers or "Authorization" not in client.http.headers:
        return []
    owner, name = repo.split("/", 1)
    rows: list[dict] = []
    ordered = sorted({int(n) for n in issue_numbers})
    for idx in range(0, len(ordered), batch_size):
        chunk = ordered[idx : idx + batch_size]
        aliases = "\n".join(
            f"i{i}: issue(number: {n}) {{ __typename number closed closedAt "
            "repository { nameWithOwner } "
            "closedByPullRequestsReferences(first: 10) { "
            "nodes { __typename number merged mergedAt url repository { nameWithOwner } } } }"
            for i, n in enumerate(chunk)
        )
        query = (
            f'query {{ repository(owner: "{owner}", name: "{name}") {{ {aliases} }} }}'
        )
        response = client.http.post(API + "graphql", json={"query": query})
        if response.status_code != 200:
            raise GitHubError(
                f"GitHub GraphQL 返回 HTTP {response.status_code}。",
                status=response.status_code,
            )
        body = response.json()
        repo_node = ((body.get("data") or {}).get("repository")) or {}
        nodes = [v for v in repo_node.values() if isinstance(v, dict)]
        rows.append({"query": query, "batch": idx // batch_size, "nodes": nodes})
    return rows
