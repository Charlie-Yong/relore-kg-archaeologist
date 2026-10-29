"""P2 C9 checks. Real Neo4j tests clean only their generated dataset namespace."""

import json
import os
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from historykg import collector
from historykg.graph import GraphStore, load_dataset
from historykg.io import make_evidence, read_jsonl, write_jsonl, write_manifest
from historykg.query import prepare_query, query
from historykg.query.frozen_index import drop_index
from historykg.query.retrieval import resolve_seeds

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/toy_v1"


def refresh(root):
    metadata = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return write_manifest(root, **{k: v for k, v in metadata.items()
                                  if k not in {"files", "sources"}})


@pytest.fixture
def sample(tmp_path):
    root = tmp_path / "dataset"
    shutil.copytree(FIXTURE, root)
    dataset = "p2_test_" + uuid.uuid4().hex
    for file in root.rglob("*.jsonl"):
        rows = read_jsonl(file)
        for r in rows:
            if "dataset_id" in r:
                r["dataset_id"] = dataset
        write_jsonl(file, rows)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["dataset_id"] = dataset
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    refresh(root)
    return root, dataset


@pytest.fixture
def graph_config(tmp_path):
    uri = os.environ.get("P2_TEST_NEO4J_URI")
    if not uri:
        pytest.skip("P2_TEST_NEO4J_URI enables actual namespace-scoped Neo4j integration")
    database = os.environ.get("P2_TEST_DATABASE_URL") or (
        "sqlite:///" + (tmp_path / "relore.sqlite3").as_posix()
    )
    assert collector.initialize_database(database)["status"] == "ok"
    config = {"neo4j_uri": uri, "database_url": database,
              "neo4j_user": os.environ.get("P2_TEST_NEO4J_USER"),
              "neo4j_password": os.environ.get("P2_TEST_NEO4J_PASSWORD"),
              "query_output_root": str(tmp_path / "queries")}
    owned = []
    config["_owned"] = owned
    yield config
    with GraphStore(config) as store:
        for dataset in owned:
            saved = store.snapshot(dataset)
            if saved and saved.get("retrieval_index"):
                drop_index(database, saved["retrieval_index"])
            store.delete_dataset(dataset)


def loaded(sample, graph_config):
    root, dataset = sample
    graph_config["_owned"].append(dataset)
    result = load_dataset(root, config=graph_config)
    assert result["status"] == "ok", result
    return root, dataset


def synthetic_answerer(**kwargs):
    source = kwargs["context"][0]
    evidence = make_evidence({**source, "repo": kwargs["repo"],
                              "dataset_id": kwargs["dataset_id"], "text": source["quote"]},
                             source["quote"], start=0)
    return {"status": "ok", "claims": [{"text": source["quote"],
                                           "evidence_ids": [evidence["evidence_id"]]}],
            "evidence": [evidence], "gaps": [], "run_id": "synthetic_test_only",
            "usage": {}, "context": {"fragments": kwargs["context"]}}


def test_idempotent_load_and_isolated_dataset(sample, graph_config):
    root, dataset = loaded(sample, graph_config)
    with GraphStore(graph_config) as store:
        before = store.snapshot(dataset)
        assert store.snapshot("other_dataset_" + dataset) is None
    repeat = load_dataset(root, config=graph_config)
    assert repeat["graph_ready"] and repeat["retrieval_ready"]
    with GraphStore(graph_config) as store:
        after = store.snapshot(dataset)
        assert before == after
        assert all(r["dataset_id"] == dataset for r in after["relations"])


@pytest.mark.parametrize("fault", ["span", "endpoint", "dataset", "manifest"])
def test_reject_invalid_records_before_write(sample, graph_config, fault):
    root, dataset = sample
    if fault == "span":
        file = root / "p1/evidence.jsonl"
        rows = read_jsonl(file)
        rows[0]["start"] += 1
    elif fault == "endpoint":
        file = root / "p1/relations.jsonl"
        rows = read_jsonl(file)
        rows[0]["to_id"] = "missing_endpoint"
    elif fault == "dataset":
        file = root / "p1/entities.jsonl"
        rows = read_jsonl(file)
        rows[0]["dataset_id"] = "another_dataset"
    else:
        file = root / "sources.jsonl"
        rows = read_jsonl(file)
        rows.pop()
    write_jsonl(file, rows)
    refresh(root)
    result = load_dataset(root, config=graph_config)
    assert result["status"] == "error" and result["rejected"]
    assert not result["graph_ready"] and not result["retrieval_ready"]
    with GraphStore(graph_config) as store:
        assert store.snapshot(dataset) is None


def test_same_dataset_cannot_overwrite_frozen_payload(sample, graph_config):
    root, dataset = loaded(sample, graph_config)
    file = root / "p1/entities.jsonl"
    rows = read_jsonl(file)
    rows[0]["properties"]["display_name"] = "Changed after freezing"
    write_jsonl(file, rows)
    refresh(root)
    result = load_dataset(root, config=graph_config)
    assert result["status"] == "error" and not result["graph_ready"]
    with GraphStore(graph_config) as store:
        assert "Changed after freezing" not in json.dumps(store.snapshot(dataset))


def test_no_decision_still_returns_issue_pr_commit_file_chain(sample, graph_config):
    root, dataset = sample
    for name in ("entities", "relations", "decisions"):
        write_jsonl(root / "p4" / (name + ".jsonl"), [])
    refresh(root)
    loaded(sample, graph_config)
    result = prepare_query({"dataset_id": dataset, "question": "Trace #1", "kind": "trace"},
                           config=graph_config)
    assert result["status"] == "ok"
    assert any({r["type"] for r in p["relations"]} >= {"Closes", "MergedAs", "Touches"}
               for p in result["paths"])
    assert not any("Decision:" in i for p in result["paths"] for i in p["entity_ids"])


def test_claims_to_close_never_becomes_close(sample, graph_config):
    root, dataset = sample
    file = root / "p1/relations.jsonl"
    write_jsonl(file, [r for r in read_jsonl(file) if r["type"] != "Closes"])
    refresh(root)
    loaded(sample, graph_config)
    result = prepare_query({"dataset_id": dataset, "question": "Trace #1", "kind": "trace"},
                           config=graph_config)
    kinds = {r["type"] for p in result["paths"] for r in p["relations"]}
    assert "ClaimsToClose" in kinds and "Closes" not in kinds


def test_different_tags_on_same_commit_remain_distinct(sample, graph_config):
    _, dataset = loaded(sample, graph_config)
    with GraphStore(graph_config) as store:
        releases = [e for e in store.snapshot(dataset)["entities"] if e["type"] == "Release"]
    assert len(releases) == 2 and len({r["id"] for r in releases}) == 2
    assert {r["properties"]["tag"] for r in releases} == {"v1.0", "V1.0"}
    assert len({r["properties"]["commit_sha"] for r in releases}) == 1


def test_ab_share_seeds_sources_and_adapter_code_visibility(sample, graph_config):
    _, dataset = loaded(sample, graph_config)
    request = {"dataset_id": dataset, "question": "cache timeout"}
    a = prepare_query(request, config={**graph_config, "system": "A"})
    b = prepare_query(request, config={**graph_config, "system": "B"})
    assert a["seed_ids"] == b["seed_ids"]
    assert a["retrieval"] == b["retrieval"]
    assert a["retrieval"]["backend"]["discussion"] == "relore.search_history"
    assert a["paths"] == [] and b["paths"]
    assert any(a["source_by_id"][c["source_id"]]["kind"] == "code" for c in a["candidates"])
    assert a["retrieval"]["backend"]["visible_source_ids"] == sorted(a["source_by_id"])


def test_query_states_and_trace_evidence(sample, graph_config):
    _, dataset = loaded(sample, graph_config)
    config = {**graph_config, "answerer": synthetic_answerer}
    request = {"dataset_id": dataset, "question": "cache timeout", "kind": "trace"}
    ok = query(request, config=config)
    assert ok.status == "ok" and ok.claims and ok.paths and ok.evidence
    assert all(set(c["evidence_ids"]) <= {e["evidence_id"] for e in ok.evidence}
               for c in ok.claims)
    assert all(p["entities"] and [e["id"] for e in p["entities"]] == p["entity_ids"]
               for p in ok.paths)
    output = Path(ok.model_extra["artifacts"]["query_run"])
    assert (output / "retrieval.json").is_file() and (output / "result.json").is_file()
    empty = query({**request, "question": "zzunfindableuniquezz"}, config=config)
    assert empty.status == "empty" and empty.gaps and not empty.claims
    for kind in ("missing_kind", "dependencies", "compare"):
        result = query({**request, "kind": kind}, config=config)
        assert result.status == "unsupported" and result.gaps
    assert query({**request, "question": ""}, config=config).status == "unsupported"
    assert query({**request, "kind": "timeline"}, config=config).status == "ok"


def test_service_failure_is_error_not_empty(sample, graph_config):
    root, dataset = loaded(sample, graph_config)
    bad_graph = {**graph_config, "neo4j_uri": "bolt://127.0.0.1:1"}
    request = {"dataset_id": dataset, "question": "cache"}
    assert query(request, config=bad_graph).status == "error"
    assert not load_dataset(root, config=bad_graph)["graph_ready"]
    bad_retrieval = {**graph_config, "database_url": "postgresql://x@127.0.0.1:1/none"}
    result = load_dataset(root, config=bad_retrieval)
    assert not result["retrieval_ready"] and result["error"]
    with GraphStore(graph_config) as store:
        descriptor = store.snapshot(dataset)["retrieval_index"]
    drop_index(graph_config["database_url"], descriptor)
    assert query(request, config=graph_config).status == "error"


def test_citation_outside_visible_context_is_rejected(sample, graph_config):
    _, dataset = loaded(sample, graph_config)

    def broken_answerer(**kwargs):
        result = synthetic_answerer(**kwargs)
        result["context"] = {"fragments": []}
        return result

    result = query({"dataset_id": dataset, "question": "cache"},
                   config={**graph_config, "answerer": broken_answerer})
    assert result.status == "error" and not result.claims


def test_external_issue_number_is_not_resolved_into_local_subject():
    from historykg.graph.store import read_package
    package = read_package(FIXTURE)
    seeds, gaps = resolve_seeds("https://github.com/other/repo/issues/1", package, [])
    assert not seeds and gaps


def test_same_repo_mutation_does_not_change_frozen_relore_hits(tmp_path, graph_config):
    from fake_github import FakeGitHub
    from relore.github.fetch_thread import ThreadPayload

    from historykg.ingest.capture import map_capture

    repo = "example/p2-frozen-" + uuid.uuid4().hex[:10]
    fake = FakeGitHub(repo)
    old = fake.add_issue(1, title="Frozen cache protocol", body="sentinel_old cache protocol")
    payload = ThreadPayload(repo=repo, number=1, thread_type="issue", thread=old.payload)

    def freeze_version(name, thread):
        dataset = "p2_test_" + uuid.uuid4().hex
        root = tmp_path / name
        root.mkdir()
        capture = root / "capture.json"
        write = {"format": collector.CAPTURE, "repo": repo,
                 "retrieved_at": "2026-10-30T00:00:00Z", "relore_commit": collector.COMMIT,
                 "result": {"status": "ok", "gaps": []}, "http_responses": [],
                 "payloads": [{**asdict(thread), "unread": []}]}
        capture.write_text(json.dumps(write), encoding="utf-8")
        map_capture(capture, dataset_dir=root, dataset_id=dataset)
        graph_config["_owned"].append(dataset)
        result = load_dataset(root, config=graph_config)
        assert result["status"] == "ok", result
        return dataset

    assert collector.index_threads([payload], database_url=graph_config["database_url"])[
        "status"] == "ok"
    first = freeze_version("old", payload)
    request = {"dataset_id": first, "question": "cache protocol"}
    before = prepare_query(request, config={**graph_config, "system": "A"})
    assert before["retrieval"]["raw_relore"]["hits"]
    payload.thread = {**payload.thread, "body": "sentinel_new changed cache protocol"}
    assert collector.index_threads([payload], database_url=graph_config["database_url"])[
        "status"] == "ok"
    second = freeze_version("new", payload)
    global_hits = collector.search_history(repo, "cache protocol",
                                           database_url=graph_config["database_url"])
    assert any("sentinel_new" in hit["snippet"] for hit in global_hits["hits"])
    after = prepare_query(request, config={**graph_config, "system": "A"})
    newer = prepare_query({**request, "dataset_id": second}, config=graph_config)
    assert before["retrieval"] == after["retrieval"]
    assert before["candidates"] == after["candidates"]
    assert "sentinel_old" in json.dumps(after["retrieval"]["raw_relore"])
    assert "sentinel_new" not in json.dumps(after["retrieval"]["raw_relore"])
    assert "sentinel_new" in json.dumps(newer["retrieval"]["raw_relore"])
    result = query(request, config={**graph_config, "answerer": synthetic_answerer})
    assert result.status == "ok" and Path(result.model_extra["artifacts"]["query_run"]).exists()


def test_real_answerer_default_root_and_final_context_budget(sample, graph_config, monkeypatch):
    from historykg.io import make_source

    root, dataset = sample
    source = make_source(dataset_id=dataset, repo="example/toy", kind="code",
                         url="https://example.invalid/large.py", origin_key="large.py",
                         text="Oversized special cache feature.\n" * 900,
                         retrieved_at="2026-10-30T00:00:00Z")
    write_jsonl(root / "sources.jsonl", [*read_jsonl(root / "sources.jsonl"), source])
    refresh(root)
    loaded(sample, graph_config)
    seen = {}

    def no_paid_call(request, *, budget, validator):
        seen.update(request)
        fragments = json.loads(request["body"]["messages"][1]["content"])["context"]
        fragment = fragments[0]
        parsed = {"claims": [{"text": "Synthetic wiring check only", "evidence": [{
            "source_id": fragment["source_id"], "quote": fragment["quote"]}]}], "gaps": []}
        validator(parsed)
        return {"status": "ok", "parsed": parsed, "run_id": request["run_id"],
                "usage": {"actual_requests": 0}, "cache_hit": False, "new_requests": 0}

    monkeypatch.setattr("historykg.llm.answer.run_request", no_paid_call)
    result = query({"dataset_id": dataset, "question": "Oversized special cache feature"},
                   config=graph_config)
    assert result.status == "ok", result
    assert Path(seen["output_directory"]).is_relative_to(root / "llm")
    audit = json.loads((Path(result.model_extra["artifacts"]["query_run"]) /
                        "retrieval.json").read_text(encoding="utf-8"))
    final = audit["answer"]["context"]
    assert final["characters"] == len(final["rendered"]) <= 12000
    fragment = next(f for f in final["fragments"] if f["source_id"] == source["source_id"])
    assert fragment["end"] < len(source["text"])
    assert source["text"][fragment["start"]:fragment["end"]] == fragment["quote"]
    assert final["gaps"] and result.model_extra["usage"]["actual_requests"] == 0
