"""Exercise collection over GitHub-shaped HTTP responses and real database backends."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from historykg import collector
from historykg.ingest.github import GitHubClient, ThreadPayload, fetch_thread

REPO = "example/toy"
URL = "https://github.com/" + REPO


def fake_service():
    fake = SimpleNamespace(requests=[], missing=set())
    headers = []
    prefix = f"/repos/{REPO}"
    issue = {"number": 1, "title": "Cache protocol fails", "body": "Cache protocol discussion",
             "comments": 2, "html_url": URL + "/issues/1"}
    pr = {"number": 2, "title": "Cache protocol fix", "body": "Cache protocol repair, fixes #1",
          "comments": 0, "pull_request": {}, "html_url": URL + "/pull/2"}
    responses = {
        "": {"private": False, "language": "Python"},
        "/issues": [pr, issue],
        "/pulls": [pr],
        "/issues/1": issue,
        "/issues/2": pr,
        "/pulls/2": {**pr, "merged_at": "2026-01-01T00:00:00Z", "merged": True},
        "/pulls/2/reviews": [{"id": 21, "body": "Cache protocol review"}],
        "/pulls/2/comments": [{"id": 22, "body": "Cache protocol inline discussion",
                               "in_reply_to_id": 20}],
    }

    def handle(request):
        fake.requests.append(str(request.url))
        headers.append(dict(request.headers))
        assert request.url.host == "api.github.com" and request.url.path.startswith(prefix)
        path = request.url.path.removeprefix(prefix)
        if path in fake.missing:
            return httpx.Response(404)
        if path == "/issues/1/comments":
            if request.url.params.get("page") == "2":
                return httpx.Response(200, json=[{"id": 12, "body": "Cache protocol second"}])
            link = request.url.copy_merge_params({"page": 2})
            return httpx.Response(200, json=[{"id": 11, "body": "Cache protocol first"}],
                                  headers={"link": f'<{link}>; rel="next"'})
        if path in responses:
            return httpx.Response(200, json=responses[path])
        return httpx.Response(404)

    return fake, headers, httpx.MockTransport(handle)


def test_collect_search_replay_idempotency_and_scope(database_url, tmp_path):
    fake, headers, transport = fake_service()
    result = collector.collect_repo(
        URL,
        database_url=database_url,
        token="",
        transport=transport,
        output_dir=tmp_path / "run",
    )
    assert result["status"] == "ok", result
    assert result["indexed_threads"] == 2
    assert result["github_requests"] > 6  # actual reviews, inline comments, paginated issue replies
    assert all("authorization" not in item for item in headers)
    capture = json.loads((tmp_path / "run/capture.json").read_text())
    assert len(next(p for p in capture["payloads"] if p["number"] == 1)["issue_comments"]) == 2
    assert any("page=" in item["url"] for item in capture["http_responses"])
    assert "Cache protocol" in capture["payloads"][0]["thread"]["body"]

    replayed = collector.replay_capture(result["capture_path"], database_url=database_url)
    assert replayed["status"] == "ok"
    assert replayed["documents_written"] == 0
    assert replayed["counts"] == result["counts"]
    hits = collector.search_history(REPO, "cache protocol", database_url=database_url)
    assert hits["status"] == "ok", hits
    assert all(h["repo"] == REPO and h["url"] and h["snippet"] for h in hits["hits"])
    assert (
        collector.search_history("other/repo", "cache", database_url=database_url)["status"]
        == "empty"
    )
    assert (
        collector.search_history(REPO, "unfindableword", database_url=database_url)["status"]
        == "empty"
    )
    assert collector.doctor(database_url)["source"]["implementation"] == "historykg"
    assert fake.requests


def test_request_budget_preserves_usable_prefix(database_url, tmp_path):
    _, _, transport = fake_service()
    result = collector.collect_repo(
        URL,
        database_url=database_url,
        token="",
        transport=transport,
        max_requests=7,
        output_dir=tmp_path / "limited",
    )
    assert result["status"] == "partial", result
    assert result["github_requests"] == 7
    assert result["indexed_threads"] == 1
    assert result["counts"]["threads"] == 1
    assert result["gaps"]
    replayed = collector.replay_capture(result["capture_path"], database_url=database_url)
    assert replayed["status"] == "partial"
    assert replayed["collection_gaps"]


def test_selected_resume_preserves_pages_and_cumulative_requests(database_url, tmp_path):
    fake, _, transport = fake_service()
    selected = [{"kind": "pr", "number": 2}, {"kind": "issue", "number": 1}]
    first = collector.collect_repo(
        URL,
        selected=selected,
        initial_requests=2,
        database_url=database_url,
        token="",
        transport=transport,
        max_requests=8,
        output_dir=tmp_path / "first",
    )
    assert first["status"] == "partial"
    assert first["github_requests"] == 8
    previous_requests = len(fake.requests)
    resumed = collector.collect_repo(
        URL,
        selected=selected,
        resume_capture=first["capture_path"],
        database_url=database_url,
        token="",
        transport=transport,
        max_requests=30,
        output_dir=tmp_path / "resumed",
        profile_version="course_small_v1",
    )
    assert resumed["status"] == "ok", resumed
    assert resumed["profile_version"] == "course_small_v1"
    assert resumed["indexed_threads"] == 2
    assert resumed["github_requests"] > first["github_requests"]
    assert len(fake.requests) > previous_requests
    capture = json.loads(Path(resumed["capture_path"]).read_text())
    issue = next(p for p in capture["payloads"] if p["number"] == 1)
    assert len(issue["issue_comments"]) == 2
    with pytest.raises(ValueError, match="冻结selected"):
        collector.collect_repo(
            URL,
            selected=selected[:1],
            resume_capture=first["capture_path"],
            database_url=database_url,
            transport=transport,
        )


def test_interrupt_keeps_budget_and_completed_response_checkpoint(database_url, tmp_path):
    _, _, upstream = fake_service()
    calls = []

    def interrupted(request):
        calls.append(1)
        if len(calls) == 7:
            raise KeyboardInterrupt()
        return upstream.handle_request(request)

    selected = [{"kind": "pr", "number": 2}, {"kind": "issue", "number": 1}]
    with pytest.raises(KeyboardInterrupt):
        collector.collect_repo(
            URL,
            selected=selected,
            token="",
            database_url=database_url,
            transport=httpx.MockTransport(interrupted),
            output_dir=tmp_path / "cut",
        )
    capture = json.loads((tmp_path / "cut/capture.json").read_text())
    assert capture["checkpoint"] is True
    assert capture["result"]["github_requests"] == 7  # in-flight attempt is already counted
    assert len(capture["http_responses"]) == 6
    assert len(capture["payloads"]) == 1
    resumed = collector.collect_repo(
        URL,
        selected=selected,
        token="",
        database_url=database_url,
        transport=upstream,
        resume_capture=tmp_path / "cut/capture.json",
        output_dir=tmp_path / "continued",
    )
    assert resumed["status"] == "ok" and resumed["indexed_threads"] == 2
    assert resumed["github_requests"] > 7


def test_budget_before_first_thread_is_blocked(database_url, tmp_path):
    _, _, transport = fake_service()
    result = collector.collect_repo(
        URL,
        database_url=database_url,
        token="",
        transport=transport,
        max_requests=1,
        output_dir=tmp_path / "blocked",
    )
    assert result["status"] == "blocked"
    assert result["indexed_threads"] == 0
    assert result["github_requests"] == 1
    replayed = collector.replay_capture(result["capture_path"], database_url=database_url)
    assert replayed["status"] == "blocked"


def test_unread_review_is_partial(database_url, tmp_path):
    fake, _, transport = fake_service()
    fake.missing.add("/pulls/2/reviews")
    result = collector.collect_repo(
        URL,
        database_url=database_url,
        token="",
        transport=transport,
        max_issues=0,
        output_dir=tmp_path / "partial",
    )
    assert result["status"] == "partial", result
    assert result["indexed_threads"] == 1
    assert any("review" in g.get("parts", []) for g in result["gaps"])


def test_missing_pr_detail_does_not_claim_complete(database_url, tmp_path):
    fake, _, transport = fake_service()
    fake.missing.add("/pulls/2")
    result = collector.collect_repo(URL, database_url=database_url, token="", transport=transport,
                                    max_issues=0, output_dir=tmp_path)
    assert result["status"] == "partial" and result["indexed_threads"] == 1
    assert result["gaps"][0]["parts"] == ["pr_detail"]


def test_partial_refresh_keeps_previously_indexed_review(database_url):
    _, _, transport = fake_service()
    with httpx.Client(transport=transport) as http:
        pr = fetch_thread(GitHubClient(http, sleep=lambda _: None), REPO, 2)
    assert collector.index_threads([pr], database_url=database_url)["status"] == "ok"
    pr.reviews = []
    pr.unread.add("review")
    assert collector.index_threads([pr], database_url=database_url)["status"] == "partial"
    hits = collector.search_history(REPO, "cache protocol", database_url=database_url)["hits"]
    assert any(h["source_type"] == "review" and h["source_id"] == "21" for h in hits)
    pr.unread.clear()
    assert collector.index_threads([pr], database_url=database_url)["status"] == "ok"
    hits = collector.search_history(REPO, "cache protocol", database_url=database_url)["hits"]
    assert not any(h["source_type"] == "review" for h in hits)


def test_rate_limit_is_not_empty(database_url, tmp_path):
    def limited(request):
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": str(int(time.time()) + 300),
            },
        )

    result = collector.collect_repo(
        URL,
        database_url=database_url,
        transport=httpx.MockTransport(limited),
        output_dir=tmp_path / "rate",
        token="",
    )
    assert result["status"] == "blocked", result
    assert result["github_requests"] == 1


def test_retries_count_against_budget(database_url, tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "_retry_wait", lambda seconds: None)
    result = collector.collect_repo(
        URL,
        database_url=database_url,
        transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"message": "busy"})),
        max_requests=2,
        output_dir=tmp_path / "retry",
        token="",
    )
    assert result["status"] == "blocked"
    assert result["github_requests"] == 2


@pytest.mark.parametrize(
    "url", ["https://evil.invalid/a/b", "owner/repo", "https://github.com/a/b/issues/1"]
)
def test_invalid_url_never_calls_network(url, tmp_path):
    def forbidden(request):
        pytest.fail("invalid input caused a network request")

    result = collector.collect_repo(url, transport=httpx.MockTransport(forbidden))
    assert result["status"] == "unsupported"


def test_empty_repository_is_empty(database_url, tmp_path):
    def empty(request):
        return httpx.Response(
            200,
            json={"private": False, "language": "Python"}
            if request.url.path == f"/repos/{REPO}"
            else [],
        )

    result = collector.collect_repo(
        URL,
        database_url=database_url,
        transport=httpx.MockTransport(empty),
        token="",
        output_dir=tmp_path / "empty",
    )
    assert result["status"] == "empty"


def test_database_failure_is_visible(tmp_path):
    url = "sqlite:///" + (tmp_path / "missing" / "index.sqlite3").as_posix()
    result = collector.search_history(REPO, "cache", database_url=url)
    assert result["status"] == "error"
    assert collector.doctor(url)["status"] == "error"


def test_cli_returns_json_without_extra_answer(database_url, monkeypatch, capsys):
    monkeypatch.setenv("HISTORYKG_DATABASE_URL", database_url)
    assert collector.initialize_database()["status"] == "ok"
    code = collector.main(["search", "unfindableword", "--repo", REPO])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "empty"


def test_index_rejects_mixed_repository_payloads(database_url):
    payload = ThreadPayload(REPO, 1, "issue", {"title": "Cache protocol"})
    other = ThreadPayload("other/repo", 2, "pr", {"title": "Cache protocol"})
    result = collector.index_threads([payload, other], database_url=database_url)
    assert result["status"] == "error"


def test_repository_case_is_normalized_for_index_and_search(database_url):
    payload = ThreadPayload("Example/Toy", 1, "issue", {"title": "Cache protocol"})
    other = ThreadPayload(REPO, 2, "pr", {"body": "Cache protocol"})
    result = collector.index_threads([payload, other], database_url=database_url)
    assert result["status"] == "ok", result
    assert (
        collector.search_history("Example/Toy", "cache protocol", database_url=database_url)[
            "status"
        ]
        == "ok"
    )
    assert payload.repo == "Example/Toy"  # normalizing the copy does not mutate the caller's data


def test_malformed_api_response_is_error(database_url, tmp_path):
    result = collector.collect_repo(
        URL,
        database_url=database_url,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text="<html>proxy error</html>")
        ),
        token="",
        output_dir=tmp_path / "malformed",
    )
    assert result["status"] == "error", result
    assert result["gaps"][0]["type"] == "JSONDecodeError"
