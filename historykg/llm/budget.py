"""A single, durable CNY budget shared by every process and model task.

Amounts are integer micro-yuan. Unknown/failed HTTP outcomes keep the reserved
upper bound: a timeout is not evidence that the provider did not bill a request.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from .pricing import PRICE_POLICY, PRICE_SOURCE, quote_usage


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
            if "settlement_json" not in {r[1] for r in db.execute("PRAGMA table_info(attempts)")}:
                db.execute("ALTER TABLE attempts ADD COLUMN settlement_json TEXT")
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
                """INSERT INTO attempts
                    (attempt_id,task,dataset_id,reserved,charged,state,usage_json,created_at)
                    VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (attempt_id, task, dataset_id, upper_micro, upper_micro, "reserved", None),
            )

    def settle(
        self,
        attempt_id: str,
        actual_micro: int | None,
        usage_json: str,
        *,
        settlement: dict | None = None,
    ) -> None:
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
                """UPDATE attempts SET charged=?,state=?,usage_json=?,settlement_json=?
                   WHERE attempt_id=?""",
                (
                    charge,
                    "uncertain" if actual_micro is None else "settled",
                    usage_json,
                    json.dumps(settlement, ensure_ascii=False) if settlement else None,
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
            "accounted_cny": charged / 1_000_000,
            "known_usage_cny": states.get("settled", {}).get("charged_micro_cny", 0) / 1_000_000,
            "unknown_upper_cny": sum(
                item["charged_micro_cny"] for state, item in states.items() if state != "settled"
            )
            / 1_000_000,
            "remaining_cny": max(0, cap - charged) / 1_000_000,
            "states": states,
        }

    def reconcile_usage(
        self,
        *,
        model_id: str,
        completed_by: str,
        time_evidence: str,
        backup_path: str | Path,
    ) -> dict:
        """One atomic legacy correction, backed up before any charge is changed.

        completed_by is an evidenced upper bound on *all* existing settled
        responses, not an assumed duration derived from an HTTP timeout.
        Only token metadata is read; request/result caches remain untouched.
        """
        backup = Path(backup_path).resolve()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='budget_reconciliations'"
            ).fetchone()
            if exists:
                previous = db.execute(
                    "SELECT summary_json FROM budget_reconciliations WHERE policy=?",
                    (PRICE_POLICY,),
                ).fetchone()
                if previous:
                    return json.loads(previous[0])
            if db.execute("SELECT 1 FROM attempts WHERE state='reserved'").fetchone():
                raise ValueError("存在进行中的预留请求，历史对账须等其结算。")
            if not time_evidence or not completed_by:
                raise ValueError("历史对账必须提供全部响应已完成的时间上界与依据。")
            if backup == self.path or backup.exists():
                raise ValueError("对账备份必须使用尚不存在的新路径。")
            rows = db.execute(
                """SELECT attempt_id,reserved,charged,state,usage_json,created_at,settlement_json
                   FROM attempts ORDER BY created_at,attempt_id"""
            ).fetchall()
            changes = []
            for attempt_id, reserved, old, state, usage_json, created, prior in rows:
                settlement = None
                if state == "settled" and prior is None:
                    # SQLite CURRENT_TIMESTAMP is explicitly UTC, despite lacking an offset.
                    start = dt.datetime.fromisoformat(created).replace(tzinfo=dt.UTC).isoformat()
                    end = dt.datetime.fromisoformat(completed_by)
                    if end.tzinfo is None or end < dt.datetime.fromisoformat(start):
                        raise ValueError("已完成时间上界必须是带时区、且晚于请求的时间。")
                    settlement = quote_usage(
                        model_id, json.loads(usage_json), started_at=start, finished_at=completed_by
                    )
                    if settlement is None:
                        raise ValueError("已结算历史请求缺少可核价用量，未修改账本。")
                new = settlement["charged_micro_cny"] if settlement else old
                changes.append((attempt_id, reserved, old, new, settlement))
            # BEGIN IMMEDIATE holds the only writer slot. A separate reader can
            # back up the committed, pre-correction state without backing up an
            # active transaction on this connection (which would wait on itself).
            backup.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as source, sqlite3.connect(backup) as target:
                source.backup(target)
            before = sum(row[2] for row in changes)
            after = sum(row[3] for row in changes)
            summary = {
                "policy": PRICE_POLICY,
                "source": PRICE_SOURCE,
                "created_at": dt.datetime.now(dt.UTC).isoformat(),
                "backup_path": str(backup),
                "model_id": model_id,
                "completed_by": completed_by,
                "time_evidence": time_evidence,
                "attempts": len(changes),
                "corrected_attempts": sum(row[4] is not None for row in changes),
                "old_charged_micro_cny": before,
                "new_charged_micro_cny": after,
                "released_micro_cny": before - after,
                "cap_and_ceiling_micro_cny": list(
                    db.execute("SELECT cap,ceiling FROM budget WHERE id=1").fetchone()
                ),
            }
            db.execute("""CREATE TABLE IF NOT EXISTS budget_reconciliations (
                policy TEXT PRIMARY KEY, summary_json TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS budget_reconciliation_items (
                policy TEXT NOT NULL, attempt_id TEXT NOT NULL, reserved INTEGER NOT NULL,
                old_charged INTEGER NOT NULL, new_charged INTEGER NOT NULL, settlement_json TEXT,
                PRIMARY KEY (policy,attempt_id)
            )""")
            for attempt_id, reserved, old, new, settlement in changes:
                details = json.dumps(settlement, ensure_ascii=False) if settlement else None
                db.execute(
                    "INSERT INTO budget_reconciliation_items VALUES (?,?,?,?,?,?)",
                    (PRICE_POLICY, attempt_id, reserved, old, new, details),
                )
                if settlement:
                    db.execute(
                        "UPDATE attempts SET charged=?,settlement_json=? WHERE attempt_id=?",
                        (new, details, attempt_id),
                    )
            db.execute(
                "INSERT INTO budget_reconciliations VALUES (?,?)",
                (PRICE_POLICY, json.dumps(summary, ensure_ascii=False)),
            )
        return summary

    def lower_ceiling(self, available_cny: str | float) -> None:
        """Apply a read-only account-balance ceiling; this can never raise authority."""
        ceiling = int(Decimal(str(available_cny)) * 1_000_000)
        if ceiling < 0:
            raise ValueError("余额上限不能为负。")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE budget SET ceiling=MIN(ceiling,?) WHERE id=1", (ceiling,))
