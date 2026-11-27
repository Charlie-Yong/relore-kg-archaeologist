import json
from pathlib import Path

from tools.build_evolution_timeline import build_timeline


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_build_timeline_verifies_spans_and_links(tmp_path):
    dataset = tmp_path / "dataset"
    (dataset / "p1").mkdir(parents=True)
    (dataset / "p3").mkdir()
    source = {
        "dataset_id": "dataset:test",
        "source_id": "SourceDocument:test",
        "repo": "pallets/flask",
        "text": "issue pr merge file function",
    }
    evidence = {
        "dataset_id": "dataset:test",
        "evidence_id": "Evidence:test",
        "source_id": source["source_id"],
        "start": 0,
        "end": 6,
        "quote": "issue ",
    }
    issue = {
        "dataset_id": "dataset:test",
        "id": "Issue:5916",
        "type": "Issue",
        "key": 5916,
        "properties": {
            "title": "route option bug",
            "created_at": "2026-02-12T20:32:21Z",
            "closed_at": "2026-02-12T21:07:52Z",
        },
        "evidence_ids": [evidence["evidence_id"]],
    }
    pull_request = {
        "dataset_id": "dataset:test",
        "id": "PullRequest:5917",
        "type": "PullRequest",
        "key": 5917,
        "properties": {
            "title": "fix route option",
            "created_at": "2026-02-12T21:06:34Z",
            "merged_at": "2026-02-12T21:07:51Z",
        },
        "evidence_ids": [evidence["evidence_id"]],
    }
    commit = {
        "dataset_id": "dataset:test",
        "id": "Commit:test",
        "type": "Commit",
        "key": "a" * 40,
        "properties": {
            "sha": "a" * 40,
            "message": "fix route option\n",
            "committed_at": "2026-02-12T13:07:50-08:00",
        },
        "evidence_ids": [evidence["evidence_id"]],
    }
    merged_as = {
        "dataset_id": "dataset:test",
        "id": "Relation:merged",
        "type": "MergedAs",
        "from_id": pull_request["id"],
        "to_id": commit["id"],
        "evidence_ids": [evidence["evidence_id"]],
    }
    (dataset / "manifest.json").write_text(
        json.dumps({"dataset_id": "dataset:test", "repo": "pallets/flask"}),
        encoding="utf-8",
    )
    _write_jsonl(dataset / "p1/sources.jsonl", [source])
    _write_jsonl(dataset / "p1/evidence.jsonl", [evidence])
    _write_jsonl(dataset / "p1/entities.jsonl", [issue, pull_request])
    _write_jsonl(dataset / "p1/relations.jsonl", [merged_as])
    _write_jsonl(dataset / "p3/entities.jsonl", [commit])

    result = build_timeline(dataset)

    assert result["event_count"] == 5
    assert result["case_count"] == 1
    assert result["cases"][0]["commit_id"] == commit["id"]
    assert result["checks"]["evidence_spans_exact"] == 1
    assert result["checks"]["missing_evidence"] == 0
