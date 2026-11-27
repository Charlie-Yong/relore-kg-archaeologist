"""Full history inventory and a persistent, model-free preparation boundary."""

from pathlib import Path

import httpx

from historykg import pipeline
from historykg.ingest.discovery import FULL_PROFILE, discover
from historykg.io import read_json


def test_full_inventory_follows_all_pages_and_freezes_git_refs(tmp_path):
    listed = []
    prefix = "/repos/example/toy"

    def handler(request):
        route = request.url.path.removeprefix(prefix)
        listed.append((route, request.url.params.get("page")))
        if route == "":
            return httpx.Response(
                200, json={"id": 1, "language": "Python", "default_branch": "main"},
            )
        if route == "/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "1" * 40}})
        if route == "/tags":
            return httpx.Response(200, json=[{"name": "v1", "commit": {"sha": "2" * 40}}])
        if route == "/releases":
            return httpx.Response(
                200, json=[{"tag_name": "v1"}, {"tag_name": "draft", "draft": True}],
            )
        page = request.url.params.get("page")
        if route == "/issues" and page == "2":
            return httpx.Response(200, json=[{"number": 2, "pull_request": {}}, {"number": 1}])
        if route == "/issues":
            link = f'<https://api.github.com{prefix}/issues?page=2>; rel="next"'
            return httpx.Response(200, json=[{"number": 3}], headers={"link": link})
        if route == "/pulls":
            return httpx.Response(200, json=[{"number": 2}, {"number": 4}])
        raise AssertionError(route)

    result = discover(
        "https://github.com/example/toy", snapshot_dir=tmp_path, dataset_id="toy",
        profile=FULL_PROFILE, transport=httpx.MockTransport(handler),
    )
    snapshot = read_json(Path(result["artifacts"]["plan"]))
    assert ("/issues", "2") in listed
    assert {(x["kind"], x["number"]) for x in snapshot["selected"]} == {
        ("pr", 2), ("pr", 4), ("issue", 1), ("issue", 3),
    }
    assert snapshot["default_branch_sha"] == "1" * 40
    assert snapshot["tags"][0]["commit"]["sha"] == "2" * 40
    assert [r["tag_name"] for r in snapshot["releases"]] == ["v1"]


def test_preparation_preserves_no_model_boundary_across_resume(tmp_path, monkeypatch):
    settings = {"jobs_root": str(tmp_path / "jobs"), "data_root": str(tmp_path / "data")}
    executed = []

    def stage(job, _directory, _settings):
        current = job["stage"]
        executed.append(current)
        if executed == ["discover", "collect"]:
            return {"status": "blocked", "error": {"code": "github_rate_limit"}}
        if current == "extract":
            return {"status": "blocked", "error": {"code": "provider_balance_exhausted"}}
        return {"status": "ok"}

    monkeypatch.setattr(pipeline, "_stage", stage)
    monkeypatch.setattr("historykg.extract.stage.estimate_extract",
                        lambda _root, **_: {"initial_requests": 10})
    job = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy", "profile": "full_history_v1"},
        config=settings, prepare_only=True,
    )
    assert job["stage"] == "collect" and job["prepare_only"]
    job = pipeline.resume_build(job["job_id"], config=settings, background=False)
    assert executed == ["discover", "collect", "collect", "code"]
    assert job["error"]["code"] == "extract_estimate_ready"
    assert read_json(job["artifacts"]["extract_estimate"]) == {"initial_requests": 10}
    job = pipeline.resume_build(job["job_id"], config=settings, background=False)
    assert executed[-1] == "extract" and "prepare_only" not in job
    assert job["error"]["code"] == "provider_balance_exhausted"


def test_full_collection_resumes_above_course_thread_limit(tmp_path):
    from historykg.collector import collect_repo

    selected = [{"kind": "issue", "number": n} for n in range(1, 42)]
    seen = []
    interrupted = True

    def handler(request):
        tail = request.url.path.removeprefix("/repos/example/toy")
        seen.append(tail)
        if not tail:
            return httpx.Response(200, json={"language": "Python"})
        number = int(tail.rsplit("/", 1)[-1])
        if number == 3 and interrupted:
            return httpx.Response(403, json={}, headers={"Retry-After": "30"})
        return httpx.Response(200, json={"number": number, "title": str(number),
                                         "body": "discussion", "comments": 0})

    options = dict(
        database_url="sqlite:///" + str(tmp_path / "discussions.sqlite3"),
        output_dir=tmp_path / "collection", selected=selected, max_requests=5000,
        profile_version="full_history_v1", transport=httpx.MockTransport(handler),
    )
    url = "https://github.com/example/toy"
    first = collect_repo(url, **options)
    assert first["status"] == "blocked" and first["indexed_threads"] == 2
    interrupted = False
    second = collect_repo(url, resume_capture=first["capture_path"], **options)
    assert second["status"] == "ok" and second["indexed_threads"] == 41
    assert seen.count("/issues/1") == seen.count("/issues/2") == 1
    assert seen.count("/issues/3") == 2
    assert second["github_requests"] == len(seen)


def test_full_history_resolves_specific_versions_and_file_revisions():
    from historykg.query.retrieval import history_scope_seeds

    path = "src/toy/core.py"
    first, second = "1" * 40, "2" * 40
    package = {"entities": [
        {"id": "released", "type": "Release", "properties": {"tag": "2.2.0"}},
        {"id": "prerelease", "type": "Release", "properties": {"tag": "2.2.0rc1"}},
        {"id": "file-a", "type": "File", "properties": {"path": path, "commit_sha": first}},
        {"id": "file-b", "type": "File", "properties": {"path": path, "commit_sha": second}},
        {"id": "different", "type": "File",
         "properties": {"path": "src/toy/other.py", "commit_sha": first}},
    ]}
    assert history_scope_seeds("2.2.0rc1 timeline", "timeline", package) == ["prerelease"]
    assert history_scope_seeds("版本 2.2.0 的日期", "timeline", package) == ["released"]
    assert history_scope_seeds(f"Compare {path} at {first} and {second}", "compare", package) == [
        "file-a", "file-b",
    ]
    assert history_scope_seeds(f"Compare {path} at {first}", "compare", package) == []


def test_full_history_gets_release_date_after_long_api_body_as_exact_span():
    from historykg.io import freeze_api_source, make_evidence
    from historykg.query.retrieval import focused_history_context

    source = freeze_api_source(
        dataset_id="toy", repo="example/toy", endpoint="repos/example/toy/releases",
        payload=[{"body": "old release notes " * 1500, "published_at": "2026-01-01T00:00:00Z",
                  "tag_name": "2.2.0"}],
        retrieved_at="2026-01-02T00:00:00Z",
    )
    ref = make_evidence(source, source["text"])
    event = {"type": "HasRelease", "to_id": "v2", "evidence_ids": [ref["evidence_id"]]}
    package = {
        "entities": [{"id": "v2", "properties": {"tag": "2.2.0"}}],
        "sources": [source], "evidence": [ref],
    }
    candidates = focused_history_context(
        package, kind="timeline", seeds=["v2"], paths=[], timeline=[event], question="2.2.0?",
    )
    assert len(candidates) == 1
    span = candidates[0]
    assert span["start"] > 12_000 and len(span["quote"]) < 1000
    assert span["quote"] == source["text"][span["start"]:span["end"]]
    assert '"published_at": "2026-01-01T00:00:00Z"' in span["quote"]
    assert '"tag_name": "2.2.0"' in span["quote"]
