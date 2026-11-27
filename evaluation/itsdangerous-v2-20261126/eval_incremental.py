"""Evaluate chronological T1 -> T2 -> T3 incremental GraphStore.apply_delta evolution."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

from historykg import collector
from historykg.graph.store import GraphStore, fingerprint, read_package
from historykg.ids import text_hash
from historykg.ingest.github import discussion_mapping
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
WORK_TMP = Path("/tmp/historykg-v7-incremental")

CUTOFF_T1 = "2018-10-31T23:59:59Z"  # Covers up through 1.1.0 and early PR #63
CUTOFF_T2 = "2021-05-31T23:59:59Z"  # Covers PR #152, PR #153, 2.0.0, 2.0.1

EVOLUTION_QUERIES = [
    ("q_simplejson_pr152", "为什么移除了 simplejson？", "search"),
    ("q_release_220", "2.2.0 是哪天出的？", "search"),
    ("q_pr372", "PR #372 最早进了哪个正式版？", "search"),
]


def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def slice_package(base_pkg: dict, base_payloads: list[dict], dataset_id: str, cutoff_iso: str | None, ds_dir: Path) -> dict:
    ds_dir.mkdir(parents=True, exist_ok=True)
    exports_dir = ds_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    if cutoff_iso is None:
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

    cutoff_dt = _instant(cutoff_iso)
    assert cutoff_dt is not None
    repo = base_pkg["manifest"]["repo"]
    src_by_id = {s["source_id"]: s for s in base_pkg["sources"]}
    ev_by_id = {e["evidence_id"]: e for e in base_pkg["evidence"]}

    # Build authoritative temporal lookups for entities/sources lacking occurred_at.
    sha_date: dict[str, datetime] = {}
    num_created: dict[int, datetime] = {}
    for e in base_pkg["entities"]:
        props = e.get("properties") or {}
        if e["type"] == "Commit":
            dt = _instant(props.get("committed_at"))
            sha = props.get("sha") or e["key"]
            if dt and sha:
                sha_date[sha] = dt
        elif e["type"] in {"Issue", "PullRequest"}:
            dt = _instant(props.get("created_at"))
            num = props.get("number")
            if dt and num is not None:
                num_created[int(num)] = dt

    release_date: dict[str, datetime] = {}
    for e in base_pkg["entities"]:
        if e["type"] == "Release":
            props = e.get("properties") or {}
            tag = props.get("tag") or e["key"]
            dt = _instant(props.get("published_at")) or sha_date.get(props.get("commit_sha") or "")
            if dt and tag:
                release_date[tag] = dt

    def slice_source(s: dict) -> tuple[dict | None, bool]:
        """Return (sliced_source_or_None, text_modified_flag) respecting cutoff_dt."""
        occ = _instant(s.get("occurred_at"))
        if s.get("occurred_at"):
            return ({**s, "dataset_id": dataset_id}, False) if (occ and occ <= cutoff_dt) else (None, False)

        kind = s.get("kind")
        url = s.get("url") or ""
        if kind == "code":
            m = re.search(r"/blob/([0-9a-f]{40})/", url) or re.match(
                r"^code:([0-9a-f]{40}):", s.get("origin_key") or ""
            )
            dt = sha_date.get(m.group(1)) if m else None
            return ({**s, "dataset_id": dataset_id}, False) if (dt and dt <= cutoff_dt) else (None, False)

        if kind == "git_output":
            cmd = (s.get("git_metadata") or {}).get("command", [])
            dt = None
            for arg in cmd:
                tm = re.fullmatch(r"refs/tags/(.+)\^\{commit\}", str(arg))
                if tm:
                    dt = release_date.get(tm.group(1))
                    break
                sm = re.match(r"^([0-9a-f]{40})(?::|\^\{|$)", str(arg))
                if sm:
                    dt = sha_date.get(sm.group(1))
                    break
            return ({**s, "dataset_id": dataset_id}, False) if (dt and dt <= cutoff_dt) else (None, False)

        if kind == "release_note":
            if "/releases/tag/" in url:
                tag = unquote(url.rsplit("/releases/tag/", 1)[-1])
                dt = release_date.get(tag)
                if dt and dt <= cutoff_dt:
                    return ({**s, "dataset_id": dataset_id}, False)
            return (None, False)

        if kind == "api_response":
            m = re.search(r"/(?:issues|pulls)/(\d+)(?:/|$)", url)
            if m:
                dt = num_created.get(int(m.group(1)))
                return ({**s, "dataset_id": dataset_id}, False) if (dt and dt <= cutoff_dt) else (None, False)

            if url.startswith(f"https://api.github.com/repos/{repo}/git/ref/heads/"):
                try:
                    head_sha = json.loads(s["text"])["object"]["sha"]
                except (ValueError, KeyError, TypeError):
                    head_sha = None
                dt = sha_date.get(head_sha or "")
                return ({**s, "dataset_id": dataset_id}, False) if (dt and dt <= cutoff_dt) else (None, False)

            if url == f"https://api.github.com/repos/{repo}/releases":
                items = json.loads(s["text"])
                kept_items = [
                    item
                    for item in items
                    if isinstance(item, dict)
                    and (dt := _instant(item.get("published_at") or item.get("created_at")))
                    and dt <= cutoff_dt
                ]
                if not kept_items:
                    return (None, False)
                if len(kept_items) == len(items):
                    return ({**s, "dataset_id": dataset_id}, False)
                new_text = json.dumps(kept_items, ensure_ascii=False, indent=2)
                return ({**s, "dataset_id": dataset_id, "text": new_text, "text_sha256": text_hash(new_text)}, True)

            if url == f"https://api.github.com/repos/{repo}/tags":
                items = json.loads(s["text"])
                kept_items = [
                    item
                    for item in items
                    if isinstance(item, dict)
                    and (dt := release_date.get(item.get("name") or ""))
                    and dt <= cutoff_dt
                ]
                if not kept_items:
                    return (None, False)
                if len(kept_items) == len(items):
                    return ({**s, "dataset_id": dataset_id}, False)
                new_text = json.dumps(kept_items, ensure_ascii=False, indent=2)
                return ({**s, "dataset_id": dataset_id, "text": new_text, "text_sha256": text_hash(new_text)}, True)

            if url.endswith(("/pulls", "/issues")):
                items = json.loads(s["text"])
                kept_items = [
                    item
                    for item in items
                    if isinstance(item, dict)
                    and (dt := _instant(item.get("created_at")))
                    and dt <= cutoff_dt
                ]
                if not kept_items:
                    return (None, False)
                if len(kept_items) == len(items):
                    return ({**s, "dataset_id": dataset_id}, False)
                new_text = json.dumps(kept_items, ensure_ascii=False, indent=2)
                return ({**s, "dataset_id": dataset_id, "text": new_text, "text_sha256": text_hash(new_text)}, True)

            if url == f"https://api.github.com/repos/{repo}":
                try:
                    dt = _instant(json.loads(s["text"]).get("created_at"))
                except (ValueError, TypeError):
                    dt = None
                return ({**s, "dataset_id": dataset_id}, False) if (dt and dt <= cutoff_dt) else (None, False)

            return (None, False)

        return (None, False)

    kept_sources: dict[str, dict] = {}
    modified_source_ids: set[str] = set()
    for s in base_pkg["sources"]:
        sliced, modified = slice_source(s)
        if sliced is not None:
            kept_sources[s["source_id"]] = sliced
            if modified:
                modified_source_ids.add(s["source_id"])

    kept_commits = set()
    kept_entities = []
    temp_ents = {}
    deferred_developers = []
    for e in base_pkg["entities"]:
        etype = e["type"]
        props = e.get("properties") or {}
        if etype == "Project":
            temp_ents[e["id"]] = e
        elif etype == "Developer":
            deferred_developers.append(e)
        elif etype == "Release":
            tag = props.get("tag") or e["key"]
            dt = release_date.get(tag)
            if dt and dt <= cutoff_dt:
                temp_ents[e["id"]] = e
        elif etype in {"Issue", "PullRequest"}:
            dt = _instant(props.get("created_at"))
            if dt and dt <= cutoff_dt:
                temp_ents[e["id"]] = e
        elif etype == "Commit":
            dt = _instant(props.get("committed_at"))
            if dt and dt <= cutoff_dt:
                temp_ents[e["id"]] = e
                kept_commits.add(props.get("sha") or e["key"])

    for e in base_pkg["entities"]:
        if e["type"] in {"File", "Function"}:
            if e["properties"].get("commit_sha") in kept_commits:
                temp_ents[e["id"]] = e

    for e in base_pkg["entities"]:
        if e["type"] == "Decision":
            p = e["properties"]
            if p.get("subject_id") not in temp_ents:
                continue
            st_evs = [ev_by_id[eid] for eid in p.get("statement_evidence_ids", []) if eid in ev_by_id]
            if st_evs and all(ev["source_id"] in kept_sources for ev in st_evs):
                temp_ents[e["id"]] = e

    # Keep only Developers active in kept relations or kept evidence.
    active_dev_ids = {
        r["from_id"]
        for r in base_pkg["relations"]
        if r["from_id"].startswith("Developer:")
        and r["to_id"] in temp_ents
        and (not r.get("occurred_at") or ((dt := _instant(r["occurred_at"])) and dt <= cutoff_dt))
    }
    for e in deferred_developers:
        has_kept_ev = any(
            (ev := ev_by_id.get(eid)) and ev["source_id"] in kept_sources
            for eid in e.get("evidence_ids", [])
        )
        if e["id"] in active_dev_ids or has_kept_ev:
            temp_ents[e["id"]] = e

    kept_entity_ids = set(temp_ents)

    kept_relations = []
    for r in base_pkg["relations"]:
        occ_raw = r.get("occurred_at")
        if occ_raw:
            occ_dt = _instant(occ_raw)
            if not occ_dt or occ_dt > cutoff_dt:
                continue
        if r["from_id"] in kept_entity_ids and (
            r["to_id"] in kept_entity_ids or r["to_id"] in kept_sources
        ):
            ev_ids = r.get("evidence_ids", [])
            if ev_ids and not any(
                (ev := ev_by_id.get(eid)) and ev["source_id"] in kept_sources for eid in ev_ids
            ):
                continue
            kept_relations.append({**r, "dataset_id": dataset_id})

    needed_ev_ids = set()
    for e in temp_ents.values():
        needed_ev_ids.update(e.get("evidence_ids", []))
        if e["type"] == "Decision":
            needed_ev_ids.update(e["properties"].get("statement_evidence_ids", []))
            needed_ev_ids.update(e["properties"].get("rationale_evidence_ids", []))
    for r in kept_relations:
        needed_ev_ids.update(r.get("evidence_ids", []))

    kept_evidence = []
    for eid in sorted(needed_ev_ids):
        ev = ev_by_id.get(eid)
        if not ev or ev["source_id"] not in kept_sources:
            continue
        sid = ev["source_id"]
        if sid in modified_source_ids:
            sliced_text = kept_sources[sid]["text"]
            orig_len = len(src_by_id[sid]["text"])
            if ev.get("start") == 0 and ev.get("end") == orig_len:
                kept_evidence.append(
                    {
                        **ev,
                        "dataset_id": dataset_id,
                        "start": 0,
                        "end": len(sliced_text),
                        "quote": sliced_text,
                    }
                )
            continue
        kept_evidence.append({**ev, "dataset_id": dataset_id})

    valid_ev_ids = {e["evidence_id"] for e in kept_evidence}
    for e in temp_ents.values():
        ev_filtered = [eid for eid in e.get("evidence_ids", []) if eid in valid_ev_ids]
        if e["type"] == "Decision":
            props = {
                **e["properties"],
                "statement_evidence_ids": [
                    eid for eid in e["properties"].get("statement_evidence_ids", []) if eid in valid_ev_ids
                ],
                "rationale_evidence_ids": [
                    eid for eid in e["properties"].get("rationale_evidence_ids", []) if eid in valid_ev_ids
                ],
            }
            kept_entities.append({**e, "dataset_id": dataset_id, "properties": props, "evidence_ids": ev_filtered})
        else:
            kept_entities.append({**e, "dataset_id": dataset_id, "evidence_ids": ev_filtered})
    final_relations = [
        {**r, "evidence_ids": [eid for eid in r.get("evidence_ids", []) if eid in valid_ev_ids]}
        for r in kept_relations
    ]

    kept_dm_keys = {
        (int(dm["number"]), dm["source_type"], str(dm["source_id"]))
        for s in kept_sources.values()
        if (dm := discussion_mapping(s))
    }
    sliced_payloads = []
    for p in base_payloads:
        num = int(p["number"])
        if (num, "body", str(num)) not in kept_dm_keys:
            continue
        sliced_payloads.append(
            {
                **p,
                "issue_comments": [
                    c for c in p.get("issue_comments", [])
                    if (num, "issue_comment", str(c["id"])) in kept_dm_keys
                ],
                "reviews": [
                    r for r in p.get("reviews", [])
                    if (num, "review", str(r["id"])) in kept_dm_keys
                ],
                "review_comments": [
                    rc for rc in p.get("review_comments", [])
                    if (num, "review_comment", str(rc["id"])) in kept_dm_keys
                ],
            }
        )
    write_json(
        exports_dir / "discussion_input.json",
        {"version": INDEX_VERSION, "dataset_id": dataset_id, "payloads": sliced_payloads},
    )

    sorted_sources = sorted(kept_sources.values(), key=lambda r: r["source_id"])
    kept_entities.sort(key=lambda r: r["id"])
    kept_evidence.sort(key=lambda r: r["evidence_id"])
    final_relations.sort(key=lambda r: r["id"])
    pkg = {
        "manifest": {**base_pkg["manifest"], "dataset_id": dataset_id},
        "subjects": [dict(s) for s in base_pkg["subjects"]],
        "sources": sorted_sources,
        "entities": kept_entities,
        "evidence": kept_evidence,
        "relations": final_relations,
        "dataset_dir": str(ds_dir),
    }
    pkg["fingerprint"] = fingerprint(pkg)
    return pkg


def run_incremental(neo4j_uri: str = "bolt://127.0.0.1:17691") -> dict:
    base_pkg = read_package(FROZEN_DS)
    base_payloads = read_json(FROZEN_DS / "exports/discussion_input.json")["payloads"]
    WORK_TMP.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{(WORK_TMP / 'inc_discussion.sqlite3').as_posix()}"
    collector.initialize_database(db_url)
    cfg = {"graph": {"neo4j_uri": neo4j_uri}, "database_url": db_url}

    ds_inc = "inc_evolving_v7_test"
    ds_full = "inc_full_t3_verify"

    pkg_t1 = slice_package(base_pkg, base_payloads, ds_inc, CUTOFF_T1, WORK_TMP / "t1")
    pkg_t2 = slice_package(base_pkg, base_payloads, ds_inc, CUTOFF_T2, WORK_TMP / "t2")
    pkg_t3 = slice_package(base_pkg, base_payloads, ds_inc, None, WORK_TMP / "t3")
    pkg_full_t3 = slice_package(base_pkg, base_payloads, ds_full, None, WORK_TMP / "full_t3")

    created_indexes = []
    stages = {}
    evolution_probe = {}

    try:
        # 1. Load T1 initial
        pkg_t1["retrieval_index"] = freeze_index(pkg_t1, db_url)
        created_indexes.append(pkg_t1["retrieval_index"])
        t0 = time.perf_counter()
        with GraphStore(cfg) as store:
            store.write(pkg_t1)
        t1_write_ms = round((time.perf_counter() - t0) * 1000, 2)
        stages["T1_initial"] = {
            "cutoff": CUTOFF_T1,
            "sources": len(pkg_t1["sources"]),
            "entities": len(pkg_t1["entities"]),
            "relations": len(pkg_t1["relations"]),
            "write_ms": t1_write_ms,
        }
        evolution_probe["T1"] = _probe_queries(ds_inc, cfg)

        # 2. Evolve T1 -> T2 via apply_delta
        pkg_t2["retrieval_index"] = freeze_index(pkg_t2, db_url)
        created_indexes.append(pkg_t2["retrieval_index"])
        t0 = time.perf_counter()
        with GraphStore(cfg) as store:
            delta_12 = store.apply_delta(ds_inc, pkg_t1, pkg_t2)
        t2_delta_ms = round((time.perf_counter() - t0) * 1000, 2)
        stages["T2_delta"] = {
            "cutoff": CUTOFF_T2,
            "sources": len(pkg_t2["sources"]),
            "entities": len(pkg_t2["entities"]),
            "relations": len(pkg_t2["relations"]),
            "delta_ms": t2_delta_ms,
            **delta_12,
        }
        evolution_probe["T2"] = _probe_queries(ds_inc, cfg)

        # 3. Evolve T2 -> T3 via apply_delta
        pkg_t3["retrieval_index"] = freeze_index(pkg_t3, db_url)
        created_indexes.append(pkg_t3["retrieval_index"])
        t0 = time.perf_counter()
        with GraphStore(cfg) as store:
            delta_23 = store.apply_delta(ds_inc, pkg_t2, pkg_t3)
        t3_delta_ms = round((time.perf_counter() - t0) * 1000, 2)
        with GraphStore(cfg) as store:
            evolved_snap = store.snapshot(ds_inc)

        # 4. Compare against fresh full T3 rebuild
        pkg_full_t3["retrieval_index"] = freeze_index(pkg_full_t3, db_url)
        created_indexes.append(pkg_full_t3["retrieval_index"])
        t0 = time.perf_counter()
        with GraphStore(cfg) as store:
            store.write(pkg_full_t3)
        full_write_ms = round((time.perf_counter() - t0) * 1000, 2)
        with GraphStore(cfg) as store:
            full_snap = store.snapshot(ds_full)

        equivalence = {
            "fingerprint_equal": evolved_snap["fingerprint"] == pkg_t3["fingerprint"],
            "entity_count_equal": len(evolved_snap["entities"]) == len(full_snap["entities"]),
            "relation_count_equal": len(evolved_snap["relations"]) == len(full_snap["relations"]),
            "source_count_equal": len(evolved_snap["sources"]) == len(full_snap["sources"]),
            "evidence_count_equal": len(evolved_snap["evidence"]) == len(full_snap["evidence"]),
        }
        stages["T3_delta"] = {
            "cutoff": "2026-11-16T06:31:18Z",
            "sources": len(pkg_t3["sources"]),
            "entities": len(pkg_t3["entities"]),
            "relations": len(pkg_t3["relations"]),
            "delta_ms": t3_delta_ms,
            "full_rebuild_ms": full_write_ms,
            "speedup_vs_full_rebuild": round(full_write_ms / t3_delta_ms, 2) if t3_delta_ms else None,
            **delta_23,
            "equivalence": equivalence,
        }
        evolution_probe["T3"] = _probe_queries(ds_inc, cfg)
    finally:
        with GraphStore(cfg) as store:
            for idx_desc in created_indexes:
                drop_index(db_url, idx_desc)
            store.delete_dataset(ds_inc)
            store.delete_dataset(ds_full)

    summary = {"stages": stages, "evolution_queries": evolution_probe}
    write_json(OUT_DIR / "incremental-summary.json", summary)
    print(json.dumps({"stages": stages, "probe": evolution_probe}, ensure_ascii=False, indent=2))
    return summary


def _probe_queries(dataset_id: str, cfg: dict) -> dict:
    out = {}
    for key, q, kind in EVOLUTION_QUERIES:
        prep = prepare_query(
            {"dataset_id": dataset_id, "question": q, "kind": kind},
            config={**cfg, "system": "B", "query_mode": "cypher_subgraph"},
        )
        urls = [c["url"].split("pallets/itsdangerous")[-1] or "/" for c in prep["candidates"][:8]]
        out[key] = {
            "search_intent": prep["search_intent"],
            "paths": len(prep["paths"]),
            "candidates": len(prep["candidates"]),
            "top_urls": urls,
            "has_pr152": any("/pull/152" in u or "/pulls/152" in u for u in urls),
            "has_220_release": any(
                "2.2.0" in c["quote"] and "published_at" in c["quote"]
                for c in prep["candidates"][:3]
            ),
            "has_pr372": any("/pull/372" in u or "/pulls/372" in u for u in urls),
        }
    return out


if __name__ == "__main__":
    run_incremental(os.environ.get("P2_TEST_NEO4J_URI", "bolt://127.0.0.1:17691"))
