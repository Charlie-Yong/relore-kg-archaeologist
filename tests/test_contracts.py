"""C5/C9 boundaries: invalid evidence and API declarations must not become facts."""

import pytest

from historykg.contracts import (
    CONTRACT_VERSION,
    ENTITY_TYPES,
    RELATION_ENDPOINTS,
    Entity,
    Subject,
)
from historykg.ids import entity_id
from historykg.ingest.discovery import parse_references
from historykg.ingest.fixture import create_fixture
from historykg.io import (
    _api_relation_supported,
    api_closer_matches,
    make_evidence,
    make_source,
    read_jsonl,
    validate_dataset,
    write_jsonl,
)


@pytest.fixture
def dataset(tmp_path):
    create_fixture(tmp_path)
    return tmp_path


def test_fixture_and_same_commit_distinct_tags(dataset):
    assert validate_dataset(dataset)["status"] == "ok"
    entities = read_jsonl(dataset / "p1/entities.jsonl")
    releases = [e for e in entities if e["type"] == "Release"]
    assert releases[0]["properties"]["commit_sha"] == releases[1]["properties"]["commit_sha"]
    assert releases[0]["id"] != releases[1]["id"]
    assert entity_id("Release", "EXAMPLE/TOY", "v1.0") == releases[0]["id"]


def test_additive_contract_keeps_legacy_data_and_adds_required_coverage(dataset):
    assert CONTRACT_VERSION == "1.4.2"
    assert {"Developer", "Function"} <= set(ENTITY_TYPES)
    assert "Feature" not in ENTITY_TYPES
    assert RELATION_ENDPOINTS["Authored"] == ({"Developer"}, {"PullRequest"})
    assert RELATION_ENDPOINTS["Merged"] == ({"Developer"}, {"PullRequest"})
    assert RELATION_ENDPOINTS["Defines"] == ({"File"}, {"Function"})
    assert validate_dataset(dataset)["status"] == "ok"

    developer = {
        "contract_version": "1.4.2",
        "dataset_id": "toy_v1",
        "id": entity_id("Developer", "example/toy", "github:42"),
        "repo": "example/toy",
        "type": "Developer",
        "key": "github:42",
        "properties": {
            "login": "alice",
            "display_name": "alice",
            "github_user_id": 42,
        },
        "evidence_ids": [],
    }
    function = {
        "contract_version": "1.4.2",
        "dataset_id": "toy_v1",
        "id": entity_id(
            "Function",
            "example/toy",
            "a" * 40,
            "toy/cache.py",
            "toy.cache.cache",
            12,
        ),
        "repo": "example/toy",
        "type": "Function",
        "key": ["a" * 40, "toy/cache.py", "toy.cache.cache", 12],
        "properties": {
            "commit_sha": "a" * 40,
            "path": "toy/cache.py",
            "qualified_name": "toy.cache.cache",
            "start_line": 12,
        },
        "evidence_ids": [],
    }
    assert Entity.model_validate(developer).type == "Developer"
    assert Entity.model_validate(function).type == "Function"
    assert Subject.model_validate(
        {
            "subject_id": developer["id"],
            "repo": "example/toy",
            "entity_type": "Developer",
            "display_name": "alice",
            "aliases": [],
            "source_ids": [],
        }
    ).entity_type == "Developer"
    assert function["id"] != entity_id(
        "Function",
        "example/toy",
        "a" * 40,
        "toy/cache.py",
        "toy.cache.cache",
        13,
    )


def test_unicode_lf_and_repeated_quote():
    source = make_source(
        dataset_id="toy_v1",
        repo="example/toy",
        kind="comment",
        url="https://example.invalid",
        text="🙂引用\r\n再次引用",
        origin_key="one",
        retrieved_at="2026-10-30T00:00:00Z",
    )
    with pytest.raises(ValueError, match="重复"):
        make_evidence(source, "引用")
    assert make_evidence(source, "引用", before="🙂")["start"] == 1
    assert make_evidence(source, "引用", before="再次")["start"] == 6


@pytest.mark.parametrize("change", ["offset", "dataset", "endpoint", "malformed"])
def test_bad_records_are_reported_without_crash(dataset, change):
    path = dataset / "p1/evidence.jsonl"
    records = read_jsonl(path)
    if change == "offset":
        records[0]["start"] += 1
    elif change == "dataset":
        records[0]["dataset_id"] = "other"
    elif change == "endpoint":
        path = dataset / "p1/relations.jsonl"
        records = read_jsonl(path)
        records[0]["to_id"] = "missing"
    else:
        path = dataset / "p1/entities.jsonl"
        records = [{"id": "bad", "dataset_id": "toy_v1"}]
    write_jsonl(path, records)
    result = validate_dataset(dataset, check_manifest=False)
    assert result["status"] == "error"
    assert result["errors"]


def test_claim_and_current_closed_are_not_a_close_event(dataset):
    sources = read_jsonl(dataset / "sources.jsonl")
    closed = next(s for s in sources if "/timeline" in s["url"])
    sources.remove(closed)
    write_jsonl(dataset / "sources.jsonl", sources)
    result = validate_dataset(dataset, check_manifest=False)
    assert result["status"] == "error"
    assert any("API上下文" in error or "缺来源" in error for error in result["errors"])


def test_api_fact_binds_actual_pr_and_merge_sha(dataset):
    entities = read_jsonl(dataset / "p1/entities.jsonl")
    commit = next(e for e in entities if e["type"] == "Commit")
    commit["properties"]["sha"] = "c" * 40
    commit["key"] = "c" * 40
    write_jsonl(dataset / "p1/entities.jsonl", entities)
    assert any("API上下文" in e for e in validate_dataset(dataset, check_manifest=False)["errors"])


def test_reference_scope_and_declarations():
    refs = parse_references(
        "Fixes #12; closes https://github.com/example/toy/issues/13; other/repo#12", "example/toy"
    )
    assert [r["number"] for r in refs] == [12, 13, 12]
    assert refs[0]["semantics"] == refs[1]["semantics"] == "claims_to_close"
    assert refs[2]["resolution"] == "out_of_scope"


def test_recreate_fixture_same_logical_records(dataset, tmp_path):
    other = tmp_path / "recreated"
    create_fixture(other)
    for path in dataset.rglob("*.jsonl"):
        if other in path.parents:
            continue
        assert path.read_bytes() == (other / path.relative_to(dataset)).read_bytes()


def test_malformed_jsonl_controlled_error(dataset):
    (dataset / "p1/entities.jsonl").write_text('{"id":', encoding="utf-8")
    assert validate_dataset(dataset)["status"] == "error"


def test_external_same_number_cannot_close_local_issue():
    from historykg.io import freeze_api_source

    repo = "pallets/flask"
    left = {"repo": repo, "key": 7, "properties": {"number": 7}}
    right = {"repo": repo, "key": 8, "properties": {"number": 8}}
    event = {
        "event": "closed",
        "issue": {"number": 8},
        "closer": {"number": 7, "html_url": "https://github.com/another/project/pull/7"},
    }
    source = freeze_api_source(
        dataset_id="dev",
        repo=repo,
        endpoint="repos/pallets/flask/issues/8/timeline",
        payload=event,
        retrieved_at="2026-10-30T00:00:00Z",
    )
    evidence = make_evidence(source, source["text"])
    assert not _api_relation_supported(
        "Closes", left, right, [evidence], {source["source_id"]: source}
    )
    assert not api_closer_matches({"number": 7, "__typename": "PullRequest"}, repo, 7)
    assert api_closer_matches(
        {"number": 7, "html_url": "https://github.com/pallets/flask/pull/7"}, repo, 7
    )
    assert api_closer_matches(
        {
            "number": 7,
            "__typename": "PullRequest",
            "repository": {"nameWithOwner": "pallets/flask"},
        },
        repo,
        7,
    )
