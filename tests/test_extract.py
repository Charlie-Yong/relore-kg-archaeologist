"""Decision ownership and evidence are checked independently of model wording."""

import copy

import pytest
from pydantic import ValidationError

from historykg.extract import run_extract_stage
from historykg.extract.stage import Candidate
from historykg.ids import entity_id
from historykg.io import make_source, read_jsonl, write_jsonl


def extraction_input(root):
    source = make_source(
        dataset_id="dev",
        repo="example/toy",
        kind="pr_body",
        url="https://example.invalid/pr/2",
        origin_key="pr/2",
        text="🙂 Change local tests because upstream is unreleased.\n"
        "Upstream adds a query API.\nConsider retaining this behavior.",
        retrieved_at="2026-10-30T00:00:00Z",
    )
    sid = source["source_id"]
    subject = {
        "subject_id": entity_id("PullRequest", "example/toy", 2),
        "repo": "example/toy",
        "entity_type": "PullRequest",
        "display_name": "PR 2",
        "aliases": ["tests"],
        "source_ids": [sid],
    }
    unit = {
        "unit_id": "u",
        "dataset_id": "dev",
        "topic_group": "dev",
        "source_ids": [sid],
        "completeness": "complete",
        "missing_parts": [],
        "origin_thread": "https://example.invalid/pr/2",
    }
    for name, records in (("sources", [source]), ("source_units", [unit]), ("subjects", [subject])):
        write_jsonl(root / (name + ".jsonl"), records)
    candidate = {
        "target_repo": "example/toy",
        "subject_id": subject["subject_id"],
        "action": "change",
        "status": "accepted",
        "statement": "Change local tests.",
        "rationale": "Upstream is unreleased.",
        "rationale_status": "stated",
        "explicit_reason_present": True,
        "statement_evidence": [{"source_id": sid, "quote": "Change local tests"}],
        "rationale_evidence": [{"source_id": sid, "quote": "upstream is unreleased"}],
        "attribution_evidence": [{"source_id": sid, "quote": "Change local tests"}],
    }
    return source, candidate


def test_local_reason_external_and_unresolved_candidates_are_kept(tmp_path, monkeypatch):
    source, candidate = extraction_input(tmp_path)
    import historykg.extract.stage as stage

    external = copy.deepcopy(candidate)
    external.update(
        target_repo="example/upstream",
        statement="Add query API.",
        action="add",
        rationale=None,
        rationale_status="not_stated",
        explicit_reason_present=False,
        rationale_evidence=[],
    )
    unknown = {**candidate, "subject_id": "not-in-catalog"}
    bad = {
        **candidate,
        "statement_evidence": [{"source_id": source["source_id"], "quote": "missing text"}],
    }
    monkeypatch.setattr(
        stage,
        "run_request",
        lambda request, **_: {
            "run_id": request["run_id"],
            "status": "ok",
            "new_requests": 0,
            "parsed": {"candidates": [candidate, external, unknown, bad]},
        },
    )
    result = run_extract_stage(tmp_path, config={}, budget={})
    assert result["status"] == "partial" and result["counts"]["decisions"] == 1
    decisions = read_jsonl(tmp_path / "p4/decisions.jsonl")
    assert decisions[0]["rationale_status"] == "stated"
    assert decisions[0]["rationale_evidence_ids"]
    resolutions = [x["resolution"] for x in read_jsonl(tmp_path / "p4/candidates.jsonl")]
    assert resolutions == [
        "accepted_record",
        "external_project",
        "unresolved_subject",
        "invalid_evidence",
    ]
    for item in read_jsonl(tmp_path / "p4/evidence.jsonl"):
        assert source["text"][item["start"] : item["end"]] == item["quote"]
    first = (tmp_path / "p4/decisions.jsonl").read_bytes()
    run_extract_stage(tmp_path, config={}, budget={})
    assert (tmp_path / "p4/decisions.jsonl").read_bytes() == first


def test_explicit_reason_cannot_be_null_and_no_reason_is_preserved(tmp_path):
    _, candidate = extraction_input(tmp_path)
    candidate.update(rationale=None, rationale_status="not_stated", rationale_evidence=[])
    with pytest.raises(ValidationError, match="明示理由"):
        Candidate.model_validate(candidate)
    candidate["explicit_reason_present"] = False
    assert Candidate.model_validate(candidate).rationale is None


def test_blocked_extraction_is_not_actual_llm_success(tmp_path, monkeypatch):
    extraction_input(tmp_path)
    import historykg.extract.stage as stage

    monkeypatch.setattr(
        stage,
        "run_request",
        lambda request, **_: {"run_id": request["run_id"], "status": "blocked", "error": "budget"},
    )
    result = run_extract_stage(tmp_path, config={}, budget={})
    assert result["status"] == "blocked"
    assert not result["usage"]["actual_llm_extraction"]
    assert read_jsonl(tmp_path / "p4/failures.jsonl")[0]["reason"] == "budget"
