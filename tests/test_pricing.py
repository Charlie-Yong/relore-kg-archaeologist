"""Pricing regressions use synthetic metadata and never call the provider."""

import json
import sqlite3

import pytest

from historykg.llm.budget import BudgetLedger
from historykg.llm.pricing import billing_period, quote_usage


@pytest.mark.parametrize(
    ("start", "end", "period"),
    [
        ("2026-10-30T00:59:00+08:00", "2026-10-30T08:01:11+08:00", "idle"),
        ("2026-10-30T09:00:00+08:00", "2026-10-30T09:01:00+08:00", "peak"),
        ("2026-10-30T12:00:00+08:00", "2026-10-30T13:59:59+08:00", "idle"),
        ("2026-10-30T08:59:59+08:00", "2026-10-30T09:00:00+08:00", "peak"),
        ("2026-10-30T13:59:59+08:00", "2026-10-30T14:00:01+08:00", "peak"),
        ("2026-10-30T18:00:00+08:00", "2026-11-02T08:59:59+08:00", "idle"),
        ("2026-10-31T09:00:00+08:00", "2026-10-31T18:00:00+08:00", "idle"),
        ("2026-10-30T18:00:00+08:00", "2026-11-02T09:00:00+08:00", "peak"),
        ("2026-10-30T08:00:00", None, "peak"),
        ("2026-10-30T10:00:00+08:00", "2026-10-30T08:00:00+08:00", "peak"),
    ],
)
def test_whole_interval_and_unknown_time_use_higher_price(start, end, period):
    assert billing_period(start, end) == period


def test_reported_cache_split_and_decimal_round_up():
    usage = {
        "prompt_tokens": 101,
        "completion_tokens": 1,
        "prompt_cache_hit_tokens": 100,
        "prompt_cache_miss_tokens": 1,
    }
    idle = quote_usage(
        "deepseek-flash",
        usage,
        started_at="2026-10-30T00:00:00Z",
        finished_at="2026-10-30T00:01:00Z",
    )
    assert idle["charged_micro_cny"] == 7  # 100*.02 + 1*1 + 1*4
    peak = quote_usage("deepseek-flash", usage, started_at=None, finished_at=None)
    assert peak["charged_micro_cny"] == 14
    usage["prompt_cache_hit_tokens"] = 1
    usage["prompt_cache_miss_tokens"] = 100
    rounded = quote_usage(
        "deepseek-flash",
        usage,
        started_at="2026-10-30T00:00:00Z",
        finished_at="2026-10-30T00:01:00Z",
    )
    assert rounded["charged_micro_cny"] == 105  # ceil(104.02), never float rounding


@pytest.mark.parametrize(
    "cache",
    [
        {},
        {"prompt_cache_hit_tokens": 90},
        {"prompt_cache_hit_tokens": 90, "prompt_cache_miss_tokens": 11},
        {"prompt_cache_hit_tokens": True, "prompt_cache_miss_tokens": 99},
    ],
)
def test_incomplete_or_inconsistent_cache_usage_remains_all_miss(cache):
    quote = quote_usage(
        "deepseek-flash",
        {"prompt_tokens": 100, "completion_tokens": 10, **cache},
        started_at=None,
        finished_at=None,
    )
    assert quote["charged_micro_cny"] == 280
    assert quote["cache_basis"] == "all_miss_fallback"
    assert (
        quote_usage("deepseek-flash", {"prompt_tokens": 100}, started_at=None, finished_at=None)
        is None
    )


def test_legacy_reconciliation_backup_audit_idempotency_unknown_and_cap(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.db", 10)
    ledger.lower_ceiling("9.84")
    usage = {
        "prompt_tokens": 101,
        "completion_tokens": 1,
        "prompt_cache_hit_tokens": 100,
        "prompt_cache_miss_tokens": 1,
    }
    ledger.reserve("known", "extract", "data", 1000)
    ledger.settle("known", 210, json.dumps(usage))
    ledger.reserve("unknown", "extract", "data", 2000)
    ledger.settle("unknown", None, "null")
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE attempts SET created_at='2026-10-30 00:00:00'")
    backup = tmp_path / "before.db"
    summary = ledger.reconcile_usage(
        model_id="deepseek-flash",
        completed_by="2026-10-30T00:01:11Z",
        time_evidence="Synthetic response metadata.",
        backup_path=backup,
    )
    assert summary["old_charged_micro_cny"] == 2210
    assert summary["new_charged_micro_cny"] == 2007
    assert summary["cap_and_ceiling_micro_cny"] == [10_000_000, 9_840_000]
    assert ledger.attempt("known")["reserved"] == 1000
    assert ledger.attempt("unknown")["charged"] == 2000
    assert ledger.snapshot()["unknown_upper_cny"] == 0.002
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT SUM(charged) FROM attempts").fetchone()[0] == 2210
    with sqlite3.connect(ledger.path) as db:
        assert db.execute(
            "SELECT old_charged,new_charged FROM budget_reconciliation_items "
            "WHERE attempt_id='known'"
        ).fetchone() == (210, 7)
    assert (
        ledger.reconcile_usage(
            model_id="deepseek-flash",
            completed_by="ignored",
            time_evidence="ignored",
            backup_path=backup,
        )
        == summary
    )
    with pytest.raises(ValueError, match="已固定"):
        BudgetLedger(ledger.path, 11)


def test_reconciliation_rejects_active_attempt_without_changing_charge(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.db", 10)
    ledger.reserve("inflight", "answer", "data", 1000)
    with pytest.raises(ValueError, match="进行中"):
        ledger.reconcile_usage(
            model_id="deepseek-flash",
            completed_by="2026-10-30T00:01:11Z",
            time_evidence="Synthetic.",
            backup_path=tmp_path / "before.db",
        )
    assert ledger.attempt("inflight")["charged"] == 1000
    assert not (tmp_path / "before.db").exists()


def test_gateway_keeps_peak_reservation_but_settles_idle_cache_usage(tmp_path, monkeypatch):
    import httpx

    from historykg.llm import prepare_request, run_request

    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic")
    monkeypatch.setattr("historykg.llm.gateway.now", lambda: "2026-10-30T00:01:00Z")
    request = prepare_request(
        task="answer",
        dataset_id="synthetic",
        payload={"text": "example"},
        config={"max_output_tokens": 30, "max_retries": 0},
        prompt="JSON",
        prompt_version="frozen",
        output_schema={"type": "object"},
        output_root=tmp_path / "runs",
    )
    usage = {
        "prompt_tokens": 101,
        "completion_tokens": 1,
        "prompt_cache_hit_tokens": 100,
        "prompt_cache_miss_tokens": 1,
    }
    response = httpx.Response(
        200,
        json={
            "model": "deepseek-flash",
            "usage": usage,
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
        },
    )
    ledger_path = tmp_path / "budget.db"
    result = run_request(
        request,
        budget={"ledger_path": ledger_path, "approved_cny": 10},
        transport=httpx.MockTransport(lambda _: response),
    )
    record = result["attempts"][0]
    assert result["status"] == "ok"
    assert record["reserved_micro_cny"] == request["input_token_upper_bound"] * 2 + 30 * 8
    assert record["charged_micro_cny"] == 7
    assert record["settlement"]["period"] == "idle"
    with sqlite3.connect(ledger_path) as db:
        saved = json.loads(db.execute("SELECT settlement_json FROM attempts").fetchone()[0])
    assert saved == record["settlement"]
