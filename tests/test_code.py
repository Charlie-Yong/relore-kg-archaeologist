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
from historykg.ids import entity_id
from historykg.io import (
    build_subjects,
    merge_sources,
    read_jsonl,
    validate_dataset,
    write_json,
    write_jsonl,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


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
        "src/toy/helper.py": "value = 1\n",
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
    snapshot = {
        "repo": "example/toy",
        "dataset_id": "toy_v1",
        "default_branch_sha": after,
        "selected_prs": [{"number": 1, "merged": True, "merge_commit_sha": after}],
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
        Entity.model_validate(entity)
    relations = read_result(result, "relations")
    for relation in relations:
        Relation.model_validate(relation)
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
    merge_sources(dataset)
    subjects = build_subjects(dataset)
    assert any("handle" in s["aliases"] for s in subjects)
    write_json(dataset / "manifest.json", {"dataset_id": "toy_v1", "repo": "example/toy"})
    checked = validate_dataset(dataset)
    assert checked["status"] == "ok", checked["errors"]


def test_static_import_offsets_and_target_missing():
    text = '标记 = "🌱"; from .helper import value\nimport outside\nimport toy.helper\n'
    result = analyze_python(text, "src/toy/core.py", ["src/toy/core.py", "src/toy/helper.py"])
    assert result["imports"][0]["target_path"] == "src/toy/helper.py"
    assert result["imports"][1]["target_path"] is None
    assert result["imports"][2]["target_path"] == "src/toy/helper.py"
    for imported in result["imports"]:
        assert text[imported["start"] : imported["end"]] == imported["quote"]


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
