"""Compute metrics from saved atomic judgments, never from model summary numbers."""

from __future__ import annotations


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _indexed(rows, key):
    result = {}
    for row in rows:
        identity = row[key]
        if identity in result:
            raise ValueError(f"duplicate {key}: {identity}")
        result[identity] = row
    return result


def _match(edges, refs, preds, judged):
    """Maximum cardinality, then maximum supported-reason coverage, deterministic ties."""
    source, sink = ("source", ""), ("sink", "")
    graph = {}

    def edge(a, b, cost):
        forward, reverse = [b, 1, cost, None], [a, 0, -cost, None]
        forward[3], reverse[3] = reverse, forward
        graph.setdefault(a, []).append(forward)
        graph.setdefault(b, []).append(reverse)
        return forward

    for pid in sorted(preds):
        edge(source, ("p", pid), 0)
    for rid in sorted(refs):
        edge(("r", rid), sink, 0)
    links = []
    for pid in sorted(edges):
        for rid in edges[pid]:
            reason = bool(
                refs[rid].get("rationale_status") == "stated"
                and preds[pid].get("rationale")
                and preds[pid].get("rationale_status") == "stated"
                and judged[pid].get("rationale_support") == "supported"
            )
            link = edge(("p", pid), ("r", rid), -(len(refs) + 1) - reason)
            links.append((pid, rid, link))
    while True:
        distance, previous = {source: 0}, {}
        # Bellman-Ford handles residual negative edges without extra dependencies.
        for _ in range(len(graph)):
            changed = False
            for a in graph:
                for item in graph[a]:
                    b, capacity, cost, _ = item
                    if (
                        capacity
                        and a in distance
                        and distance[a] + cost < distance.get(b, float("inf"))
                    ):
                        distance[b], previous[b] = distance[a] + cost, (a, item)
                        changed = True
            if not changed:
                break
        if sink not in previous:
            break
        node = sink
        while node != source:
            a, item = previous[node]
            item[1] -= 1
            item[3][1] += 1
            node = a
    return {rid: pid for pid, rid, item in links if item[1] == 0}


def score_extraction(references, predictions, judgments, *, reference_complete=True):
    """Judgments have prediction_id, reference_ids, support, rationale_support.

    Only supported semantic matches become edges. Maximum bipartite matching
    prevents duplicates from consuming two references or a greedy undercount.
    Missing prediction judgments make overall metrics unavailable. Production
    failure is represented by an empty prediction list, retaining every FN.
    """
    refs = _indexed(references, "reference_id")
    preds = _indexed(predictions, "prediction_id")
    judged = _indexed(judgments, "prediction_id")
    if judged.keys() - preds.keys():
        raise ValueError("judgment names an absent prediction")
    edges = {}
    for pid, judgment in judged.items():
        candidates = judgment.get("reference_ids", [])
        if set(candidates) - refs.keys():
            raise ValueError("match names an absent reference")
        edges[pid] = sorted(set(candidates)) if judgment["support"] == "supported" else []
    owner = _match(edges, refs, preds, judged)
    tp = len(owner)
    fp, fn = len(preds) - tp, len(refs) - tp
    complete = reference_complete and judged.keys() == preds.keys()
    stated = {rid for rid, ref in refs.items() if ref.get("rationale_status") == "stated"}
    covered, empty, missing, partial, status_wrong = [], [], [], [], []
    for rid in sorted(stated):
        pid = owner.get(rid)
        if pid is None:
            missing.append(rid)
            continue
        pred, judgment = preds[pid], judged[pid]
        if pred.get("rationale_status") != "stated":
            status_wrong.append(rid)
        if not pred.get("rationale"):
            empty.append(rid)
        elif (
            judgment.get("rationale_support") == "supported"
            and pred.get("rationale_status") == "stated"
        ):
            covered.append(rid)
        else:
            partial.append(rid)
    rationale_judged = all(
        "rationale_support" in judged[pid] for rid, pid in owner.items() if rid in stated
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": ratio(tp, tp + fp) if complete else None,
        "recall": ratio(tp, tp + fn) if complete else None,
        "f1": ratio(2 * tp, 2 * tp + fp + fn) if complete else None,
        "reference_complete": reference_complete,
        "judgment_complete": judged.keys() == preds.keys(),
        "judgment_coverage": ratio(len(judged), len(preds)),
        "unjudged_prediction_ids": sorted(preds.keys() - judged.keys()),
        "unclear": sum(j["support"] == "unclear" for j in judged.values()),
        "matches": [
            {"reference_id": rid, "prediction_id": pid} for rid, pid in sorted(owner.items())
        ],
        "rationale": {
            "covered": len(covered),
            "eligible": len(stated),
            "coverage": ratio(len(covered), len(stated)) if complete and rationale_judged else None,
            "covered_ids": covered,
            "empty_ids": empty,
            "missing_decision_ids": missing,
            "incomplete_or_unsupported_ids": partial,
            "status_error_ids": status_wrong,
            "judgment_complete": rationale_judged,
        },
    }


def evidence_recall(groups, fragments):
    """Each necessary group has alternatives; require a whole visible source span."""
    hits = []
    for group in groups:
        hit = any(
            candidate["source_id"] == visible["source_id"]
            and visible["start"] <= candidate["start"] < candidate["end"] <= visible["end"]
            for candidate in group["alternatives"]
            for visible in fragments
        )
        hits.append({"group_id": group["group_id"], "hit": hit})
    return {
        "hit": sum(x["hit"] for x in hits),
        "total": len(hits),
        "recall": ratio(sum(x["hit"] for x in hits), len(hits)),
        "groups": hits,
    }


def score_qa(reference, answer, judgment, fragments):
    """Claims and facts have stable IDs; a missing item invalidates its overall rate."""
    claims = _indexed(answer.get("claims", []), "claim_id")
    facts = _indexed(reference.get("facts", []), "fact_id")
    judged_claims = _indexed(judgment.get("claims", []), "claim_id")
    judged_facts = _indexed(judgment.get("facts", []), "fact_id")
    if judged_claims.keys() - claims.keys() or judged_facts.keys() - facts.keys():
        raise ValueError("judge returned unknown claim/fact IDs")
    failed = answer["status"] not in {"ok", "empty"}
    claim_complete = claims.keys() == judged_claims.keys()
    fact_complete = not claims or facts.keys() == judged_facts.keys()
    supported = sum(x["support"] == "supported" for x in judged_claims.values())
    unsupported = sum(x["support"] == "unsupported" for x in judged_claims.values())
    fact_hits = (
        0 if failed or not claims else sum(x["covered"] is True for x in judged_facts.values())
    )
    answerable = reference.get("answerability") == "answerable"
    insufficient = (
        reference.get("answerability") == "insufficient"
        and reference.get("whole_pool_verified") is True
    )
    return {
        "claim_count": len(claims),
        "supported": supported,
        "unsupported": unsupported,
        "unclear": sum(x["support"] == "unclear" for x in judged_claims.values()),
        "claim_judgment_complete": claim_complete,
        "claim_judgment_coverage": ratio(len(judged_claims), len(claims)),
        "unsupported_rate": ratio(unsupported, len(claims)) if claim_complete else None,
        "facts_hit": fact_hits,
        "facts_total": len(facts),
        "fact_coverage": ratio(fact_hits, len(facts)) if answerable and fact_complete else None,
        "fact_judgment_complete": fact_complete,
        "correct_abstention": (not failed and not claims) if insufficient else None,
        "production_failed": failed,
        "evidence": evidence_recall(reference.get("evidence_groups", []), fragments),
    }
