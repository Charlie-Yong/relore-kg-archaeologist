"""Shared 15 CNY budget guard for Phase 2 experiments."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from historykg.llm.budget import BudgetLedger

ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / ".local/itsdangerous-v2-20261126/budget-usage.sqlite3"
HARD_CAP_CNY = 15.0
HANDOFF_WARN_CNY = 12.0


def budget_config() -> dict:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    BudgetLedger(LEDGER_PATH, HARD_CAP_CNY)
    return {"ledger_path": str(LEDGER_PATH), "approved_cny": HARD_CAP_CNY}


def record_external_call(attempt_id: str, task: str, model: str, usage: dict) -> float:
    """Record a direct Bailian API call (e.g., glm-5.3 judge/reference) in the shared ledger."""
    ledger = BudgetLedger(LEDGER_PATH, HARD_CAP_CNY)
    in_tok = int(usage.get("prompt_tokens") or 0)
    out_tok = int(usage.get("completion_tokens") or 0)
    # Conservative rate table in micro-yuan/token (bailian flash <= 2/8, glm-5.3 <= 4/16).
    in_rate, out_rate = (4, 16) if "glm" in model else (2, 8)
    actual_micro = max(1, in_tok * in_rate + out_tok * out_rate)
    snap = ledger.snapshot()
    if snap["remaining_cny"] * 1_000_000 < actual_micro:
        raise RuntimeError(
            f"Budget cap {HARD_CAP_CNY} CNY exceeded (spent={snap['accounted_cny']:.4f})"
        )
    ledger.reserve(unique_attempt_id := f"{attempt_id}-{uuid.uuid4().hex[:8]}", f"{task}:{model}", "phase2", actual_micro)
    ledger.settle(unique_attempt_id, actual_micro, json.dumps(usage or {}))
    return actual_micro / 1_000_000


def spend_summary() -> dict:
    if not LEDGER_PATH.exists():
        return {"spent_cny": 0.0, "remaining_cny": HARD_CAP_CNY, "calls": 0}
    snap = BudgetLedger(LEDGER_PATH, HARD_CAP_CNY).snapshot()
    with sqlite3.connect(LEDGER_PATH, timeout=30) as conn:
        calls = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    return {
        "spent_cny": round(float(snap["accounted_cny"]), 4),
        "remaining_cny": round(float(snap["remaining_cny"]), 4),
        "cap_cny": HARD_CAP_CNY,
        "calls": int(calls),
        "approaching_cap": float(snap["accounted_cny"]) >= HANDOFF_WARN_CNY,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
