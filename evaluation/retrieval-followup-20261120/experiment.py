"""Run one independent cell. Old and new queries share the original Bailian transport."""

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCAL = ROOT / ".local/retrieval-followup"
PREVIOUS = HERE.parent / "agent-comparison-20261120"
P = json.loads((HERE / "protocol.json").read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_runner(baseline=False):
    sys.path.insert(0, str(LOCAL / "baseline" if baseline else ROOT))
    import historykg

    if baseline and not Path(historykg.__file__).is_relative_to(LOCAL / "baseline"):
        raise RuntimeError("Run the old program in a fresh Python process")

    spec = importlib.util.spec_from_file_location("previous_comparison", PREVIOUS / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.P = P
    module.HERE = HERE
    module.LOCAL = LOCAL
    return module


def cfg_for(run, arm, key):
    cfg = run.pipeline.query_config(run.CFG)
    cfg.update(
        system="A" if arm == "A" else "B",
        query_output_root=str(LOCAL / key / "queries"),
        answer_output_root=str(LOCAL / key / "answers"),
        budget={"mode": "provider_balance", "ledger_path": str(LOCAL / key / "usage.sqlite3")},
    )
    cfg["answer"] = {
        **run.CFG["model"],
        "thinking": "enabled",
        "reasoning_effort": "max",
        "max_output_tokens": 8192,
        "timeout_seconds": 90,
        "max_retries": 2,
    }
    return cfg


def graph_edges(prepared, visible):
    entities = {n["id"]: n for p in prepared["paths"] for n in p["entities"]}
    evidence = {e["evidence_id"]: e for e in prepared["path_evidence"]}

    def label(i):
        e = entities[i]
        p = e["properties"]
        return [
            e["type"],
            next(
                (
                    p[k]
                    for k in ("tag", "number", "sha", "path", "display_name", "title")
                    if p.get(k) is not None
                ),
                e.get("key", i),
            ),
        ]

    edges = []
    for path in prepared["paths"]:
        for r in path["relations"]:
            refs = [evidence[i] for i in r["evidence_ids"] if i in evidence]
            if not any(
                f["source_id"] == e["source_id"] and f["end"] > e["start"] and e["end"] > f["start"]
                for e in refs
                for f in visible
            ):
                continue
            edge = [label(r["from_id"]), r["type"], label(r["to_id"])]
            if edge not in edges:
                edges.append(edge)
            if len(edges) == 10:
                return edges
    return edges


def api(arm, n, development=False, dry=False, more_output=False, numbered=False, live=False):
    key = ("dev-" if development else "") + arm + str(n)
    primary = key
    if numbered:
        key = "passages-" + key
    if live:
        key = "live-" + key
    if more_output:
        key = "output-" + key
    dest = HERE / "records" / (key + ".json")
    if dest.exists() and not dry:
        return
    run = load_runner(arm == "O")
    cfg = cfg_for(run, arm, key)
    cfg["answer"]["citation_style"] = "passage_numbers" if numbered else "quotes"
    if more_output:
        cfg["answer"]["max_output_tokens"] = 16384
    os.environ["DEEPSEEK_API_KEY"] = "local-relay-routing-only"
    run.ans.run_request = run.via_bailian
    if live:
        cfg["answer"] = dict(run.CFG["answer"])
        run.ans.run_request = run.gateway_call
        if arm == "O":
            # Only the connection and timeout are shared; retrieval and answer code stay frozen.
            spec = importlib.util.spec_from_file_location(
                "historykg.llm.comparison_bailian_gateway", ROOT / "historykg/llm/gateway.py"
            )
            gateway = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gateway)
            run.prepare_request = gateway.prepare_request
            run.ans.run_request = gateway.run_request
    questions = json.loads((PREVIOUS / "protocol.json").read_text()) if development else P
    run.P = questions
    if (numbered or live) and n > len(P["questions"]):
        extra = json.loads((HERE / "citation-check-protocol.json").read_text())
        run.P = {**P, "questions": [*P["questions"], *(x["question"] for x in extra)]}
    q = run.question(n - 1)
    request = {"dataset_id": run.ID, "question": q, "kind": "search"}
    t = time.monotonic()
    prepared = run.prepare_query(request, config=cfg)
    rendered = run.render_context(prepared["candidates"], max_characters=12000)
    save(LOCAL / key / "visible.json", rendered["fragments"])
    digest = hashlib.sha256(rendered["rendered"].encode()).hexdigest()
    if more_output or (numbered and n <= 6):
        previous = json.loads((HERE / "records" / (primary + ".json")).read_text())
        assert digest == previous["context_sha256"]
    if dry:
        print(key, len(rendered["fragments"]), digest)
        return
    edges = graph_edges(prepared, rendered["fragments"]) if arm == "C" else []

    def inject(**kwargs):
        if arm == "C":
            kwargs["payload"] = {**kwargs["payload"], "graph_edges": edges}
        return run.prepare_request(**kwargs)

    with (
        patch.object(run.ans, "prepare_request", inject),
        patch("historykg.query.service.prepare_query", return_value=prepared),
    ):
        result = run.query(request, config=cfg).model_dump(mode="json")
    elapsed = time.monotonic() - t
    save(LOCAL / key / "result.json", result)
    answers = sorted((LOCAL / key / "answers").glob("**/attempts/*/response.json"))
    responses = []
    for f in answers:
        receipt = json.loads(f.read_text())
        body = json.loads(receipt["body"])
        choices = body.get("choices") or [{}]
        responses.append(
            dict(
                status=receipt["status_code"],
                usage=body.get("usage"),
                answer=choices[0].get("message", {}).get("content"),
                reason=choices[0].get("finish_reason"),
                provider_error=(body.get("error") or {}).get("message"),
            )
        )
    cited = {i for c in result["claims"] for i in c["evidence_ids"]}
    strings = [s for s in result["gaps"] if isinstance(s, str)]
    save(
        dest,
        dict(
            arm=arm,
            question=q,
            status=result["status"],
            error=result["error"],
            seconds=round(elapsed, 3),
            method=prepared["method_version"],
            max_output_tokens=cfg["answer"]["max_output_tokens"],
            timeout_seconds=cfg["answer"]["timeout_seconds"],
            claims=result["claims"],
            evidence=[e for e in result["evidence"] if e["evidence_id"] in cited],
            gaps=strings,
            context_characters=rendered["characters"],
            context_sha256=digest,
            visible=[{k: v for k, v in f.items() if k != "quote"} for f in rendered["fragments"]],
            graph_edges=edges,
            responses=responses,
        ),
    )
    print(key, result["status"], round(elapsed, 1), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("arm", choices=list("OABCDE"))
    parser.add_argument("numbers", nargs="+", type=int)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--more-output", action="store_true")
    parser.add_argument("--numbered", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.arm in "DE":
        run = load_runner()
        for n in args.numbers:
            assert n in P["codex_and_edges"]
            run.runner(args.arm, n - 1)
    else:
        for n in args.numbers:
            api(args.arm, n, args.development, args.dry, args.more_output, args.numbered, args.live)
