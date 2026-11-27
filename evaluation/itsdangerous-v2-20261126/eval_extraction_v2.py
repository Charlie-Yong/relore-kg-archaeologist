"""Evaluate extraction PROMPT v1 vs v2 on original 30 and disjoint held-out 20 units."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from budget_guard import (
    budget_config,
    record_external_call,
    spend_summary,
)
from historykg.evaluation import extraction, reference
from historykg.evaluation.metrics import score_extraction
from historykg.extract import run_extract_stage
from historykg.io import read_json, read_jsonl, write_json
from historykg.llm.gateway import bailian_connection, digest

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
FROZEN_DS = (
    ROOT
    / ".local/full-history-itsdangerous/datasets"
    / "dataset-0c94c5af1f7f64c628c4a7fe05b496647ad8ef760e18eee01287fd43f1ea3ef2"
)
FORMAL_ORIG = ROOT / ".local/private_test/itsdangerous-final-20261121/formal"
PRIVATE_V2 = ROOT / ".local/private_test/itsdangerous-v2-20261126"
WORK_ROOT = ROOT / ".local/itsdangerous-v2-20261126/extract_work"

DRAFT = "bailian/deepseek-v4.1-flash-1017"
REVIEW = "bailian/glm-5.3"
HELDOUT_SEED = "itsdangerous-v2-heldout20-20261126"
MAX_THREAD_CHARACTERS = 20000


def wilson_ci(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def select_disjoint_heldout20(units: list[dict], pool: dict, exclude_ids: set[str]) -> list[dict]:
    sizes = {
        u["unit_id"]: sum(len(pool[sid]["text"]) for sid in u["source_ids"])
        for u in units
    }
    groups = {u["topic_group"] for u in units if u["unit_id"] in exclude_ids}
    selected = []
    for kind in ("/issues/", "/pull/"):
        eligible = sorted(
            (
                u
                for u in units
                if u["unit_id"] not in exclude_ids
                and u["completeness"] == "complete"
                and kind in u["origin_thread"]
                and 200 <= sizes[u["unit_id"]] <= MAX_THREAD_CHARACTERS
            ),
            key=lambda u: (sizes[u["unit_id"]], u["unit_id"]),
        )
        # Stratify evenly across low/high size halves: 5 + 5 = 10 per kind -> 20 total
        for bucket in range(2):
            band = eligible[bucket * len(eligible) // 2 : (bucket + 1) * len(eligible) // 2]
            chosen = 0
            for unit in sorted(band, key=lambda u: digest([HELDOUT_SEED, u["unit_id"]])):
                if unit["topic_group"] in groups:
                    continue
                selected.append(unit)
                groups.add(unit["topic_group"])
                chosen += 1
                if chosen == 5:
                    break
            if chosen != 5:
                raise ValueError(f"Stratum {kind} bucket {bucket} had <5 disjoint units")
    return selected


def bailian_structured_call(cache_dir: Path, key: str, model: str, prompt: str, payload: dict,
                            schema: dict, validate) -> dict:
    dest = cache_dir / f"{key}.json"
    request_id = digest(["compact-json-v3", model, prompt, payload, schema])
    if dest.exists():
        old = read_json(dest)
        if old["request_id"] != request_id:
            raise ValueError(f"Cached request differs for {key}")
        return old["parsed"]
    endpoint, headers = bailian_connection()
    field = "judgments" if "predictions" in payload else "units"
    instruction = (
        f"Perform the requested evaluation on the supplied data now. Return an instance "
        f"with exactly the top-level key {field!r} and the completed array. "
        "Never return or repeat the JSON schema."
    )
    field_guide = (
        "Each judgment: prediction_id, reference_ids, support, rationale_support, explanation. "
        "Support values: supported, unsupported, unclear."
        if field == "judgments"
        else "Each unit: unit_id, decisions, external_claims, review_notes, unclear_notes. "
        "external_claims, review_notes, and unclear_notes MUST each be a JSON array of plain strings (e.g. [] or [\"note\"]), NEVER a single string or object. "
        "Each decision: subject_id, target_repo, action, status, statement, rationale, "
        "rationale_status, statement_evidence, rationale_evidence. Each quote: source_id and quote. "
        "Use empty lists [] when there is nothing to record. "
        'Example empty unit: {"unit_id":"...","decisions":[],"external_claims":[],"review_notes":[],"unclear_notes":[]}.'
    )
    messages = [
        {"role": "system", "content": prompt + "\n" + instruction + "\n" + field_guide},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False) + "\n" + instruction},
    ]
    attempts = []
    for number in range(1, 5):
        started = time.monotonic()
        diag = {}
        try:
            response = httpx.post(
                endpoint,
                headers=headers,
                trust_env=False,
                timeout=180,
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 6144,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "thinking": {"type": "disabled"},
                    "enable_thinking": False,
                    "reasoning_effort": "none",
                },
            )
            diag["http_status"] = response.status_code
            response.raise_for_status()
            body = response.json()
            usage = body.get("usage") or {}
            record_external_call(f"{key}-a{number}-{request_id[:12]}", field, model, usage)
            choice = body["choices"][0]
            content = (choice["message"]["content"] or "").strip()
            diag.update(usage=usage, finish_reason=choice["finish_reason"], chars=len(content))
            if content.startswith("```") and content.endswith("```"):
                content = content.split("\n", 1)[1][:-3]
            value = json.loads(content)
            validate(value)
        except (httpx.HTTPError, ValueError, TypeError, IndexError, KeyError) as exc:
            if isinstance(exc, ValidationError):
                reason = json.dumps(exc.errors(include_input=False, include_url=False))
            else:
                reason = str(exc) or type(exc).__name__
            attempts.append(
                {
                    "attempt": number,
                    "seconds": round(time.monotonic() - started, 2),
                    "error": type(exc).__name__,
                    "validation": reason[:1200],
                    **diag,
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": instruction
                    + " Cover every item exactly once with verbatim quotes; ensure list fields (external_claims/review_notes/unclear_notes) are JSON arrays of strings, not strings/dicts. Validator: "
                    + reason[:900],
                }
            )
            if number == 4:
                write_json(dest.with_suffix(".failed.json"), attempts)
                raise RuntimeError(f"Validation failed for {key}: {reason[:300]}") from exc
            continue
        attempts.append(
            {
                "attempt": number,
                "seconds": round(time.monotonic() - started, 2),
                "usage": diag.get("usage"),
                "model": body.get("model", model),
            }
        )
        write_json(dest, {"request_id": request_id, "attempts": attempts, "parsed": value})
        return value


def run_extraction_arm(arm_name: str, prompt_version: str, unit_ids: list[str]) -> tuple[list[dict], dict[str, dict], dict]:
    arm_dir = WORK_ROOT / arm_name
    arm_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("sources.jsonl", "source_units.jsonl", "subjects.jsonl"):
        target = arm_dir / fname
        if not target.exists():
            target.symlink_to(FROZEN_DS / fname)
    res = run_extract_stage(
        arm_dir,
        config={
            "full_history": True,
            "prompt_version": prompt_version,
            "unit_ids": unit_ids,
            "route": DRAFT,
            "model_id": "deepseek-flash",
            "thinking": "disabled",
            "max_output_tokens": 4096,
            "max_retries": 2,
            "timeout_seconds": 90,
            "output_root": str(WORK_ROOT / "llm_cache"),
        },
        budget=budget_config(),
    )
    preds = [{**d, "prediction_id": d["id"]} for d in read_jsonl(arm_dir / "p4/decisions.jsonl")]
    ev = {e["evidence_id"]: e for e in read_jsonl(arm_dir / "p4/evidence.jsonl")}
    return preds, ev, res


def judge_predictions(
    cache_dir: Path,
    prefix: str,
    selected_units: list[dict],
    sources: dict,
    catalog: list[dict],
    repo: str,
    references: list[dict],
    predictions: list[dict],
    evidence: dict[str, dict],
) -> list[dict]:
    batches = [selected_units[i : i + 3] for i in range(0, len(selected_units), 3)]

    def read_sources(unit):
        rows = [
            {
                k: sources[sid][k]
                for k in ("source_id", "kind", "text", "author", "occurred_at", "trust_tier")
            }
            for sid in unit["source_ids"]
        ]
        return {"unit_id": unit["unit_id"], "origin_thread": unit["origin_thread"], "sources": rows}

    def judge_batch(idx_batch):
        idx, batch = idx_batch
        keys = {u["unit_id"] for u in batch}
        preds = [d for d in predictions if d["unit_id"] in keys]
        refs = [r for r in references if r["unit_id"] in keys]
        if not preds:
            return []
        visible = {sid for u in batch for sid in u["source_ids"]}
        scope = [s for s in catalog if s["entity_type"] == "Project" or visible.intersection(s["source_ids"])]
        by_pred = {d["prediction_id"]: d["unit_id"] for d in preds}
        by_ref = {r["reference_id"]: r["unit_id"] for r in refs}
        data = {
            "repo": repo,
            "subjects": scope,
            "units": [read_sources(u) for u in batch],
            "references": refs,
            "predictions": preds,
            "prediction_evidence": [
                evidence[eid]
                for p in preds
                for eid in p["statement_evidence_ids"] + p["rationale_evidence_ids"]
                if eid in evidence
            ],
        }

        def validate(value):
            rows = extraction.MatchOutput.model_validate(value).judgments
            if len(rows) != len(by_pred) or {r.prediction_id for r in rows} != set(by_pred):
                raise ValueError("Judgments do not cover every prediction exactly once")
            if any(
                by_ref.get(rid) != by_pred[r.prediction_id]
                for r in rows
                for rid in r.reference_ids
            ):
                raise ValueError("A reference match refers to a different discussion")

        parsed = bailian_structured_call(
            cache_dir, f"{prefix}-judge-{idx}", REVIEW, extraction.PROMPT,
            data, extraction.MatchOutput.model_json_schema(), validate,
        )
        print(f"{prefix} judge batch {idx + 1}/{len(batches)} done", flush=True)
        return parsed["judgments"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        return [j for batch in pool.map(judge_batch, enumerate(batches)) for j in batch]


def build_references_for_heldout(
    cache_dir: Path, selected_units: list[dict], sources: dict, catalog: list[dict], repo: str
) -> tuple[list[dict], list[dict]]:
    batches = [selected_units[i : i + 2] for i in range(0, len(selected_units), 2)]

    def read_sources(unit):
        rows = [
            {
                k: sources[sid][k]
                for k in ("source_id", "kind", "text", "author", "occurred_at", "trust_tier")
            }
            for sid in unit["source_ids"]
        ]
        return {"unit_id": unit["unit_id"], "origin_thread": unit["origin_thread"], "sources": rows}

    def make_batch(idx_batch):
        idx, batch = idx_batch
        visible = {sid for u in batch for sid in u["source_ids"]}
        scope = [s for s in catalog if s["entity_type"] == "Project" or visible.intersection(s["source_ids"])]
        data = {"repo": repo, "subjects": scope, "units": [read_sources(u) for u in batch]}
        schema = reference.ReferenceOutput.model_json_schema()

        def validate(val):
            reference.validate_reference(val, data)

        draft = bailian_structured_call(cache_dir, f"held-draft-{idx}", DRAFT, reference.PROMPT, data, schema, validate)
        reviewed = bailian_structured_call(
            cache_dir, f"held-review-{idx}", REVIEW, reference.REVIEW_PROMPT,
            {**data, "draft_reference": draft}, schema, validate,
        )
        print(f"heldout reference batch {idx + 1}/{len(batches)} reviewed", flush=True)
        return {
            u["unit_id"]: [
                {
                    **d,
                    "reference_id": hashlib.sha256(f"{u['unit_id']}:{i}".encode()).hexdigest(),
                    "unit_id": u["unit_id"],
                }
                for i, d in enumerate(u["decisions"])
            ]
            for u in reviewed["units"]
        }

    with ThreadPoolExecutor(max_workers=3) as pool:
        grouped = {uid: rows for batch in pool.map(make_batch, enumerate(batches)) for uid, rows in batch.items()}
    refs = [r for rows in grouped.values() for r in rows if r["target_repo"] == repo]
    unknown = [r for rows in grouped.values() for r in rows if r["target_repo"] is None]
    return refs, unknown


def categorize_errors(
    units_by_id: dict, sources: dict, refs: list[dict], preds: list[dict],
    judgments: list[dict], metrics: dict
) -> dict:
    matched_pids = {m["prediction_id"] for m in metrics["matches"]}
    matched_rids = {m["reference_id"] for m in metrics["matches"]}
    judged = {j["prediction_id"]: j for j in judgments}
    fp_reasons = {"bot_bump": 0, "status_mismatch": 0, "plain_bug_or_nondecision": 0, "other_fp": 0}
    fn_reasons = {"missed_rejection_or_keep": 0, "missed_proposal_or_change": 0}

    ref_by_unit = {}
    for r in refs:
        ref_by_unit.setdefault(r["unit_id"], []).append(r)

    fp_items = []
    for p in preds:
        if p["prediction_id"] in matched_pids:
            continue
        unit = units_by_id.get(p["unit_id"], {})
        authors = {(sources[sid].get("author") or "").lower() for sid in unit.get("source_ids", [])}
        texts = "\n".join(sources[sid]["text"] for sid in unit.get("source_ids", [])).lower()
        expl = (judged.get(p["prediction_id"], {}).get("explanation") or "").lower()
        if any("[bot]" in a or "dependabot" in a for a in authors) or "bumps " in texts[:200]:
            cat = "bot_bump"
        elif "status" in expl or "proposed" in expl and "accepted" in expl:
            cat = "status_mismatch"
        elif not ref_by_unit.get(p["unit_id"]):
            cat = "plain_bug_or_nondecision"
        else:
            cat = "other_fp"
        fp_reasons[cat] += 1
        fp_items.append({"prediction_id": p["prediction_id"], "category": cat, "status": p["status"], "statement": p["statement"]})

    fn_items = []
    for r in refs:
        if r["reference_id"] in matched_rids:
            continue
        cat = "missed_rejection_or_keep" if (r.get("status") == "rejected" or r.get("action") == "keep") else "missed_proposal_or_change"
        fn_reasons[cat] += 1
        fn_items.append({"reference_id": r["reference_id"], "category": cat, "status": r["status"], "action": r["action"], "statement": r["statement"]})

    return {
        "fp_breakdown": fp_reasons,
        "fn_breakdown": fn_reasons,
        "rationale_breakdown": {
            "covered": metrics["rationale"]["covered"],
            "eligible": metrics["rationale"]["eligible"],
            "empty": len(metrics["rationale"]["empty_ids"]),
            "partial_or_unsupported": len(metrics["rationale"]["incomplete_or_unsupported_ids"]),
            "missed_decision": len(metrics["rationale"]["missing_decision_ids"]),
            "status_error": len(metrics["rationale"]["status_error_ids"]),
        },
        "fp_items": fp_items,
        "fn_items": fn_items,
    }


def compact_metrics(m: dict, preds: list[dict], refs: list[dict]) -> dict:
    rat = m["rationale"]
    tp, fp, fn = m["tp"], m["fp"], m["fn"]
    return {
        "references": len(refs),
        "predictions": len(preds),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(m["precision"], 4) if m["precision"] is not None else None,
        "precision_ci95": wilson_ci(tp, tp + fp),
        "recall": round(m["recall"], 4) if m["recall"] is not None else None,
        "recall_ci95": wilson_ci(tp, tp + fn),
        "f1": round(m["f1"], 4) if m["f1"] is not None else None,
        "rationale_covered": rat["covered"],
        "rationale_eligible": rat["eligible"],
        "rationale_coverage": round(rat["coverage"], 4) if rat["coverage"] is not None else None,
        "rationale_ci95": wilson_ci(rat["covered"], rat["eligible"]),
    }


def main():
    PRIVATE_V2.mkdir(parents=True, exist_ok=True)
    cache_runs = PRIVATE_V2 / "runs"
    cache_runs.mkdir(parents=True, exist_ok=True)

    manifest = read_json(FROZEN_DS / "manifest.json")
    repo = manifest["repo"]
    units = read_jsonl(FROZEN_DS / "source_units.jsonl")
    units_by_id = {u["unit_id"]: u for u in units}
    sources = {s["source_id"]: s for s in read_jsonl(FROZEN_DS / "sources.jsonl")}
    catalog = read_jsonl(FROZEN_DS / "subjects.jsonl")

    # Part A: Original 30 units (reuse exact cached formal references + v1 scoring)
    orig_proto = read_json(FORMAL_ORIG / "protocol.json")
    orig_unit_ids = orig_proto["units"]
    orig_units = [units_by_id[uid] for uid in orig_unit_ids]
    orig_scoring = read_json(FORMAL_ORIG / "scoring.json")
    orig_refs = orig_scoring["references"]
    orig_v1_preds = orig_scoring["predictions"]
    orig_v1_judg = orig_scoring["judgments"]
    orig_v1_metrics = score_extraction(orig_refs, orig_v1_preds, orig_v1_judg, reference_complete=True)

    orig_v2_preds, orig_v2_ev, orig_v2_run = run_extraction_arm("orig30_v2", "v2", orig_unit_ids)
    orig_v2_judg = judge_predictions(
        cache_runs, "orig30-v2", orig_units, sources, catalog, repo, orig_refs, orig_v2_preds, orig_v2_ev
    )
    orig_v2_metrics = score_extraction(orig_refs, orig_v2_preds, orig_v2_judg, reference_complete=True)

    # Part B: Disjoint held-out 20 units (build independent refs, then score v1 vs v2)
    held_units = select_disjoint_heldout20(units, sources, set(orig_unit_ids))
    held_unit_ids = [u["unit_id"] for u in held_units]
    held_refs, held_unknown = build_references_for_heldout(cache_runs, held_units, sources, catalog, repo)

    held_v1_preds, held_v1_ev, held_v1_run = run_extraction_arm("held20_v1", "v1", held_unit_ids)
    held_v1_judg = judge_predictions(
        cache_runs, "held20-v1", held_units, sources, catalog, repo, held_refs, held_v1_preds, held_v1_ev
    )
    held_v1_metrics = score_extraction(held_refs, held_v1_preds, held_v1_judg, reference_complete=not held_unknown)

    held_v2_preds, held_v2_ev, held_v2_run = run_extraction_arm("held20_v2", "v2", held_unit_ids)
    held_v2_judg = judge_predictions(
        cache_runs, "held20-v2", held_units, sources, catalog, repo, held_refs, held_v2_preds, held_v2_ev
    )
    held_v2_metrics = score_extraction(held_refs, held_v2_preds, held_v2_judg, reference_complete=not held_unknown)

    summary = {
        "dataset_id": manifest["dataset_id"],
        "repo": repo,
        "draft_model": DRAFT,
        "judge_model": REVIEW,
        "orig30": {
            "units": len(orig_units),
            "v1": compact_metrics(orig_v1_metrics, orig_v1_preds, orig_refs),
            "v2": compact_metrics(orig_v2_metrics, orig_v2_preds, orig_refs),
            "v1_errors": categorize_errors(units_by_id, sources, orig_refs, orig_v1_preds, orig_v1_judg, orig_v1_metrics),
            "v2_errors": categorize_errors(units_by_id, sources, orig_refs, orig_v2_preds, orig_v2_judg, orig_v2_metrics),
        },
        "heldout20": {
            "units": len(held_units),
            "seed": HELDOUT_SEED,
            "unresolved_references": len(held_unknown),
            "disjoint_from_orig30": len(set(orig_unit_ids) & set(held_unit_ids)) == 0,
            "v1": compact_metrics(held_v1_metrics, held_v1_preds, held_refs),
            "v2": compact_metrics(held_v2_metrics, held_v2_preds, held_refs),
            "v1_errors": categorize_errors(units_by_id, sources, held_refs, held_v1_preds, held_v1_judg, held_v1_metrics),
            "v2_errors": categorize_errors(units_by_id, sources, held_refs, held_v2_preds, held_v2_judg, held_v2_metrics),
        },
        "spend": spend_summary(),
    }
    write_json(OUT_DIR / "extraction-v2-summary.json", summary)
    write_json(
        OUT_DIR / "extraction-v2-audit.json",
        {
            "orig30_unit_ids": orig_unit_ids,
            "heldout20_unit_ids": held_unit_ids,
            "heldout20_references": held_refs,
            "heldout20_unresolved": held_unknown,
            "orig30_v2_predictions": orig_v2_preds,
            "orig30_v2_judgments": orig_v2_judg,
            "heldout20_v1_predictions": held_v1_preds,
            "heldout20_v1_judgments": held_v1_judg,
            "heldout20_v2_predictions": held_v2_preds,
            "heldout20_v2_judgments": held_v2_judg,
        },
    )
    print(json.dumps({
        "orig30_v1": summary["orig30"]["v1"],
        "orig30_v2": summary["orig30"]["v2"],
        "held20_v1": summary["heldout20"]["v1"],
        "held20_v2": summary["heldout20"]["v2"],
        "spend": summary["spend"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
