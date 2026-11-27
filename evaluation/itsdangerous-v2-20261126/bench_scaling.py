"""Benchmark Neo4j snapshot vs Cypher on-demand subgraph scaling at 1x, 5x, and 10x corpus sizes."""

from __future__ import annotations

import gc
import json
import os
import shutil
import statistics
import time
from pathlib import Path

from historykg import collector
from historykg.graph.store import GraphStore, fingerprint, read_package
from historykg.ids import text_hash
from historykg.io import read_json, write_json
from historykg.query.frozen_index import VERSION as INDEX_VERSION, drop_index, freeze_index
from historykg.query.service import prepare_query

ROOT = Path(__file__).resolve().parents[2]
FROZEN_DS = (
    ROOT
    / ".local/full-history-itsdangerous/datasets"
    / "dataset-0c94c5af1f7f64c628c4a7fe05b496647ad8ef760e18eee01287fd43f1ea3ef2"
)
OUT_DIR = Path(__file__).resolve().parent
WORK_TMP = Path("/tmp/historykg-v7-scale")

BENCH_QUERIES = [
    ("release", "search", "2.1.0 是哪天出的？请给出正式 GitHub Release 的 UTC 日期和出处。"),
    ("change", "search", "PR #408 为什么改发布流程？它实际改了哪个文件？"),
    ("membership", "search", "PR #153 最早进了哪个正式版？"),
    ("decision", "search", "为什么改用标准库 JSON？早期有没有拒绝过类似提议，最终由哪个 PR 合并落地并改了哪些文件？"),
    ("code", "search", "src/itsdangerous/serializer.py 中的 Serializer.dumps 和 Serializer.loads 先做什么后做什么？"),
    ("timeline", "timeline", "2.0.1 发布时间线与包含的 PR 提交"),
]


def _prefix_id(old_id: str, clone_idx: int) -> str:
    if ":" in old_id:
        head, tail = old_id.split(":", 1)
        return f"{head}:c{clone_idx}_{tail}"
    return f"c{clone_idx}_{old_id}"


def build_scaled_package(base_pkg: dict, base_payloads: list[dict], scale: int, ds_dir: Path) -> dict:
    ds_dir.mkdir(parents=True, exist_ok=True)
    exports_dir = ds_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    dataset_id = f"scale_{scale}x_{text_hash(f'itsdangerous-{scale}x')[:24]}"
    if scale == 1:
        write_json(
            exports_dir / "discussion_input.json",
            {"version": INDEX_VERSION, "dataset_id": dataset_id, "payloads": base_payloads},
        )
        pkg = {
            **base_pkg,
            "manifest": {**base_pkg["manifest"], "dataset_id": dataset_id},
            "sources": [{**s, "dataset_id": dataset_id} for s in base_pkg["sources"]],
            "entities": [{**e, "dataset_id": dataset_id} for e in base_pkg["entities"]],
            "evidence": [{**e, "dataset_id": dataset_id} for e in base_pkg["evidence"]],
            "relations": [{**r, "dataset_id": dataset_id} for r in base_pkg["relations"]],
            "dataset_dir": str(ds_dir),
        }
        pkg["fingerprint"] = fingerprint(pkg)
        return pkg

    sources = [{**s, "dataset_id": dataset_id} for s in base_pkg["sources"]]
    entities = [{**e, "dataset_id": dataset_id} for e in base_pkg["entities"]]
    evidence = [{**e, "dataset_id": dataset_id} for e in base_pkg["evidence"]]
    relations = [{**r, "dataset_id": dataset_id} for r in base_pkg["relations"]]
    subjects = [dict(s) for s in base_pkg["subjects"]]
    scaled_payloads = [dict(p) for p in base_payloads]

    for k in range(1, scale):
        num_shift = k * 1_000_000
        id_shift = k * 10_000_000_000
        sid_map = {s["source_id"]: _prefix_id(s["source_id"], k) for s in base_pkg["sources"]}
        eid_map = {e["id"]: _prefix_id(e["id"], k) for e in base_pkg["entities"]}
        ev_map = {e["evidence_id"]: _prefix_id(e["evidence_id"], k) for e in base_pkg["evidence"]}

        for p in base_payloads:
            new_num = int(p["number"]) + num_shift
            new_thread = {**p["thread"], "number": new_num}
            if isinstance(new_thread.get("id"), int):
                new_thread["id"] = new_thread["id"] + id_shift
            scaled_payloads.append(
                {
                    **p,
                    "number": new_num,
                    "thread": new_thread,
                    "issue_comments": [
                        {**c, "id": int(c["id"]) + id_shift}
                        for c in p.get("issue_comments", [])
                    ],
                    "reviews": [
                        {**r, "id": int(r["id"]) + id_shift}
                        for r in p.get("reviews", [])
                    ],
                    "review_comments": [
                        {**rc, "id": int(rc["id"]) + id_shift}
                        for rc in p.get("review_comments", [])
                    ],
                }
            )

        for s in base_pkg["sources"]:
            row = {
                **s,
                "dataset_id": dataset_id,
                "source_id": sid_map[s["source_id"]],
                "origin_key": f"c{k}:{s['origin_key']}",
            }
            if row.get("discussion_mapping"):
                dm = dict(row["discussion_mapping"])
                dm["number"] = int(dm["number"]) + num_shift
                if dm["source_type"] == "body":
                    dm["source_id"] = str(dm["number"])
                else:
                    dm["source_id"] = str(int(dm["source_id"]) + id_shift)
                row["discussion_mapping"] = dm
            sources.append(row)
        for e in base_pkg["evidence"]:
            ev_copy = {
                **e,
                "dataset_id": dataset_id,
                "evidence_id": ev_map[e["evidence_id"]],
                "source_id": sid_map.get(e["source_id"], e["source_id"]),
            }
            evidence.append(ev_copy)
        for ent in base_pkg["entities"]:
            props = dict(ent.get("properties") or {})
            if isinstance(props.get("number"), int):
                props["number"] = props["number"] + k * 1_000_000
            if isinstance(props.get("tag"), str):
                props["tag"] = f"{props['tag']}-c{k}"
            if isinstance(props.get("path"), str):
                props["path"] = f"c{k}/{props['path']}"
            if isinstance(props.get("subject_id"), str):
                props["subject_id"] = eid_map.get(props["subject_id"], props["subject_id"])
            if "statement_evidence_ids" in props:
                props["statement_evidence_ids"] = [
                    ev_map.get(x, x) for x in props["statement_evidence_ids"]
                ]
            if "rationale_evidence_ids" in props:
                props["rationale_evidence_ids"] = [
                    ev_map.get(x, x) for x in props["rationale_evidence_ids"]
                ]
            entities.append(
                {
                    **ent,
                    "dataset_id": dataset_id,
                    "id": eid_map[ent["id"]],
                    "properties": props,
                    "evidence_ids": [ev_map.get(x, x) for x in ent.get("evidence_ids", [])],
                }
            )
        for rel in base_pkg["relations"]:
            relations.append(
                {
                    **rel,
                    "dataset_id": dataset_id,
                    "id": _prefix_id(rel["id"], k),
                    "from_id": eid_map.get(
                        rel["from_id"], sid_map.get(rel["from_id"], rel["from_id"])
                    ),
                    "to_id": eid_map.get(rel["to_id"], sid_map.get(rel["to_id"], rel["to_id"])),
                    "evidence_ids": [ev_map.get(x, x) for x in rel.get("evidence_ids", [])],
                }
            )

    write_json(
        exports_dir / "discussion_input.json",
        {"version": INDEX_VERSION, "dataset_id": dataset_id, "payloads": scaled_payloads},
    )
    sources.sort(key=lambda r: r["source_id"])
    entities.sort(key=lambda r: r["id"])
    evidence.sort(key=lambda r: r["evidence_id"])
    relations.sort(key=lambda r: r["id"])
    pkg = {
        "manifest": {**base_pkg["manifest"], "dataset_id": dataset_id},
        "subjects": subjects,
        "sources": sources,
        "entities": entities,
        "evidence": evidence,
        "relations": relations,
        "dataset_dir": str(ds_dir),
    }
    pkg["fingerprint"] = fingerprint(pkg)
    return pkg


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round((len(sorted_vals) - 1) * p))))
    return sorted_vals[idx]


def run_benchmark(neo4j_uri: str = "bolt://127.0.0.1:17691") -> dict:
    base_pkg = read_package(FROZEN_DS)
    base_payloads = read_json(FROZEN_DS / "exports/discussion_input.json")["payloads"]
    WORK_TMP.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{(WORK_TMP / 'bench_discussion.sqlite3').as_posix()}"
    collector.initialize_database(db_url)
    cfg = {"graph": {"neo4j_uri": neo4j_uri}, "database_url": db_url}

    scales = {}
    parity_1x = []
    created_datasets = []

    try:
        for scale in (1, 5, 10):
            ds_dir = WORK_TMP / f"scale_{scale}x"
            pkg = build_scaled_package(base_pkg, base_payloads, scale, ds_dir)
            ds_id = pkg["manifest"]["dataset_id"]
            t_load0 = time.perf_counter()
            pkg["retrieval_index"] = freeze_index(pkg, db_url)
            with GraphStore(cfg) as store:
                store.write(pkg)
            load_sec = round(time.perf_counter() - t_load0, 3)
            created_datasets.append((ds_id, pkg["retrieval_index"]))
            print(
                f"Loaded {scale}x: {len(pkg['entities'])} entities, "
                f"{len(pkg['relations'])} rels, {len(pkg['sources'])} sources in {load_sec}s",
                flush=True,
            )

            mode_results = {}
            for mode in ("snapshot", "cypher_subgraph"):
                repeats = 5 if mode == "cypher_subgraph" else {1: 3, 5: 2, 10: 1}[scale]
                all_latencies = []
                per_query = []
                hydrated_sources_list = []
                for qname, kind, question in BENCH_QUERIES:
                    warm = prepare_query(
                        {"dataset_id": ds_id, "question": question, "kind": kind},
                        config={**cfg, "system": "B", "query_mode": mode},
                    )
                    times = []
                    for _ in range(repeats):
                        t0 = time.perf_counter()
                        res = prepare_query(
                            {"dataset_id": ds_id, "question": question, "kind": kind},
                            config={**cfg, "system": "B", "query_mode": mode},
                        )
                        times.append((time.perf_counter() - t0) * 1000)
                    times.sort()
                    all_latencies.extend(times)
                    hydrated_sources_list.append(len(res["source_by_id"]))
                    per_query.append(
                        {
                            "query": qname,
                            "kind": kind,
                            "repeats": repeats,
                            "p50_ms": round(statistics.median(times), 2),
                            "mean_ms": round(statistics.mean(times), 2),
                            "p95_ms": round(_percentile(times, 0.95), 2),
                            "paths": len(warm["paths"]),
                            "candidates": len(warm["candidates"]),
                            "hydrated_sources": len(warm["source_by_id"]),
                            "top_candidate_source_ids": [
                                c["source_id"] for c in warm["candidates"][:5]
                            ],
                        }
                    )
                all_latencies.sort()
                mode_results[mode] = {
                    "overall_p50_ms": round(statistics.median(all_latencies), 2),
                    "overall_mean_ms": round(statistics.mean(all_latencies), 2),
                    "overall_p95_ms": round(_percentile(all_latencies, 0.95), 2),
                    "median_hydrated_sources": int(statistics.median(hydrated_sources_list)),
                    "per_query": per_query,
                }
                if scale == 1:
                    scales.setdefault("_tmp_1x", {})[mode] = per_query

            snap_med = mode_results["snapshot"]["overall_p50_ms"]
            cyp_med = mode_results["cypher_subgraph"]["overall_p50_ms"]
            snap_p95 = mode_results["snapshot"]["overall_p95_ms"]
            cyp_p95 = mode_results["cypher_subgraph"]["overall_p95_ms"]
            scales[f"{scale}x"] = {
                "counts": {
                    "sources": len(pkg["sources"]),
                    "entities": len(pkg["entities"]),
                    "relations": len(pkg["relations"]),
                    "evidence": len(pkg["evidence"]),
                },
                "load_seconds": load_sec,
                "speedup_p50": round(snap_med / cyp_med, 2) if cyp_med else None,
                "speedup_p95": round(snap_p95 / cyp_p95, 2) if cyp_p95 else None,
                **mode_results,
            }
            drop_index(db_url, pkg["retrieval_index"])
            with GraphStore(cfg) as store:
                store.delete_dataset(ds_id)
            created_datasets.remove((ds_id, pkg["retrieval_index"]))
            shutil.rmtree(ds_dir, ignore_errors=True)
            del pkg
            gc.collect()

        snap_1x = scales.pop("_tmp_1x")["snapshot"]
        cyp_1x_rows = scales["1x"]["cypher_subgraph"]["per_query"]
        for s_row, c_row in zip(snap_1x, cyp_1x_rows, strict=True):
            parity_1x.append(
                {
                    "query": s_row["query"],
                    "paths_equal": s_row["paths"] == c_row["paths"],
                    "top_candidates_equal": (
                        s_row["top_candidate_source_ids"] == c_row["top_candidate_source_ids"]
                    ),
                }
            )
    finally:
        with GraphStore(cfg) as store:
            for ds_id, idx_desc in created_datasets:
                drop_index(db_url, idx_desc)
                store.delete_dataset(ds_id)

    summary = {
        "base_dataset_id": base_pkg["manifest"]["dataset_id"],
        "neo4j_uri": neo4j_uri,
        "scales": scales,
        "parity_1x": parity_1x,
    }
    write_json(OUT_DIR / "scaling-benchmark.json", summary)
    print(
        json.dumps(
            {
                k: {
                    "entities": v["counts"]["entities"],
                    "relations": v["counts"]["relations"],
                    "sources": v["counts"]["sources"],
                    "snapshot_p50_ms": v["snapshot"]["overall_p50_ms"],
                    "cypher_p50_ms": v["cypher_subgraph"]["overall_p50_ms"],
                    "speedup_p50": v["speedup_p50"],
                    "speedup_p95": v["speedup_p95"],
                }
                for k, v in scales.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return summary


if __name__ == "__main__":
    run_benchmark(os.environ.get("P2_TEST_NEO4J_URI", "bolt://127.0.0.1:17691"))
