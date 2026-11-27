"""Score frozen production extraction against independently reviewed source-only references."""

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from pydantic import ValidationError

from historykg.evaluation import extraction, reference
from historykg.evaluation.metrics import score_extraction
from historykg.io import read_json, read_jsonl, write_json
from historykg.llm.gateway import bailian_connection, digest

HERE = Path(__file__).resolve().parent
DRAFT = "bailian/deepseek-v4.1-flash-1017"
REVIEW = "bailian/glm-5.3"
SEED = "itsdangerous-final-extraction-20261121"
MAX_THREAD_CHARACTERS = 24000


def select_units(units, pool):
    sizes = {unit["unit_id"]: sum(len(pool[s]["text"]) for s in unit["source_ids"])
             for unit in units}
    groups = set()
    selected = []
    for kind in ("/issues/", "/pull/"):
        eligible = sorted(
            (u for u in units if u["completeness"] == "complete"
             and kind in u["origin_thread"] and sizes[u["unit_id"]] <= MAX_THREAD_CHARACTERS),
            key=lambda u: (sizes[u["unit_id"]], u["unit_id"]),
        )
        for bucket in range(3):
            band = eligible[bucket * len(eligible) // 3:(bucket + 1) * len(eligible) // 3]
            chosen = 0
            for unit in sorted(band, key=lambda u: digest([SEED, u["unit_id"]])):
                if unit["topic_group"] in groups:
                    continue
                selected.append(unit)
                groups.add(unit["topic_group"])
                chosen += 1
                if chosen == 5:
                    break
            if chosen != 5:
                raise ValueError("A sampling stratum did not contain five distinct topics")
    return selected


def evaluate(dataset, private):
    manifest = read_json(dataset / "manifest.json")
    units = read_jsonl(dataset / "source_units.jsonl")
    sources = {s["source_id"]: s for s in read_jsonl(dataset / "sources.jsonl")}
    selected = select_units(units, sources)
    protocol = {
        "dataset_id": manifest["dataset_id"], "repo": manifest["repo"], "seed": SEED,
        "max_thread_characters": MAX_THREAD_CHARACTERS, "draft_model": DRAFT,
        "review_model": REVIEW, "judge_model": REVIEW,
        "units": [u["unit_id"] for u in selected],
        "source_hash": digest([
            [u["unit_id"], [(sid, sources[sid]["text_sha256"]) for sid in u["source_ids"]]]
            for u in selected
        ]),
    }
    path = private / "protocol.json"
    if path.exists() and read_json(path) != protocol:
        raise ValueError("The frozen evaluation protocol changed")
    write_json(path, protocol)
    catalog = read_jsonl(dataset / "subjects.jsonl")
    endpoint, headers = bailian_connection()
    repo = manifest["repo"]

    def request(key, model, prompt, payload, schema, validate):
        dest = private / "runs" / f"{key}.json"
        request_id = digest(["compact-json-v2", model, prompt, payload, schema])
        if dest.exists():
            old = read_json(dest)
            if old["request_id"] != request_id:
                raise ValueError(f"Cached request differs for {key}")
            return old["parsed"]
        attempts = []
        field = "judgments" if "predictions" in payload else "units"
        instruction = (
            f"Perform the requested evaluation on the supplied data now. Return an instance "
            f"with exactly the top-level key {field!r} and the completed array. "
            "Never return or repeat the JSON schema."
        )
        field_guide = (
                'Each judgment: prediction_id, reference_ids, support, rationale_support, '
                'explanation. Support values: supported, unsupported, unclear.'
                if field == "judgments" else
                'Each unit: unit_id, decisions, external_claims, review_notes, unclear_notes. '
                'Each decision: subject_id, target_repo, action, status, statement, rationale, '
                'rationale_status, statement_evidence, rationale_evidence. Each quote: source_id '
                'and quote. Use empty lists when there is nothing to record.'
        )
        messages = [
            {"role": "system", "content": prompt + "\n" + instruction + "\n" + field_guide},
            {"role": "user",
             "content": json.dumps(payload, ensure_ascii=False) + "\n" + instruction},
        ]
        for number in range(1, 4):
            started = time.monotonic()
            diagnosis = {}
            try:
                response = httpx.post(
                    endpoint, headers=headers, trust_env=False, timeout=150,
                    json={"model": model, "messages": messages, "max_tokens": 6144,
                          "response_format": {"type": "json_object"}, "temperature": 0,
                          "thinking": {"type": "disabled"}, "enable_thinking": False,
                          "reasoning_effort": "none"},
                )
                diagnosis["http_status"] = response.status_code
                response.raise_for_status()
                body = response.json()
                choice = body["choices"][0]
                content = (choice["message"]["content"] or "").strip()
                diagnosis.update(usage=body.get("usage"), finish_reason=choice["finish_reason"],
                                 content_characters=len(content))
                if content.startswith("```") and content.endswith("```"):
                    content = content.split("\n", 1)[1][:-3]
                value = json.loads(content)
                validate(value)
            except (httpx.HTTPError, ValueError, TypeError, IndexError, KeyError) as exc:
                if isinstance(exc, ValidationError):
                    reason = json.dumps(exc.errors(include_input=False, include_url=False))
                elif isinstance(exc, ValueError):
                    reason = str(exc)
                else:
                    reason = type(exc).__name__
                attempts.append({"attempt": number, "seconds": time.monotonic() - started,
                                 "error": type(exc).__name__, "validation": reason[:1500],
                                 **diagnosis})
                messages.append({
                    "role": "user", "content": (
                        instruction + " Cover every unit or prediction exactly once. "
                        "Use unique, verbatim source spans as quotes. Validator: " + reason[:1000]
                    ),
                })
                if number == 3:
                    write_json(dest.with_suffix(".failed.json"), attempts)
                    raise RuntimeError(f"Could not validate {key}: {type(exc).__name__}") from exc
                continue
            attempts.append({"attempt": number, "seconds": time.monotonic() - started,
                             "usage": body.get("usage"), "model": body.get("model", model)})
            write_json(dest, {"request_id": request_id, "attempts": attempts, "parsed": value})
            return value

    batches = [selected[i:i + 3] for i in range(0, len(selected), 3)]

    def read_sources(unit):
        rows = [{k: sources[sid][k] for k in
                 ("source_id", "kind", "text", "author", "occurred_at", "trust_tier")}
                for sid in unit["source_ids"]]
        return {"unit_id": unit["unit_id"], "origin_thread": unit["origin_thread"], "sources": rows}

    def payload(batch):
        visible = {sid for unit in batch for sid in unit["source_ids"]}
        scope = [s for s in catalog if s["entity_type"] == "Project"
                 or visible.intersection(s["source_ids"])]
        return {"repo": repo, "subjects": scope, "units": [read_sources(u) for u in batch]}

    def make_reference(index_batch):
        index, batch = index_batch
        data = payload(batch)
        schema = reference.ReferenceOutput.model_json_schema()

        def validate(value):
            reference.validate_reference(value, data)
        draft = request(f"draft-{index}", DRAFT, reference.PROMPT, data, schema, validate)
        reviewed = request(
            f"review-{index}", REVIEW, reference.REVIEW_PROMPT,
            {**data, "draft_reference": draft}, schema, validate,
        )
        print(f"reference {index + 1}/{len(batches)} reviewed", flush=True)
        return {
            unit["unit_id"]: [
                {**d, "reference_id": hashlib.sha256(
                    f"{unit['unit_id']}:{i}".encode()).hexdigest(), "unit_id": unit["unit_id"]}
                for i, d in enumerate(unit["decisions"])
            ]
            for unit in reviewed["units"]
        }

    with ThreadPoolExecutor(max_workers=4) as workers:
        reviewed_batches = workers.map(make_reference, enumerate(batches))
        grouped = {unit: rows for batch in reviewed_batches for unit, rows in batch.items()}

    references = [r for rows in grouped.values() for r in rows if r["target_repo"] == repo]
    unknown = [r for rows in grouped.values() for r in rows if r["target_repo"] is None]
    predictions = [
        {**d, "prediction_id": d["id"]}
        for d in read_jsonl(dataset / "p4/decisions.jsonl") if d["unit_id"] in grouped
    ]
    evidence = {e["evidence_id"]: e for e in read_jsonl(dataset / "p4/evidence.jsonl")}

    def judge(index_batch):
        index, batch = index_batch
        keys = {u["unit_id"] for u in batch}
        preds = [d for d in predictions if d["unit_id"] in keys]
        refs = [r for r in references if r["unit_id"] in keys]
        if not preds:
            return []
        by_pred = {d["prediction_id"]: d["unit_id"] for d in preds}
        by_ref = {r["reference_id"]: r["unit_id"] for r in refs}
        data = {**payload(batch), "references": refs, "predictions": preds,
                "prediction_evidence": [
                    evidence[eid] for p in preds
                    for eid in p["statement_evidence_ids"] + p["rationale_evidence_ids"]
                ]}

        def validate(value):
            rows = extraction.MatchOutput.model_validate(value).judgments
            if len(rows) != len(by_pred) or {r.prediction_id for r in rows} != set(by_pred):
                raise ValueError("Judgments do not cover every prediction exactly once")
            if any(by_ref.get(rid) != by_pred[r.prediction_id]
                   for r in rows for rid in r.reference_ids):
                raise ValueError("A reference match refers to a different discussion")
        parsed = request(f"judge-{index}", REVIEW, extraction.PROMPT, data,
                         extraction.MatchOutput.model_json_schema(), validate)
        print(f"prediction batch {index + 1}/{len(batches)} scored", flush=True)
        return parsed["judgments"]

    with ThreadPoolExecutor(max_workers=4) as workers:
        judgments = [j for batch in workers.map(judge, enumerate(batches)) for j in batch]
    write_json(private / "scoring.json", {"references": references, "unresolved": unknown,
                                         "predictions": predictions, "judgments": judgments})
    metrics = score_extraction(references, predictions, judgments, reference_complete=not unknown)
    rationale = metrics["rationale"]
    summary = {
        "dataset_id": manifest["dataset_id"], "source_hash": protocol["source_hash"],
        "protocol_sha256": digest(protocol), "units": len(selected),
        "issue_units": 15, "pull_request_units": 15, "seed": SEED,
        "draft_model": DRAFT, "review_model": REVIEW,
        "references": len(references), "predictions": len(predictions),
        "unresolved_references": len(unknown),
        **{k: metrics[k] for k in ("tp", "fp", "fn", "precision", "recall", "f1",
                                   "judgment_complete", "judgment_coverage")},
        "rationale": {k: rationale[k] for k in ("covered", "eligible", "coverage")},
    }
    write_json(HERE / "extraction-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("private", type=Path)
    args = parser.parse_args()
    evaluate(args.dataset.resolve(strict=True), reference.private_root(args.private))


if __name__ == "__main__":
    main()
