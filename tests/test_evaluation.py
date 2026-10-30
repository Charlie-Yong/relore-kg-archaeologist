"""Acceptance cases for denominators, one-to-one matching and prompt evidence."""

import pytest

from historykg.evaluation import evidence_recall, score_extraction, score_qa
from historykg.evaluation.reference import freeze_sources, private_root


def test_duplicate_and_missing_count_once():
    refs = [
        {"reference_id": "r1", "rationale_status": "stated"},
        {"reference_id": "r2", "rationale_status": "stated"},
    ]
    preds = [{"prediction_id": "p1", "rationale": None}, {"prediction_id": "p2", "rationale": None}]
    judges = [
        {
            "prediction_id": p["prediction_id"],
            "reference_ids": ["r1"],
            "support": "supported",
            "rationale_support": "unsupported",
        }
        for p in preds
    ]
    value = score_extraction(refs, preds, judges)
    assert (value["tp"], value["fp"], value["fn"]) == (1, 1, 1)
    assert value["precision"] == value["recall"] == value["f1"] == 0.5
    assert value["rationale"]["eligible"] == 2
    assert value["rationale"]["coverage"] == 0


def test_empty_reason_only_reduces_reason_coverage():
    ref = [{"reference_id": "r", "rationale_status": "stated"}]
    pred = [{"prediction_id": "p", "rationale": None, "rationale_status": "not_stated"}]
    judgment = [
        {
            "prediction_id": "p",
            "reference_ids": ["r"],
            "support": "supported",
            "rationale_support": "unsupported",
        }
    ]
    result = score_extraction(ref, pred, judgment)
    assert result["f1"] == 1
    assert result["rationale"]["coverage"] == 0
    assert result["rationale"]["status_error_ids"] == ["r"]


def test_failure_retains_fn_and_empty_denominators_are_na():
    result = score_extraction([{"reference_id": "r", "rationale_status": "stated"}], [], [])
    assert result["fn"] == 1 and result["f1"] == result["recall"] == 0
    assert result["precision"] is None and result["rationale"]["coverage"] == 0
    assert score_extraction([], [], [])["f1"] is None


def test_missing_judgment_cannot_be_zero_error():
    result = score_extraction([], [{"prediction_id": "p"}], [])
    assert result["f1"] is None and result["precision"] is None
    assert result["unjudged_prediction_ids"] == ["p"]


def test_maximum_matching_instead_of_greedy():
    refs = [{"reference_id": r} for r in ("r1", "r2")]
    preds = [{"prediction_id": p} for p in ("p1", "p2")]
    judges = [
        {"prediction_id": "p1", "reference_ids": ["r1", "r2"], "support": "supported"},
        {"prediction_id": "p2", "reference_ids": ["r1"], "support": "supported"},
    ]
    assert score_extraction(refs, preds, judges)["tp"] == 2


def test_matching_tie_preserves_supported_reason():
    refs = [{"reference_id": "r", "rationale_status": "stated"}]
    preds = [
        {"prediction_id": "a", "rationale": None},
        {"prediction_id": "z", "rationale": "because", "rationale_status": "stated"},
    ]
    judges = [
        {
            "prediction_id": p["prediction_id"],
            "reference_ids": ["r"],
            "support": "supported",
            "rationale_support": "supported",
        }
        for p in preds
    ]
    result = score_extraction(refs, preds, judges)
    assert result["tp"] == 1 and result["fp"] == 1
    assert result["rationale"]["coverage"] == 1


def test_final_prompt_span_must_include_whole_alternative():
    groups = [{"group_id": "g", "alternatives": [{"source_id": "s", "start": 5, "end": 15}]}]
    assert evidence_recall(groups, [{"source_id": "s", "start": 0, "end": 14}])["recall"] == 0
    assert evidence_recall(groups, [{"source_id": "s", "start": 5, "end": 15}])["recall"] == 1


def test_all_claims_judged_and_abstention_needs_whole_pool():
    ref = {"facts": [{"fact_id": "f"}], "answerability": "answerable"}
    answer = {"status": "ok", "claims": [{"claim_id": "1"}, {"claim_id": "2"}]}
    judge = {
        "claims": [{"claim_id": "1", "support": "supported"}],
        "facts": [{"fact_id": "f", "covered": True}],
    }
    assert score_qa(ref, answer, judge, [])["unsupported_rate"] is None
    ref = {"facts": [], "answerability": "insufficient", "whole_pool_verified": False}
    assert score_qa(ref, {"status": "empty"}, {}, [])["correct_abstention"] is None
    ref["whole_pool_verified"] = True
    assert score_qa(ref, {"status": "error"}, {}, [])["correct_abstention"] is False
    assert score_qa(ref, {"status": "empty"}, {}, [])["correct_abstention"] is True


def test_isolation_and_immutable_freeze(tmp_path):
    with pytest.raises(ValueError, match="private_test"):
        private_root(tmp_path / "public")
    path = tmp_path / "private_test" / "toy"
    root = __import__("pathlib").Path(__file__).parents[1] / "fixtures" / "toy_v1"
    # Synthetic origin identifiers need not use GitHub numeric suffixes.
    from historykg.io import read_jsonl

    units = read_jsonl(root / "source_units.jsonl")
    if all(u["origin_thread"].split("/")[-1].isdigit() for u in units):
        freeze_sources(root, path, dev_threads=[1])
        with pytest.raises(ValueError, match="differs"):
            freeze_sources(root, path, dev_threads=[999])


def test_qa_judge_sees_reference_context_and_rejects_an_omitted_claim(tmp_path, monkeypatch):
    from historykg.evaluation import qa_run
    from historykg.io import write_json, write_jsonl

    root, dataset = tmp_path / "private_test" / "run", tmp_path / "dataset"
    write_json(root / "questions/all.json", {"questions": [{
        "question_id": "q", "question": "why", "split": "dev", "category": "reason",
    }]})
    reference = {
        "question_id": "q", "answerability": "answerable", "evidence_groups": [],
        "facts": [{"fact_id": "f", "text": "reason", "evidence": [
            {"source_id": "reference-source", "quote": "original reason"},
        ]}],
    }
    write_json(root / "qa_references/all.json", {"references": [reference]})
    write_json(root / "blind_mapping.json", [{"question_id": "q", "mapping": {"answer-0": "A"}}])
    write_jsonl(dataset / "sources.jsonl", [{
        "source_id": "reference-source", "text": "the original reason here",
        "repo": "example/toy", "url": "https://example.invalid/source",
    }])
    write_json(root / "answers/q/A.json", {"result": {
        "status": "ok", "claims": [
            {"text": "one", "evidence_ids": []}, {"text": "two", "evidence_ids": []},
        ], "evidence": [],
    }})

    def prepare(**kwargs):
        payload = kwargs["payload"]
        assert "system" not in payload["answers"][0]
        assert payload["original_context"][0]["text"] == "the original reason here"
        return {"run_id": "synthetic-judge"}

    def run(request, *, budget, validator):
        incomplete = {"answers": [{
            "answer_id": "answer-0", "claims": [
                {"claim_id": "claim-0", "support": "supported", "explanation": "ok"},
            ], "facts": [{"fact_id": "f", "covered": False, "explanation": "absent"}],
        }]}
        with pytest.raises(ValueError, match="omitted/duplicated claims"):
            validator(incomplete)
        incomplete["answers"][0]["claims"].append({
            "claim_id": "claim-1", "support": "unsupported", "explanation": "no evidence",
        })
        validator(incomplete)
        return {"status": "ok", "run_id": request["run_id"], "parsed": incomplete}

    monkeypatch.setattr(qa_run, "prepare_request", prepare)
    monkeypatch.setattr(qa_run, "run_request", run)
    result = qa_run.judge_answers({"dataset_dir": str(dataset), "dataset_id": "toy"}, root, {}, {})
    assert result == {"answers_scored": 1, "questions_reviewed": 1, "judgment_failures": 0}
