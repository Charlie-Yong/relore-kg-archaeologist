"""No paid calls: exercise billing concurrency, failure traces and private isolation."""

import concurrent.futures
import json
from pathlib import Path

import httpx
import pytest

from historykg.llm import BudgetLedger, answer_question, prepare_request, run_request
from historykg.llm.answer import render_context
from historykg.llm.budget import BudgetBlocked


def reserve_worker(path, index):
    ledger = BudgetLedger(path, 10)
    try:
        ledger.reserve(str(index), "extract", "data", 6_000_000)
        return "reserved"
    except BudgetBlocked:
        return "blocked"


def test_budget_is_shared_across_processes_and_not_resettable(tmp_path):
    path = str(tmp_path / "budget.sqlite3")
    BudgetLedger(path, 10)
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(reserve_worker, [path] * 3, range(3)))
    assert results.count("reserved") == 1
    assert BudgetLedger(path, 10).snapshot()["remaining_cny"] == 4
    with pytest.raises(ValueError, match="已固定"):
        BudgetLedger(path, 20)


def prepared(tmp_path, **kwargs):
    return prepare_request(
        task=kwargs.pop("task", "extract"),
        dataset_id=kwargs.pop("dataset_id", "data1"),
        payload={"text": "🙂"},
        config=kwargs.pop("config", {"max_output_tokens": 30, "max_retries": 2}),
        prompt="Return JSON.",
        prompt_version="p1",
        output_schema={
            "type": "object",
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
            "additionalProperties": False,
        },
        output_root=kwargs.pop("output_root", tmp_path / "output"),
        **kwargs,
    )


def budget(tmp_path):
    return {"ledger_path": str(tmp_path / "budget.sqlite3"), "approved_cny": 10}


def response(value, *, finish="stop", tokens=12):
    return httpx.Response(
        200,
        json={
            "model": "deepseek-flash",
            "usage": {
                "prompt_tokens": tokens,
                "completion_tokens": 8,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
            "choices": [{"finish_reason": finish, "message": {"content": json.dumps(value)}}],
        },
    )


def test_truncated_http_success_is_failed_attempt_and_billed_before_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-never-serialize")
    monkeypatch.setattr("historykg.llm.gateway.now", lambda: "2026-10-30T01:30:00Z")
    seen = []

    def handler(request):
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "disabled"}
        seen.append(body)
        return response({"ok": True}, finish="length" if len(seen) == 1 else "stop")

    req = prepared(tmp_path)
    result = run_request(req, budget=budget(tmp_path), transport=httpx.MockTransport(handler))
    assert result["status"] == "ok"
    assert [a["status"] for a in result["attempts"]] == ["failed", "ok"]
    assert result["usage"]["prompt_tokens"] == 24
    assert result["usage"]["charged_upper_cny"] == (24 * 2 + 16 * 8) / 1_000_000
    cached = run_request(req, budget=budget(tmp_path), transport=httpx.MockTransport(handler))
    assert cached["cache_hit"] and cached["new_requests"] == 0 and len(seen) == 2
    assert "test-secret-never-serialize" not in "".join(
        p.read_text() for p in Path(req["output_directory"]).rglob("*.json")
    )


def test_budget_blocks_before_network_and_timeout_keeps_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    req = prepared(tmp_path, config={"max_output_tokens": 100, "max_retries": 0})
    calls = []

    def broken(request):
        calls.append(1)
        raise httpx.ReadTimeout("unknown outcome")

    result = run_request(req, budget=budget(tmp_path), transport=httpx.MockTransport(broken))
    assert result["status"] == "failed" and result["budget"]["states"]["uncertain"]["attempts"] == 1
    small = {"ledger_path": str(tmp_path / "small.sqlite3"), "approved_cny": 0.000001}
    denied = run_request(
        prepared(tmp_path / "other"), budget=small, transport=httpx.MockTransport(broken)
    )
    assert denied["status"] == "blocked" and len(calls) == 1


def test_missing_key_and_401_do_not_trigger_retry(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    req = prepared(tmp_path)
    assert run_request(req, budget=budget(tmp_path))["status"] == "blocked"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    result = run_request(
        req,
        budget=budget(tmp_path),
        transport=httpx.MockTransport(lambda _: httpx.Response(401, json={})),
    )
    assert result["status"] == "failed" and len(result["attempts"]) == 1


def test_private_roots_and_configuration_change_cache_identity(tmp_path):
    with pytest.raises(ValueError, match="private_test"):
        prepared(tmp_path, task="reference")
    with pytest.raises(ValueError, match="生产任务"):
        prepared(tmp_path, task="extract", output_root=tmp_path / "private_test")
    private = prepared(tmp_path, task="judge", output_root=tmp_path / "private_test")
    assert Path(private["output_directory"]).is_relative_to(tmp_path / "private_test")
    a = prepared(tmp_path)
    b = prepared(tmp_path, config={"thinking": "enabled", "max_output_tokens": 30})
    c = prepared(tmp_path, dataset_id="data2")
    d = prepared(tmp_path, repeat_index=1)
    assert len({r["run_id"] for r in (a, b, c, d)}) == 4


def test_interrupted_worker_consumes_retry_and_keeps_unknown_bill(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    req = prepared(tmp_path)
    settings = budget(tmp_path)
    ledger = BudgetLedger(settings["ledger_path"], settings["approved_cny"])
    upper = req["input_token_upper_bound"] * 2 + req["body"]["max_tokens"] * 8
    ledger.reserve(req["run_id"] + ":0", "extract", "data1", upper)
    calls = []

    def handler(_):
        calls.append(1)
        return response({"ok": True})

    result = run_request(req, budget=settings, transport=httpx.MockTransport(handler))
    assert result["status"] == "ok" and len(calls) == 1
    assert result["attempts"][0]["error"] == "interrupted_before_attempt_record"
    assert result["usage"]["actual_requests"] == 2 and result["new_requests"] == 1
    assert ledger.snapshot()["states"]["uncertain"]["charged_micro_cny"] == upper


def test_same_run_lock_does_not_overwrite_active_result(tmp_path, monkeypatch):
    from historykg.llm.gateway import _run_lock

    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    req = prepared(tmp_path)
    with _run_lock(Path(req["output_directory"])) as acquired:
        assert acquired
        blocked = run_request(req, budget=budget(tmp_path))
    assert blocked["error"] == "same_run_in_progress"
    assert not (Path(req["output_directory"]) / "result.json").exists()


@pytest.mark.parametrize("task", ["extract", "answer", "reference", "judge"])
def test_four_tasks_use_isolated_gateway_records(tmp_path, monkeypatch, task):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    root = tmp_path / ("private_test" if task in {"reference", "judge"} else "production")
    req = prepared(tmp_path, task=task, output_root=root)
    result = run_request(
        req,
        budget=budget(tmp_path),
        transport=httpx.MockTransport(lambda _: response({"ok": True})),
    )
    assert result["status"] == "ok"
    assert (Path(req["output_directory"]) / "attempts/0/response.json").is_file()


def test_final_context_clips_at_complete_boundary_with_real_offsets():
    item = {
        "source_id": "s",
        "start": 20,
        "end": 20 + len("One sentence. " * 20),
        "quote": "One sentence. " * 20,
    }
    rendered = render_context([item, item], max_characters=150)
    assert rendered["characters"] <= 150
    assert len(rendered["fragments"]) == 1
    visible = rendered["fragments"][0]
    assert visible["quote"].endswith(". ")
    assert visible["end"] == visible["start"] + len(visible["quote"])
    assert visible["end"] < item["end"]


def test_answer_only_returns_cited_claims_and_no_free_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    import historykg.llm.answer as module

    original = module.run_request
    outputs = [
        {"claims": [{"text": "Invented", "evidence": []}], "gaps": []},
        {
            "claims": [
                {"text": "Local change", "evidence": [{"source_id": "s", "quote": "🙂 kept."}]}
            ],
            "gaps": [],
        },
    ]

    def handler(_):
        return response(outputs.pop(0))

    monkeypatch.setattr(
        module,
        "run_request",
        lambda request, **kwargs: original(
            request, **kwargs, transport=httpx.MockTransport(handler)
        ),
    )
    text = "🙂 kept."
    result = answer_question(
        dataset_id="data1",
        repo="example/toy",
        question="What changed?",
        context=[{"source_id": "s", "start": 40, "end": 40 + len(text), "quote": text}],
        config={"output_root": tmp_path / "runs"},
        budget=budget(tmp_path),
    )
    assert result["status"] == "ok" and len(result["claims"]) == 1
    assert "summary" not in result and "answer" not in result
    assert result["evidence"][0]["start"] == 40
    assert result["usage"]["actual_requests"] == 2
