"""Recompute cohort counts and paired uncertainty from saved per-answer metrics."""

from __future__ import annotations

import random
import statistics

from .metrics import ratio


def summarize_qa(rows, *, split="test", expected_questions=None):
    selected = [r for r in rows if r["split"] == split]
    expected_questions = (
        expected_questions if expected_questions is not None else (20 if split == "test" else 4)
    )
    identities = [(r["question_id"], r["system"]) for r in selected]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate question/system score")
    result = {}
    for system in ("A", "B"):
        cohort = [r for r in selected if r["system"] == system]
        metrics = [r["metrics"] for r in cohort]
        cohort_complete = len(cohort) == expected_questions
        eligible = [
            m
            for r, m in zip(cohort, metrics, strict=True)
            if r.get("answerability") == "answerable"
        ]
        subset_claims_judged = bool(metrics) and all(m["claim_judgment_complete"] for m in metrics)
        subset_facts_judged = bool(eligible) and all(
            m["fact_coverage"] is not None for m in eligible
        )
        all_judged = cohort_complete and subset_claims_judged
        facts_judged = cohort_complete and subset_facts_judged
        claims = sum(m["claim_count"] for m in metrics)
        unsupported = sum(m["unsupported"] for m in metrics)
        facts_hit, facts_total = (
            sum(m["facts_hit"] for m in eligible),
            sum(m["facts_total"] for m in eligible),
        )
        correct = [m["correct_abstention"] for m in metrics if m["correct_abstention"] is not None]
        latency = [r["timings_ms"]["total"] for r in cohort if "total" in r.get("timings_ms", {})]
        result[system] = {
            "questions": len(cohort),
            "expected_questions": expected_questions,
            "question_coverage": ratio(len(cohort), expected_questions),
            "question_set_complete": cohort_complete,
            "claim_count": claims,
            "unsupported_claims": unsupported,
            "unsupported_rate": ratio(unsupported, claims) if all_judged else None,
            "claim_judgment_complete": all_judged,
            "unclear_claims": sum(m["unclear"] for m in metrics),
            "answerable_questions": len(eligible),
            "facts_hit": facts_hit,
            "facts_total": facts_total,
            "fact_coverage": ratio(facts_hit, facts_total) if facts_judged else None,
            "fact_judgment_complete": facts_judged,
            "evaluated_subset": {
                "unsupported_rate": ratio(unsupported, claims) if subset_claims_judged else None,
                "fact_coverage": ratio(facts_hit, facts_total) if subset_facts_judged else None,
                "answers_with_complete_claim_judgments": sum(
                    m["claim_judgment_complete"] for m in metrics
                ),
                "questions_with_fact_scores": sum(m["fact_coverage"] is not None for m in eligible),
            },
            "evidence_groups_hit": sum(m["evidence"]["hit"] for m in metrics),
            "evidence_groups_total": sum(m["evidence"]["total"] for m in metrics),
            "evidence_group_recall": ratio(
                sum(m["evidence"]["hit"] for m in metrics),
                sum(m["evidence"]["total"] for m in metrics),
            ),
            "correct_abstentions": sum(correct),
            "verified_insufficient_questions": len(correct),
            "correct_abstention_rate": ratio(sum(correct), len(correct)),
            "production_failures": sum(m["production_failed"] for m in metrics),
            "latency_samples": len(latency),
            "median_latency_ms": statistics.median(latency) if latency else None,
            "prompt_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in cohort),
            "completion_tokens": sum(
                r.get("usage", {}).get("completion_tokens", 0) for r in cohort
            ),
            "charged_upper_cny": sum(
                r.get("usage", {}).get("charged_upper_cny", 0) for r in cohort
            ),
            "new_charge_upper_cny": sum(
                r.get("usage", {}).get("new_charge_upper_cny", 0) for r in cohort
            ),
        }
    pairs = {}
    for row in selected:
        pairs.setdefault(row["question_id"], {})[row["system"]] = row["metrics"]["fact_coverage"]
    values = [
        p["B"] - p["A"]
        for p in pairs.values()
        if set(p) == {"A", "B"} and p["A"] is not None and p["B"] is not None
    ]
    rng = random.Random(20261030)
    bootstrap = (
        sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(10000))
        if values
        else []
    )
    result["paired_fact_coverage"] = {
        "pairs": len(values),
        "mean_difference_B_minus_A": statistics.mean(values) if values else None,
        "bootstrap95": [bootstrap[249], bootstrap[9749]] if bootstrap else None,
        "wins_B": sum(v > 0 for v in values),
        "wins_A": sum(v < 0 for v in values),
        "ties": sum(v == 0 for v in values),
        "bootstrap_seed": 20261030,
        "interpretation": "descriptive paired question bootstrap within this frozen small cohort; "
        "not independent-theme population inference",
    }
    return result
