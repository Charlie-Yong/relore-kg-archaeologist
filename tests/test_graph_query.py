"""P2 C9 checks. Real Neo4j tests clean only their generated dataset namespace."""

import json
import os
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from historykg import collector
from historykg.contracts import CONTRACT_VERSION
from historykg.graph import GraphStore, load_dataset, validate_extended_dataset
from historykg.ids import entity_id, relation_id
from historykg.io import make_evidence, read_jsonl, write_jsonl, write_manifest
from historykg.query import prepare_query, query
from historykg.query.frozen_index import drop_index
from historykg.query.retrieval import context_candidates, resolve_seeds, subject_records

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/toy_v1"


def refresh(root):
    metadata = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return write_manifest(root, **{k: v for k, v in metadata.items()
                                  if k not in {"files", "sources"}})


def add_extended_graph_records(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    dataset, repo = manifest["dataset_id"], manifest["repo"]
    entities_path = root / "p1/entities.jsonl"
    relations_path = root / "p1/relations.jsonl"
    entities = read_jsonl(entities_path)
    relations = read_jsonl(relations_path)
    pull_request = next(
        entity for entity in entities
        if entity["type"] == "PullRequest" and entity["properties"]["number"] == 2
    )
    commit = next(entity for entity in entities if entity["type"] == "Commit")
    file = next(
        entity for entity in entities
        if entity["type"] == "File"
        and entity["properties"]["path"] == "toy/cache.py"
        and entity["properties"]["commit_sha"]
        == commit["properties"]["sha"]
    )
    sha, path = file["properties"]["commit_sha"], file["properties"]["path"]
    function_name = "cache"
    qualified_name = "toy.cache.cache"

    def developer(login, github_id):
        identity_key = (
            f"github:{github_id}" if github_id is not None
            else "login:" + login.casefold()
        )
        return {
            "contract_version": CONTRACT_VERSION,
            "dataset_id": dataset,
            "id": entity_id("Developer", repo, identity_key),
            "repo": repo,
            "type": "Developer",
            "key": identity_key,
            "properties": {
                "login": login,
                "display_name": login,
                "logins": [login],
                "github_user_id": github_id,
            },
            "evidence_ids": pull_request["evidence_ids"][:1],
        }

    def function(start_line, end_line):
        return {
            "contract_version": CONTRACT_VERSION,
            "dataset_id": dataset,
            "id": entity_id(
                "Function", repo, sha, path, qualified_name, start_line
            ),
            "repo": repo,
            "type": "Function",
            "key": [sha, path, qualified_name, start_line],
            "properties": {
                "commit_sha": sha,
                "path": path,
                "name": function_name,
                "qualified_name": qualified_name,
                "kind": "function",
                "start_line": start_line,
                "end_line": end_line,
                "scope": "module",
            },
            "evidence_ids": file["evidence_ids"][:1],
        }

    author, merger = developer("Alice", 101), developer("bob", None)
    function_record = function(1, 5)
    repeated_function = function(20, 24)
    assert function_record["id"] != repeated_function["id"]
    write_jsonl(
        entities_path,
        [*entities, author, merger, function_record, repeated_function],
    )

    def relation(kind, from_id, to_id, evidence_ids, method):
        return {
            "contract_version": CONTRACT_VERSION,
            "dataset_id": dataset,
            "id": relation_id(repo, kind, from_id, to_id),
            "repo": repo,
            "type": kind,
            "from_id": from_id,
            "to_id": to_id,
            "properties": {},
            "evidence_ids": evidence_ids,
            "method": method,
            "extractor_version": "test_extended_v1",
            "occurred_at": None,
        }

    write_jsonl(
        relations_path,
        [
            *relations,
            relation("Authored", author["id"], pull_request["id"],
                     pull_request["evidence_ids"][:1], "github_api"),
            relation("Merged", merger["id"], pull_request["id"],
                     pull_request["evidence_ids"][:1], "github_api"),
            relation("Defines", file["id"], function_record["id"],
                     file["evidence_ids"][:1], "ast"),
            relation("Defines", file["id"], repeated_function["id"],
                     file["evidence_ids"][:1], "ast"),
        ],
    )
    refresh(root)
    return (
        author,
        merger,
        pull_request,
        commit,
        file,
        function_record,
        repeated_function,
    )


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


def test_extended_entities_import_and_developer_to_function_path(sample, graph_config):
    root, dataset = sample
    (
        author,
        _merger,
        pull_request,
        commit,
        file,
        function,
        repeated_function,
    ) = add_extended_graph_records(root)
    loaded(sample, graph_config)
    with GraphStore(graph_config) as store:
        before = store.snapshot(dataset)
        assert {"Developer", "Function"} <= {e["type"] for e in before["entities"]}
        function_ids = {
            entity["id"] for entity in before["entities"]
            if entity["type"] == "Function"
        }
        assert function["id"] in function_ids
        assert repeated_function["id"] in function_ids
        assert function["id"] != repeated_function["id"]
        assert store.run(
            "MATCH (n:HGDeveloper {dataset_id:$dataset}) RETURN count(n) AS count",
            dataset=dataset,
        )[0]["count"] == 2
        assert store.run(
            "MATCH (n:HGFunction {dataset_id:$dataset}) RETURN count(n) AS count",
            dataset=dataset,
        )[0]["count"] == 2
    repeat = load_dataset(root, config=graph_config)
    assert repeat["status"] == "ok"
    with GraphStore(graph_config) as store:
        assert store.snapshot(dataset) == before

    default_prepared = prepare_query(
        {"dataset_id": dataset, "question": "Alice", "kind": "trace"},
        config=graph_config,
    )
    assert author["id"] in default_prepared["seed_ids"]
    assert default_prepared["method_version"] == "relore_common_rrf_graph_v2"
    expected = [
        author["id"],
        pull_request["id"],
        commit["id"],
        file["id"],
        function["id"],
    ]
    assert not any(
        path["entity_ids"] == expected for path in default_prepared["paths"]
    )

    prepared = prepare_query(
        {"dataset_id": dataset, "question": "Alice", "kind": "trace"},
        config={**graph_config, "graph_depth": 4},
    )
    assert author["id"] in prepared["seed_ids"]
    path = next(path for path in prepared["paths"] if path["entity_ids"] == expected)
    assert [relation["type"] for relation in path["relations"]] == [
        "Authored", "MergedAs", "Touches", "Defines"
    ]

    by_function = prepare_query(
        {
            "dataset_id": dataset,
            "question": "toy/cache.py::toy.cache.cache",
            "kind": "trace",
        },
        config={**graph_config, "graph_depth": 4},
    )
    assert function["id"] in by_function["seed_ids"]
    result = query(
        {"dataset_id": dataset, "question": "Alice", "kind": "trace"},
        config={
            **graph_config,
            "graph_depth": 4,
            "answerer": synthetic_answerer,
        },
    )
    assert result.status == "ok"
    assert any(
        {"Developer", "Function"} <= {entity["type"] for entity in path["entities"]}
        for path in result.paths
    )


def test_extended_subject_fallback_and_validation(sample):
    root, _dataset = sample
    add_extended_graph_records(root)
    package = {
        "manifest": json.loads((root / "manifest.json").read_text(encoding="utf-8")),
        "entities": read_jsonl(root / "p1/entities.jsonl"),
        "evidence": read_jsonl(root / "p1/evidence.jsonl"),
        "subjects": read_jsonl(root / "subjects.jsonl"),
    }
    subjects = subject_records(package)
    developer_subject = next(
        subject for subject in subjects if subject["entity_type"] == "Developer"
    )
    function_subject = next(
        subject for subject in subjects if subject["entity_type"] == "Function"
    )
    assert developer_subject["display_name"] == "Alice"
    assert {"Alice", "101"} <= set(developer_subject["aliases"])
    assert not any("github:101" in alias or alias.startswith("[")
                   for alias in developer_subject["aliases"])
    assert function_subject["display_name"] == "toy.cache.cache"
    assert {"cache", "toy/cache.py", "toy/cache.py::toy.cache.cache"} <= set(
        function_subject["aliases"]
    )
    assert not any(alias.startswith("[") for alias in function_subject["aliases"])

    seeds, gaps = resolve_seeds(
        "toy/cache.py::toy.cache.cache", package, []
    )
    function_ids = {
        entity["id"] for entity in package["entities"]
        if entity["type"] == "Function"
    }
    assert function_ids <= set(seeds)
    assert any("主体匹配多个" in gap for gap in gaps)
    assert validate_extended_dataset(root)["status"] == "ok"

    functions = read_jsonl(root / "p1/entities.jsonl")
    function = next(entity for entity in functions if entity["type"] == "Function")
    function["properties"]["path"] = "toy/other.py"
    function["key"][1] = "toy/other.py"
    function["id"] = entity_id(
        "Function",
        function["repo"],
        function["properties"]["commit_sha"],
        "toy/other.py",
        function["properties"]["qualified_name"],
        function["properties"]["start_line"],
    )
    write_jsonl(root / "p1/entities.jsonl", functions)
    relations = read_jsonl(root / "p1/relations.jsonl")
    defines = next(relation for relation in relations if relation["type"] == "Defines")
    defines["to_id"] = function["id"]
    defines["id"] = relation_id(
        function["repo"], "Defines", defines["from_id"], defines["to_id"]
    )
    write_jsonl(root / "p1/relations.jsonl", relations)
    refresh(root)
    report = validate_extended_dataset(root)
    assert report["status"] == "error"
    assert any("Defines必须连接同SHA同路径" in error for error in report["errors"])


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("developer_key", "Developer.key与github_user_id不一致"),
        ("developer_id", "稳定ID不匹配"),
        ("function_missing_start_line", "Function.key须为"),
        ("function_id_without_start_line", "稳定ID不匹配"),
    ],
)
def test_p3_developer_function_key_and_id_validation(sample, fault, message):
    root, _dataset = sample
    add_extended_graph_records(root)
    path = root / "p1/entities.jsonl"
    entities = read_jsonl(path)
    developer = next(
        entity for entity in entities
        if entity["type"] == "Developer" and entity["key"] == "github:101"
    )
    function = next(
        entity for entity in entities
        if entity["type"] == "Function"
        and entity["properties"]["start_line"] == 1
    )
    if fault == "developer_key":
        developer["key"] = ["github:999"]
    elif fault == "developer_id":
        developer["id"] = entity_id("Developer", developer["repo"], "login:alice")
    elif fault == "function_missing_start_line":
        function["key"] = function["key"][:3]
        function["properties"].pop("start_line")
    else:
        function["id"] = entity_id(
            "Function",
            function["repo"],
            function["properties"]["commit_sha"],
            function["properties"]["path"],
            function["properties"]["qualified_name"],
        )
    write_jsonl(path, entities)
    refresh(root)
    report = validate_extended_dataset(root)
    assert report["status"] == "error"
    assert any(message in error for error in report["errors"])


def test_p3_real_flask_identity_shape_matches_known_ids():
    from historykg.graph.store import _extended_entity_id

    repo = "pallets/flask"
    sha = "05e9c6bd630ecf4ec0ec884b1fc7901663737bc7"
    path = "src/flask/testing.py"
    qualified_name = "flask.testing._get_werkzeug_version"
    author = {
        "type": "Developer",
        "repo": repo,
        "key": "github:14022447",
        "properties": {
            "login": "lkk7",
            "display_name": "lkk7",
            "github_user_id": 14022447,
        },
    }
    function = {
        "type": "Function",
        "repo": repo,
        "key": [sha, path, qualified_name, 100],
        "properties": {
            "commit_sha": sha,
            "path": path,
            "qualified_name": qualified_name,
            "start_line": 100,
        },
    }
    assert _extended_entity_id(author) == (
        "Developer:14b5ede4facfe75a5c84e846f8806df7b7157b48e5a73fc948372544334e53b6"
    )
    wrapped_author = {**author, "key": ["github:14022447"]}
    assert _extended_entity_id(wrapped_author) == _extended_entity_id(author)
    assert _extended_entity_id(function) == (
        "Function:b0f5e030cc7a9050d0a339cf3cceadc153ecb023cd578a7ed5192fb09f0edb31"
    )
    repeated = {
        **function,
        "key": [sha, path, qualified_name, 120],
        "properties": {**function["properties"], "start_line": 120},
    }
    assert _extended_entity_id(repeated) != _extended_entity_id(function)


@pytest.mark.skipif(
    not os.environ.get("P2_REAL_P3_DATASET_DIR"),
    reason="P2_REAL_P3_DATASET_DIR enables the actual P1+P3 shard acceptance test",
)
def test_real_p3_merged_shard_loads_and_returns_four_hop_path(graph_config):
    root = Path(os.environ["P2_REAL_P3_DATASET_DIR"]).resolve()
    report = validate_extended_dataset(root)
    assert report["status"] == "ok", report["errors"]
    assert report["counts"] == {
        "sources": 370,
        "source_units": 40,
        "evidence": 741,
        "entities": 535,
        "relations": 591,
        "subjects": 65,
    }
    dataset = report["dataset_id"]
    graph_config["_owned"].append(dataset)
    loaded_result = load_dataset(root, config=graph_config)
    assert loaded_result["status"] == "ok", loaded_result

    with GraphStore(graph_config) as store:
        snapshot = store.snapshot(dataset)
    developer = next(
        entity for entity in snapshot["entities"]
        if entity["id"] == (
            "Developer:14b5ede4facfe75a5c84e846f8806df7b7157b48e5a73fc948372544334e53b6"
        )
    )
    function = next(
        entity for entity in snapshot["entities"]
        if entity["id"] == (
            "Function:b0f5e030cc7a9050d0a339cf3cceadc153ecb023cd578a7ed5192fb09f0edb31"
        )
    )
    assert developer["key"] == "github:14022447"
    assert function["key"] == [
        "05e9c6bd630ecf4ec0ec884b1fc7901663737bc7",
        "src/flask/testing.py",
        "flask.testing._get_werkzeug_version",
        100,
    ]

    prepared = prepare_query(
        {
            "dataset_id": dataset,
            "question": (
                "PR #6096（作者 lkk7、合并者 davidism）合并为 commit "
                "05e9c6bd630ecf4ec0ec884b1fc7901663737bc7，请追到 "
                "src/flask/testing.py 中的顶层函数 "
                "flask.testing._get_werkzeug_version。"
            ),
            "kind": "trace",
            "seed_ids": [developer["id"], function["id"]],
        },
        config={
            **graph_config,
            "graph_depth": 4,
            "graph_path_limit": 100,
            "graph_expand_seeds": False,
        },
    )
    expected_relations = {
        "Relation:a93b5efa39826afd9b209821b4923674ff414115ba9a9b406f9b993b01859004",
        "Relation:90007a4e1f5c7293bd980420d8745213fae4187664d822224e0480a30deb4125",
        "Relation:6e186e8d98eb9dd86a305dcf58d3079567de12c642c7d06a301d5e716e290a18",
        "Relation:da169aa17eb6819c0d417c20a7a1bcd85b9b94a2d90226ee2e11f3b9fa7b68d4",
    }
    merged_relations = {
        "Relation:c73048f6644f5b2bda50e54119330fe8e63fc40481e7574addde0e570a368d9c",
        "Relation:90007a4e1f5c7293bd980420d8745213fae4187664d822224e0480a30deb4125",
        "Relation:6e186e8d98eb9dd86a305dcf58d3079567de12c642c7d06a301d5e716e290a18",
        "Relation:da169aa17eb6819c0d417c20a7a1bcd85b9b94a2d90226ee2e11f3b9fa7b68d4",
    }
    path_relations = {frozenset(path["relation_ids"]) for path in prepared["paths"]}
    assert frozenset(expected_relations) in path_relations
    assert frozenset(merged_relations) in path_relations


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


def test_candidate_priority_prefers_scoped_discussion_over_generic_sources():
    def source(identity, kind, origin_key, text):
        return {
            "source_id": identity,
            "source_key": identity,
            "kind": kind,
            "origin_key": origin_key,
            "title": None,
            "text": text,
            "url": "https://example.invalid/" + identity,
            "author": None,
            "occurred_at": None,
        }

    package = {
        "sources": [
            source("body", "issue_body", "example/repo:body:7", "server close context"),
            source("comment", "comment", "example/repo:comment:900", "server close context"),
            source("api", "api_response", "https://api.example/issues/7", "server close context"),
            source("code", "code", "code:abc:src/app.py", "server close context"),
        ]
    }
    retrieval = {
        "scores": {"api": 0.9, "code": 0.8, "comment": 0.2, "body": 0.1}
    }
    ordered = context_candidates(
        package, retrieval, [], question="issue #7 server close", limit=4
    )
    assert [item["source_id"] for item in ordered] == ["body", "comment", "api", "code"]


def test_candidate_priority_keeps_explicit_code_snapshot_first():
    def source(identity, kind, origin_key):
        return {
            "source_id": identity,
            "source_key": identity,
            "kind": kind,
            "origin_key": origin_key,
            "title": None,
            "text": "session cookie implementation",
            "url": "https://example.invalid/" + identity,
            "author": None,
            "occurred_at": None,
        }

    package = {
        "sources": [
            source("comment", "comment", "example/repo:comment:900"),
            source(
                "code",
                "code",
                "code:514fc6b:src/example/testing.py",
            ),
        ]
    }
    question = "提交 514fc6b 的 src/example/testing.py 如何处理 session cookie？"
    ordered = context_candidates(
        package, {"scores": {"comment": 0.9, "code": 0.1}}, [], question=question
    )
    assert ordered[0]["source_id"] == "code"


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
