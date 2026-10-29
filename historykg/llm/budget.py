"""A single, durable CNY budget shared by every process and model task.

Amounts are integer micro-yuan. Unknown/failed HTTP outcomes keep the reserved
upper bound: a timeout is not evidence that the provider did not bill a request.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path


class BudgetBlocked(RuntimeError):
    pass


class BudgetLedger:
    def __init__(self, path: str | Path, approved_cny: str | float):
        self.path = Path(path).resolve()
        limit = Decimal(str(approved_cny)) * 1_000_000
        if limit <= 0 or limit != limit.to_integral_value():
            raise ValueError("预算必须为正数，最多六位小数。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY, cap INTEGER)")
            if "ceiling" not in {r[1] for r in db.execute("PRAGMA table_info(budget)")}:
                db.execute("ALTER TABLE budget ADD COLUMN ceiling INTEGER")
                db.execute("UPDATE budget SET ceiling=cap")
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY, task TEXT, dataset_id TEXT,
                reserved INTEGER NOT NULL, charged INTEGER NOT NULL,
                state TEXT NOT NULL, usage_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            row = db.execute("SELECT cap FROM budget WHERE id=1").fetchone()
            if row and row[0] != int(limit):
                raise ValueError("共享账本预算已固定，禁止通过新配置重置或增加额度。")
            db.execute("INSERT OR IGNORE INTO budget VALUES (1, ?, ?)", (int(limit), int(limit)))

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def reserve(self, attempt_id: str, task: str, dataset_id: str, upper_micro: int) -> None:
        if upper_micro <= 0:
            raise ValueError("请求预留费用必须大于零。")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise BudgetBlocked("本次尝试已有账目；请读取缓存或核对未完成请求，禁止重复发送。")
            cap = db.execute("SELECT MIN(cap,ceiling) FROM budget WHERE id=1").fetchone()[0]
            used = db.execute("SELECT COALESCE(SUM(charged),0) FROM attempts").fetchone()[0]
            if used + upper_micro > cap:
                raise BudgetBlocked("共享DeepSeek费用上限不足以保留本次请求，已停止发送。")
            db.execute(
                "INSERT INTO attempts VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                (attempt_id, task, dataset_id, upper_micro, upper_micro, "reserved", None),
            )

    def settle(self, attempt_id: str, actual_micro: int | None, usage_json: str) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT reserved,state FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row is None or row[1] != "reserved":
                raise ValueError("请求账目不存在或已结算。")
            # The bound includes all UTF-8 bytes plus conservative chat framing.
            # An unexpected provider usage is charged fully and stops further requests.
            charge = row[0] if actual_micro is None else actual_micro
            db.execute(
                "UPDATE attempts SET charged=?,state=?,usage_json=? WHERE attempt_id=?",
                (
                    charge,
                    "uncertain" if actual_micro is None else "settled",
                    usage_json,
                    attempt_id,
                ),
            )

    def attempt(self, attempt_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT reserved,charged,state,usage_json FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        return (
            dict(zip(("reserved", "charged", "state", "usage_json"), row, strict=True))
            if row
            else None
        )

    def snapshot(self) -> dict:
        with self._connect() as db:
            approved, cap = db.execute(
                "SELECT cap,MIN(cap,ceiling) FROM budget WHERE id=1"
            ).fetchone()
            rows = db.execute("SELECT state,COUNT(*),SUM(charged) FROM attempts GROUP BY state")
            states = {
                state: {"attempts": count, "charged_micro_cny": cost} for state, count, cost in rows
            }
            charged = sum(x["charged_micro_cny"] for x in states.values())
        return {
            "ledger_path": str(self.path),
            "approved_cny": approved / 1_000_000,
            "effective_cap_cny": cap / 1_000_000,
            "charged_upper_cny": charged / 1_000_000,
            "remaining_cny": max(0, cap - charged) / 1_000_000,
            "states": states,
        }

    def lower_ceiling(self, available_cny: str | float) -> None:
        """Apply a read-only account-balance ceiling; this can never raise authority."""
        ceiling = int(Decimal(str(available_cny)) * 1_000_000)
        if ceiling < 0:
            raise ValueError("余额上限不能为负。")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE budget SET ceiling=MIN(ceiling,?) WHERE id=1", (ceiling,))
