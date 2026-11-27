"""Check the final comparison inventory, frozen citations, scores, and timing."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median

from historykg.io import read_json, read_jsonl, write_json

HERE = Path(__file__).resolve().parent
BROWSER_MARKER = re.compile(r"::browser-complete\{[^\n]*\}")


def summarize(dataset, directory):
    plan = read_json(directory / "qa-protocol.json")
    common = set(plan["codex_and_edges"])
    sources = {v["source_id"]: v["text"] for v in read_jsonl(dataset / "sources.jsonl")}
    answers = {a: [] for a in "OABCDE"}
    rows = []
    identical = []
    checked = 0
    for n, rubric in enumerate(plan["rubric"], 1):
        arms = "OABCDE" if n in common else "OAB"
        score = read_json(directory / "scores" / f"live-q{n}.json")["scores"]
        review = directory / "score-review.json"
        if review.exists():
            score.update(read_json(review).get(str(n), {}))
        if set(score) != set(arms):
            raise ValueError(f"Unexpected score groups for Q{n}")
        q = {}
        for arm in arms:
            prefix = "live-" if arm in "OABC" else ""
            path = directory / "records" / f"{prefix}{arm}{n}.json"
            item = read_json(path)
            if arm in "OABC":
                if item["max_output_tokens"] != 32768:
                    raise ValueError(f"Unexpected output cap in {path.name}")
                for ref in item["evidence"]:
                    if sources[ref["source_id"]][ref["start"]:ref["end"]] != ref["quote"]:
                        raise ValueError(f"Invalid frozen quote in {path.name}")
                    checked += 1
            values = score[arm]["points"]
            if len(values) != len(rubric) or any(x not in (0, .5, 1) for x in values):
                raise ValueError(f"Invalid rubric scores in {path.name}")
            points, seconds = sum(values), item.get("seconds", item.get("elapsed_seconds"))
            status = item["status"]
            if arm in "DE" and BROWSER_MARKER.fullmatch(item["answer"].strip()):
                status = "empty"
            facts = {"score": points, "max": len(rubric), "seconds": seconds,
                     "status": status, "record": path.relative_to(directory).as_posix()}
            q[arm] = facts
            answers[arm].append({"number": n, **facts})
        if n in common:
            b = read_json(directory / q["B"]["record"])
            c = read_json(directory / q["C"]["record"])
            if b["context_sha256"] != c["context_sha256"]:
                raise ValueError(f"B and C used different original passages on Q{n}")
            identical.append({"question": n, "explicit_edges": len(c["graph_edges"])})
        rows.append(q)

    def stats(values):
        return {
            "score": sum(v["score"] for v in values), "max": sum(v["max"] for v in values),
            "score_300s": sum(v["score"] for v in values if v["seconds"] <= 300),
            "median_seconds": round(median(v["seconds"] for v in values), 1),
            "statuses": dict(Counter(v["status"] for v in values)),
        }
    totals = {arm: {"all": stats(values),
                    "common": stats([v for v in values if v["number"] in common])}
              for arm, values in answers.items()}
    summary = {"questions": len(rows), "comparison_cells": sum(map(len, rows)), "totals": totals,
               "per_question": rows, "matched_BC_inputs": identical, "api_citations": checked}
    write_json(directory / "qa-summary.json", summary)
    print(json.dumps(totals, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--records", type=Path, default=HERE)
    args = parser.parse_args()
    summarize(args.dataset, args.records)
