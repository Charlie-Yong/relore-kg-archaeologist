"""Non-sensitive application versions and production-only model usage exports."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from historykg.ids import canonical_json, text_hash
from historykg.io import read_json


def application_version(root: Path) -> dict:
    def git(*args):
        try:
            return subprocess.check_output(
                ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL, text=True
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    files = sorted(root.glob("historykg/**/*.py")) + sorted(root.glob("app/**/*.py"))
    files += [root / name for name in ("requirements.txt", "pyproject.toml")]
    hashes = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files if p.is_file()
    }
    status = git("status", "--porcelain", "--untracked-files=all", "--",
                 "historykg", "app", "requirements.txt", "pyproject.toml")
    return {
        "application_commit": git("rev-parse", "HEAD"),
        "application_worktree_dirty": bool(status) if status is not None else None,
        "application_file_sha256": hashes,
        "application_tree_sha256": text_hash(canonical_json(hashes)),
    }


def model_run_usage(dataset_id: str, run_ids: list[str], output_root: Path) -> dict:
    """Read only explicitly supplied extract runs; never scan private references."""
    if "private_test" in output_root.parts:
        raise ValueError("生产用量不能读取private_test")
    parent = output_root / text_hash(canonical_json(dataset_id)) / "extract"
    attempts, missing, prompt, completion, upper = {}, [], 0, 0, 0.0
    for run_id in sorted(set(run_ids)):
        if len(run_id) != 64 or any(c not in "0123456789abcdef" for c in run_id):
            raise ValueError("非法生产run_id")
        path = parent / run_id / "result.json"
        if not path.exists():
            missing.append(run_id)
            continue
        run = read_json(path)
        for attempt in run.get("attempts", []):
            key = attempt["attempt_id"]
            if key in attempts:
                continue
            attempts[key] = attempt
            usage = attempt.get("usage") or {}
            prompt += usage.get("prompt_tokens", 0)
            completion += usage.get("completion_tokens", 0)
            upper += attempt.get("charged_micro_cny", 0) / 1_000_000
    return {
        "scope": "production_extract_only",
        "run_count": len(set(run_ids)), "missing_run_ids": missing,
        "cumulative_model_attempts": len(attempts),
        "prompt_tokens": prompt, "completion_tokens": completion,
        "historical_record_upper_cny": round(upper, 6),
        "cost_semantics": "historical upper bound; shared ledger reconciliation is authoritative",
    }


def merge_stage_usage(job: dict, stage: str, result: dict, *, output_root: Path) -> None:
    """Keep local stage counters separate and aggregate model attempts across resume."""
    usage = result.get("usage", {})
    history = job.setdefault("stage_usage_history", {})
    history.setdefault(stage, []).append(usage)
    if "github_requests_total" in usage:
        job["usage"]["github_requests"] = usage["github_requests_total"]
    for key, value in usage.items():
        if key not in {"github_requests", "github_requests_total", "model_requests"}:
            job["usage"][key] = value
    model_ids = job.setdefault("model_run_ids", {})
    model_ids[stage] = sorted(set(model_ids.get(stage, [])) | set(result.get("model_run_ids", [])))
    new_requests = sum(u.get("new_model_requests", 0)
                       for rows in history.values() for u in rows)
    job["usage"]["new_model_requests"] = new_requests
    if model_ids.get("extract"):
        summary = model_run_usage(job["dataset_id"], model_ids["extract"], output_root)
        job["usage"]["model_runs"] = summary
        if not summary["missing_run_ids"]:
            total = summary["cumulative_model_attempts"]
            job["usage"].update(model_requests=total,
                                 model_requests_basis="deduplicated_production_attempt_records",
                                 reused_model_attempts=max(0, total - new_requests))
            if stage == "extract":
                job["usage"].update(
                    latest_extract_new_requests=usage.get("new_model_requests", 0),
                    latest_extract_reused_attempts=max(
                        0, total - usage.get("new_model_requests", 0)
                    ),
                )
            return
    # Older adapters may not return run IDs; this is explicitly an invocation counter.
    job["usage"]["model_requests"] = new_requests
    job["usage"]["model_requests_basis"] = "stage_new_requests; full run records unavailable"
