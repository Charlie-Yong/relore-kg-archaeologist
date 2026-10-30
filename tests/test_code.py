"""P3 static code contract regression: real local git objects, no target execution."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import httpx
import pytest

from historykg.code import collect_code
from historykg.code.ast_analysis import analyze_python
from historykg.contracts import Entity, Evidence, Relation, SourceDocument
from historykg.ids import entity_id, relation_id
from historykg.io import (
    build_subjects,
    freeze_api_source,
    merge_sources,
    read_jsonl,
    validate_dataset,
    write_json,
    write_jsonl,
)

LEGACY_ENTITY_TYPES = {
    "Project",
    "Release",
    "Issue",
    "PullRequest",
    "Commit",
    "File",
    "Decision",
}
LEGACY_RELATION_TYPES = {
    "HasRelease",
    "ClaimsToClose",
    "Closes",
    "MergedAs",
    "Touches",
    "ReachableIn",
    "MentionsPR",
    "ChangesTo",
    "Imports",
    "ABOUT",
    "EVIDENCED_BY",
}


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def with_pull_requests(snapshot, pull_requests):
    sources = []
    selected = []
    merge_sha = snapshot["selected_prs"][0]["merge_commit_sha"]
    for number, user, merged_by, merged in pull_requests:
        payload = {
            "number": number,
            "user": user,
            "merged": merged,
            "merged_at": "2026-01-01T00:00:00Z" if merged else None,
            "merged_by": merged_by,
            "merge_commit_sha": merge_sha,
        }
        source = freeze_api_source(
            dataset_id=snapshot["dataset_id"],
            repo=snapshot["repo"],
            endpoint=f"repos/{snapshot['repo']}/pulls/{number}",
            payload=payload,
            params={},
            retrieved_at="2026-01-01T00:00:00Z",
        )
        sources.append(source)
        selected.append(
            {
                "number": number,
                "merged": merged,
                "merged_at": payload["merged_at"],
                "merge_commit_sha": merge_sha,
                "source_id": source["source_id"],
            }
        )
    return {
        **snapshot,
        "selected_prs": selected,
        "sources": sources,
        "releases": [],
    }


@pytest.fixture
def toy_git(tmp_path):
    root = tmp_path / "objects"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Synthetic Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    files = {
        "src/toy/__init__.py": (
            '"""Toy package entry."""\nfrom .core import handle\n'
            "from . import helper\nimport math\nfrom .missing import nope\n"
        ),
        "src/toy/core.py": (
            '"""Handle toy data."""\nfrom .helper import value\ndef handle():\n    return value\n'
        ),
        "src/toy/helper.py": (
            "value = 1\n"
            "async def handle():\n"
            "    return value\n"
            "async def 处理():\n"
            '    return "🌱"\n'
            "def repeated():\n"
            "    return 1\n"
            "def repeated():\n"
            "    return 2\n"
            "class NotAFunction:\n"
            "    def nested(self):\n"
            "        return value\n"
        ),
        "src/toy/gone.py": "gone = True\n",
        "src/toy/rename_me.py": (
            '"""A preserved module, renamed in the next commit."""\nvalue = 123\n'
        ),
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial synthetic snapshot")
    before = git(root, "rev-parse", "HEAD")
    (root / "src/toy/core.py").write_text(
        files["src/toy/core.py"].replace("return value", "return value + 1"), encoding="utf-8"
    )
    (root / "src/toy/gone.py").unlink()
    git(root, "mv", "src/toy/rename_me.py", "src/toy/renamed.py")
    (root / "src/toy/broken.py").write_text("def invalid(:\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "change, delete, rename, and retain parse failure")
    after = git(root, "rev-parse", "HEAD")
    git(root, "tag", "v1")
    git(root, "tag", "1")
    pr_source = freeze_api_source(
        dataset_id="toy_v1",
        repo="example/toy",
        endpoint="repos/example/toy/pulls/1",
        payload={
            "number": 1,
            "user": {"login": "fixture-author", "id": 1001},
            "merged": True,
            "merged_at": "2026-01-01T00:00:00Z",
            "merged_by": {"login": "fixture-merger", "id": 1002},
            "merge_commit_sha": after,
        },
        params={},
        retrieved_at="2026-01-01T00:00:00Z",
    )
    snapshot = {
        "repo": "example/toy",
        "dataset_id": "toy_v1",
        "default_branch_sha": after,
        "selected_prs": [
            {
                "number": 1,
                "merged": True,
                "merged_at": "2026-01-01T00:00:00Z",
                "merge_commit_sha": after,
                "source_id": pr_source["source_id"],
            }
        ],
        "sources": [pr_source],
        "releases": [
            {
                "id": 1,
                "tag_name": "v1",
                "published_at": "2026-01-01T00:00:00Z",
                "body": "Includes #1.",
                "html_url": "https://example.invalid/v1",
            },
            {
                "id": 2,
                "tag_name": "1",
                "published_at": "2026-01-01T00:00:00Z",
                "body": "Also includes #1.",
                "html_url": "https://example.invalid/1",
            },
        ],
    }
    return root, snapshot, before, after


def read_result(result, name):
    return read_jsonl(result["artifacts"][name])


def test_code_git_facts_and_unicode_evidence(toy_git, tmp_path):
    root, snapshot, before, after = toy_git
    result = collect_code(snapshot, dataset_dir=tmp_path / "dataset", git_repo=root)
    assert result["status"] == "partial"  # Genuine syntax failure remains visible.
    assert result["usage"]["github_requests"] == 0
    assert result["counts"]["file_snapshots"] <= 24
    assert result["counts"]["Imports"] >= 2
    assert result["counts"]["developers"] == 2
    assert result["counts"]["Authored"] == 1
    assert result["counts"]["Merged"] == 1
    assert result["counts"]["functions"] >= 4
    assert result["counts"]["Defines"] == result["counts"]["functions"]
    assert any(g["reason"] == "ast_parse_failed" for g in result["gaps"])
    sources = {s["source_id"]: s for s in read_result(result, "sources")}
    for source in sources.values():
        SourceDocument.model_validate(source)
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["text_sha256"]
    for evidence in read_result(result, "evidence"):
        Evidence.model_validate(evidence)
        assert (
            sources[evidence["source_id"]]["text"][evidence["start"] : evidence["end"]]
            == evidence["quote"]
        )
    entities = {e["id"]: e for e in read_result(result, "entities")}
    for entity in entities.values():
        if entity["type"] in LEGACY_ENTITY_TYPES:
            Entity.model_validate(entity)
        else:
            assert entity["type"] in {"Developer", "Function"}
            assert entity["contract_version"] == "1.4.2"
    relations = read_result(result, "relations")
    for relation in relations:
        if relation["type"] in LEGACY_RELATION_TYPES:
            Relation.model_validate(relation)
        else:
            assert relation["type"] in {"Authored", "Merged", "Defines"}
            assert relation["contract_version"] == "1.4.2"
    developers = {
        e["properties"]["display_name"]: e
        for e in entities.values()
        if e["type"] == "Developer"
    }
    assert set(developers) == {"fixture-author", "fixture-merger"}
    assert all("name" not in e["properties"] for e in developers.values())
    pull_request_id = entity_id("PullRequest", "example/toy", 1)
    authored = next(r for r in relations if r["type"] == "Authored")
    merged = next(r for r in relations if r["type"] == "Merged")
    assert authored["to_id"] == merged["to_id"] == pull_request_id
    assert entities[authored["from_id"]]["properties"]["display_name"] == "fixture-author"
    assert entities[merged["from_id"]]["properties"]["display_name"] == "fixture-merger"
    for relation in (authored, merged):
        evidence = next(
            e
            for e in read_result(result, "evidence")
            if e["evidence_id"] == relation["evidence_ids"][0]
        )
        assert sources[evidence["source_id"]]["kind"] == "api_response"
        assert '"login":' in evidence["quote"]
    functions = [e for e in entities.values() if e["type"] == "Function"]
    handles = [e for e in functions if e["properties"]["name"] == "handle"]
    assert {e["properties"]["path"] for e in handles} >= {
        "src/toy/core.py",
        "src/toy/helper.py",
    }
    async_handle = next(
        e
        for e in handles
        if e["properties"]["path"] == "src/toy/helper.py"
        and e["properties"]["commit_sha"] == after
    )
    assert async_handle["properties"]["kind"] == "async_function"
    unicode_function = next(
        e
        for e in functions
        if e["properties"]["qualified_name"] == "toy.helper.处理"
    )
    assert unicode_function["properties"]["kind"] == "async_function"
    assert unicode_function["properties"]["start_line"] == 4
    assert all(e["properties"]["name"] != "NotAFunction" for e in functions)
    assert all(e["properties"]["name"] != "nested" for e in functions)
    assert len({e["id"] for e in handles}) == len(handles)
    repeated = [
        e
        for e in functions
        if e["properties"]["path"] == "src/toy/helper.py"
        and e["properties"]["name"] == "repeated"
        and e["properties"]["commit_sha"] == after
    ]
    assert len(repeated) == 2
    assert len({e["id"] for e in repeated}) == 2
    defines = [r for r in relations if r["type"] == "Defines"]
    assert len(defines) == len(functions)
    for relation in defines:
        assert entities[relation["from_id"]]["type"] == "File"
        assert entities[relation["to_id"]]["type"] == "Function"
    release_ids = [e["id"] for e in entities.values() if e["type"] == "Release"]
    assert len(set(release_ids)) == 2
    assert sum(r["type"] == "ReachableIn" for r in relations) == 2
    assert sum(r["type"] == "MentionsPR" for r in relations) == 2
    gone = next(
        r
        for r in relations
        if r["type"] == "Touches" and r["properties"]["change_type"] == "deleted"
    )
    assert entities[gone["to_id"]]["properties"]["commit_sha"] == before
    rename = next(
        r
        for r in relations
        if r["type"] == "ChangesTo" and r["properties"]["change_type"].startswith("R")
    )
    assert entities[rename["from_id"]]["properties"]["path"] == "src/toy/rename_me.py"
    assert entities[rename["to_id"]]["properties"]["path"] == "src/toy/renamed.py"
    assert entity_id("File", "example/toy", before, "src/toy/core.py") != entity_id(
        "File", "example/toy", after, "src/toy/core.py"
    )
    for relation in relations:
        if relation["type"] == "Imports":
            assert (
                entities[relation["from_id"]]["properties"]["commit_sha"]
                == entities[relation["to_id"]]["properties"]["commit_sha"]
            )
    # Exercise the actual P1 consumer, including cross-shard endpoints and subjects.
    dataset = tmp_path / "dataset"
    write_jsonl(
        dataset / "p1/entities.jsonl",
        [
            {
                "contract_version": "1.4.1",
                "dataset_id": "toy_v1",
                "repo": "example/toy",
                "id": entity_id(kind, "example/toy", *keys),
                "type": kind,
                "key": keys[0] if keys else "example/toy",
                "properties": props,
                "evidence_ids": [],
            }
            for kind, keys, props in [("Project", [], {}), ("PullRequest", [1], {"number": 1})]
        ],
    )
    write_jsonl(
        dataset / "p3/entities.jsonl",
        [e for e in entities.values() if e["type"] in LEGACY_ENTITY_TYPES],
    )
    write_jsonl(
        dataset / "p3/relations.jsonl",
        [r for r in relations if r["type"] in LEGACY_RELATION_TYPES],
    )
    merge_sources(dataset)
    subjects = build_subjects(dataset)
    assert any("handle" in s["aliases"] for s in subjects)
    write_json(dataset / "manifest.json", {"dataset_id": "toy_v1", "repo": "example/toy"})
    checked = validate_dataset(dataset)
    assert checked["status"] == "ok", checked["errors"]


def test_developers_cover_multiple_authors_missing_author_and_login_fallback(toy_git, tmp_path):
    root, snapshot, _, _ = toy_git
    snapshot = with_pull_requests(
        snapshot,
        [
            (2, {"login": "Alice", "id": 11}, {"login": "Maintainer", "id": 99}, True),
            (3, {"login": "bob"}, None, False),
            (4, None, None, False),
        ],
    )
    result = collect_code(snapshot, dataset_dir=tmp_path / "dataset", git_repo=root)
    entities = {e["id"]: e for e in read_result(result, "entities")}
    relations = read_result(result, "relations")
    developers = [e for e in entities.values() if e["type"] == "Developer"]
    assert {e["properties"]["display_name"] for e in developers} == {
        "Alice",
        "Maintainer",
        "bob",
    }
    bob = next(e for e in developers if e["properties"]["login"] == "bob")
    assert bob["id"] == entity_id("Developer", "example/toy", "login:bob")
    assert bob["properties"]["github_user_id"] is None
    authored = [r for r in relations if r["type"] == "Authored"]
    merged = [r for r in relations if r["type"] == "Merged"]
    assert {r["properties"]["pr_number"] for r in authored} == {2, 3}
    assert {r["properties"]["pr_number"] for r in merged} == {2}
    assert all(r["to_id"].startswith("PullRequest:") for r in authored + merged)
    assert all(not r["to_id"].startswith("Commit:") for r in authored + merged)
    assert any(g["reason"] == "pr_author_missing" and g["pr"] == 4 for g in result["gaps"])
    sources = {s["source_id"]: s for s in read_result(result, "sources")}
    evidence = {e["evidence_id"]: e for e in read_result(result, "evidence")}
    for relation in authored + merged:
        item = evidence[relation["evidence_ids"][0]]
        assert sources[item["source_id"]]["kind"] == "api_response"
        assert '"login":' in item["quote"]


def test_developer_function_and_relation_ids_are_stable(toy_git, tmp_path):
    root, snapshot, _, _ = toy_git
    first = collect_code(snapshot, dataset_dir=tmp_path / "first", git_repo=root)
    second = collect_code(snapshot, dataset_dir=tmp_path / "second", git_repo=root)
    for kind in ("Developer", "Function"):
        assert {
            e["id"] for e in read_result(first, "entities") if e["type"] == kind
        } == {e["id"] for e in read_result(second, "entities") if e["type"] == kind}
    for kind in ("Authored", "Merged", "Defines"):
        first_ids = {r["id"] for r in read_result(first, "relations") if r["type"] == kind}
        second_ids = {r["id"] for r in read_result(second, "relations") if r["type"] == kind}
        assert first_ids == second_ids
    first_defines = next(r for r in read_result(first, "relations") if r["type"] == "Defines")
    assert first_defines["id"] == relation_id(
        "example/toy",
        "Defines",
        first_defines["from_id"],
        first_defines["to_id"],
    )


def test_static_import_offsets_and_target_missing():
    text = (
        '标记 = "🌱"; from .helper import value\n'
        "import outside\n"
        "import toy.helper\n"
        "async def 处理(\n"
        "    value: int,\n"
        ") -> int:\n"
        "    return value\n"
        "class Wrapper:\n"
        "    def nested(self):\n"
        "        return value\n"
    )
    result = analyze_python(text, "src/toy/core.py", ["src/toy/core.py", "src/toy/helper.py"])
    assert result["imports"][0]["target_path"] == "src/toy/helper.py"
    assert result["imports"][1]["target_path"] is None
    assert result["imports"][2]["target_path"] == "src/toy/helper.py"
    for imported in result["imports"]:
        assert text[imported["start"] : imported["end"]] == imported["quote"]
    assert len(result["functions"]) == 1
    function = result["functions"][0]
    assert function["qualified_name"] == "toy.core.处理"
    assert function["kind"] == "async_function"
    assert function["start_line"] == 4
    assert function["end_line"] == 7
    assert text[function["start"] : function["end"]] == function["quote"]
    assert function["quote"].startswith("async def 处理(")


def test_missing_file_is_not_deletion(toy_git, tmp_path):
    from historykg.code.collect import CodeStage

    root, snapshot, _, after = toy_git
    stage = CodeStage(snapshot, tmp_path / "dataset", {}, {}, None, root)
    assert stage.read_file(after, "src/toy/absent.py", "fixture_missing") is None
    assert stage.gaps[-1]["reason"] == "file_not_in_tree"
    assert not stage.relations


def test_source_read_failure_is_distinct_from_absence(toy_git, tmp_path, monkeypatch):
    from historykg.code.collect import CodeStage
    from historykg.code.git_reader import GitReadError

    root, snapshot, _, after = toy_git
    stage = CodeStage(snapshot, tmp_path / "dataset", {}, {}, None, root)

    def unreadable(*_):
        raise GitReadError("fixture_object_read_failure")

    monkeypatch.setattr(stage.git, "file", unreadable)
    assert stage.read_file(after, "src/toy/core.py", "fixture_failure") is None
    assert stage.gaps[-1]["reason"] == "file_read_failed"
    assert not stage.relations


def test_budget_shared_and_cache_replay(toy_git, tmp_path):
    root, snapshot, _, _ = toy_git
    snapshot = {**snapshot, "releases": []}
    calls = []

    def reply(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[])

    budget = {"github_requests": 299, "max_requests": 300}
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        result = collect_code(
            snapshot, dataset_dir=tmp_path / "dataset", budget=budget, client=client, git_repo=root
        )
        assert budget["github_requests"] == 300
        again = collect_code(
            snapshot, dataset_dir=tmp_path / "dataset", budget=budget, client=client, git_repo=root
        )
    assert len(calls) == 1
    assert again["replayed"] is True
    assert again["hashes"] == result["hashes"]
    assert again["usage"]["github_requests"] == 0


def test_budget_exhaustion_reports_gaps(toy_git, tmp_path):
    root, snapshot, _, _ = toy_git
    snapshot.pop("releases")
    result = collect_code(
        snapshot,
        dataset_dir=tmp_path / "dataset",
        budget={"github_requests": 300, "max_requests": 300},
        git_repo=root,
    )
    assert result["status"] == "partial"
    assert result["error"]["code"] == "blocked"
    assert any(g["reason"] == "request_budget_or_rate_limit" for g in result["gaps"])


def test_input_changes_do_not_overwrite_frozen_output(toy_git, tmp_path):
    root, snapshot, _, _ = toy_git
    collect_code(snapshot, dataset_dir=tmp_path / "dataset", git_repo=root)
    with pytest.raises(ValueError, match="frozen code-stage input changed"):
        collect_code(
            {**snapshot, "default_branch_sha": "a" * 40},
            dataset_dir=tmp_path / "dataset",
            git_repo=root,
        )
