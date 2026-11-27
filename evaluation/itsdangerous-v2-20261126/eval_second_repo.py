"""Zero-code-change second-repository generalization evaluation on pallets-eco/blinker."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))
from budget_guard import budget_config, spend_summary
from eval_qa_v2 import judge_answer, verify_citations

from historykg import collector
from historykg.contracts import BuildRequest_v1
from historykg.graph.store import read_package
from historykg.ingest.github import FULL_HISTORY
from historykg.io import read_json, read_jsonl, validate_dataset, write_json
from historykg.llm.gateway import digest
from historykg.pipeline import get_build, start_build
from historykg.query import query

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
LOCAL_BLINKER = ROOT / ".local/itsdangerous-v2-20261126/blinker_run"
ANSWER_ROUTE = "bailian/deepseek-v4.1-flash-1017"
REPO_URL = "https://github.com/pallets-eco/blinker"


def load_github_token() -> None:
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        return
    gh_bin = shutil.which("gh") or str(Path.home() / ".local/bin/gh")
    token = subprocess.check_output([gh_bin, "auth", "token"], text=True).strip()
    if not token:
        raise RuntimeError("Missing GitHub CLI token for GraphQL Closes verification")
    os.environ["GITHUB_TOKEN"] = token


def wait_job(job_id: str, cfg: dict, timeout: float = 900.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = get_build(job_id, config=cfg)
        if job["status"] in {"ready", "partial", "failed", "blocked", "unsupported"}:
            return job
        time.sleep(2.0)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")


def main():
    load_github_token()
    LOCAL_BLINKER.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{(LOCAL_BLINKER / 'blinker_discussion.sqlite3').as_posix()}"
    collector.initialize_database(db_url)
    neo4j_uri = os.environ.get("P2_TEST_NEO4J_URI", "bolt://127.0.0.1:17691")

    base_cfg = {
        "jobs_root": str(LOCAL_BLINKER / "jobs"),
        "data_root": str(LOCAL_BLINKER / "datasets"),
        "database_url": db_url,
        "graph": {"neo4j_uri": neo4j_uri},
    }

    # Check if an earlier ready job already exists under LOCAL_BLINKER/jobs
    existing_jobs = sorted((LOCAL_BLINKER / "jobs").glob("*/job.json"))
    ready_job = None
    for jp in existing_jobs:
        j = read_json(jp)
        if j["status"] in {"ready", "partial"} and j.get("dataset_id"):
            ready_job = j
            break

    if ready_job is None:
        # Full zero-code-change production pipeline run: discover -> collect -> code -> extract(v2) -> validate -> index_graph
        full_cfg = {
            **base_cfg,
            "model": {
                "route": ANSWER_ROUTE,
                "model_id": "deepseek-flash",
                "thinking": "disabled",
                "prompt_version": "v2",
                "max_output_tokens": 4096,
                "max_retries": 2,
                "timeout_seconds": 90,
                "output_root": str(LOCAL_BLINKER / "llm"),
            },
            "budget": {**budget_config(), "max_cost_cny": 15.0},
        }
        job = start_build(
            BuildRequest_v1(repo_url=REPO_URL, profile=FULL_HISTORY),
            config=full_cfg,
            background=False,
        )
        assert job["status"] in {"ready", "partial"} and job.get("dataset_id"), job
        ready_job = job

    ds_dir = Path(ready_job["artifacts"]["dataset_dir"])
    dataset_id = ready_job["dataset_id"]
    val = validate_dataset(ds_dir)
    assert val["status"] == "ok", val
    pkg = read_package(ds_dir)

    from collections import Counter

    ent_counts = Counter(e["type"] for e in pkg["entities"])
    rel_counts = Counter(r["type"] for r in pkg["relations"])
    print("Blinker counts:", dict(ent_counts), dict(rel_counts), flush=True)
    assert rel_counts.get("Closes", 0) > 0, f"Expected GraphQL Closes > 0 on blinker, got {rel_counts}"

    # Inspect real facts directly from blinker package to build 6 verifiable test questions
    ents = {e["id"]: e for e in pkg["entities"]}
    rels = [e for e in pkg["entities"] if e["type"] == "Release" and e["properties"].get("published_at")]
    rels.sort(key=lambda e: e["properties"]["published_at"])
    target_rel = rels[-1]["properties"]

    closes_edges = [r for r in pkg["relations"] if r["type"] == "Closes"]
    merged_edges = {r["from_id"]: r for r in pkg["relations"] if r["type"] == "MergedAs"}
    touches_by_commit = {}
    for r in pkg["relations"]:
        if r["type"] == "Touches":
            touches_by_commit.setdefault(r["from_id"], []).append(ents[r["to_id"]]["properties"]["path"])

    sample_chain = None
    commit_ent_id = None
    for ce in closes_edges:
        pr_ent = ents[ce["from_id"]]
        iss_ent = ents[ce["to_id"]]
        me = merged_edges.get(pr_ent["id"])
        if me and touches_by_commit.get(me["to_id"]):
            commit_ent_id = me["to_id"]
            sample_chain = (
                iss_ent["properties"]["number"],
                pr_ent["properties"]["number"],
                ents[commit_ent_id]["properties"]["sha"],
                sorted(touches_by_commit[commit_ent_id]),
                pr_ent["properties"].get("title", ""),
            )
            break
    if sample_chain is None and merged_edges:
        pr_id, me = next(iter(merged_edges.items()))
        pr_ent = ents[pr_id]
        commit_ent_id = me["to_id"]
        sample_chain = (
            None,
            pr_ent["properties"]["number"],
            ents[commit_ent_id]["properties"]["sha"],
            sorted(touches_by_commit.get(commit_ent_id, [])),
            pr_ent["properties"].get("title", ""),
        )
    reachable_tags = (
        sorted(
            ents[r["to_id"]]["properties"]["tag"]
            for r in pkg["relations"]
            if r["type"] == "ReachableIn"
            and r["from_id"] == commit_ent_id
            and r["to_id"] in ents
            and ents[r["to_id"]]["type"] == "Release"
        )
        if commit_ent_id
        else []
    )

    # Find a code file and AST function on default branch
    code_sources = [s for s in pkg["sources"] if s["kind"] == "code" and "src/blinker/base.py" in s["origin_key"]]
    code_target = code_sources[0] if code_sources else next(s for s in pkg["sources"] if s["kind"] == "code")
    func_ents = [e for e in pkg["entities"] if e["type"] == "Function" and e["properties"].get("path", "").endswith("base.py")]
    sample_dec = next((e for e in pkg["entities"] if e["type"] == "Decision"), None)
    dec_subj = ents[sample_dec["properties"]["subject_id"]] if sample_dec else None

    iss_n, pr_n, sha_full, touched_files, pr_title = sample_chain
    questions = [
        {
            "id": "BL1",
            "category": "release_date",
            "question": f"{target_rel['tag']} 是哪天在 GitHub 正式发布的？请给出 UTC 时间和出处。",
            "rubric": [
                f"给出 {target_rel['tag']} 精确 UTC 发布时间 {target_rel['published_at']}",
                "附上官方 GitHub Release 出处",
            ],
            "reference": target_rel,
        },
        {
            "id": "BL2",
            "category": "closes_merge_change",
            "question": (
                f"Issue #{iss_n} 是由哪个 PR 关闭的？该 PR 的合并提交 SHA 是什么，改了哪些文件？请附出处。"
                if iss_n
                else f"PR #{pr_n} 的合并提交 SHA 是什么，改了哪些文件？请附出处。"
            ),
            "rubric": [
                *( [f"指明 Issue #{iss_n} 由 PR #{pr_n} 关闭"] if iss_n else [f"指明 PR #{pr_n} 状态与标题"] ),
                f"给出合并提交 SHA {sha_full[:12]}（完整或前12位）",
                f"准确说出修改文件（含 {touched_files[0]}）及对应出处",
            ],
            "reference": {
                "issue": iss_n,
                "pr": pr_n,
                "sha": sha_full,
                "files": touched_files,
                "title": pr_title,
            },
        },
        {
            "id": "BL3",
            "category": "pr_release_membership",
            "question": f"PR #{pr_n} 改了什么？是否包含在已冻结的最新正式版 {target_rel['tag']} 中？请给出核对出处。",
            "rubric": [
                f"说明 PR #{pr_n} 的改动内容与合并提交 {sha_full[:12]}",
                f"基于标签历史准确核对它与 {target_rel['tag']} 的包含关系并附出处",
            ],
            "reference": {
                "pr": pr_n,
                "sha": sha_full,
                "latest_release": target_rel["tag"],
                "reachable_releases": reachable_tags,
                "in_latest_release": target_rel["tag"] in reachable_tags,
                "title": pr_title,
            },
        },
        {
            "id": "BL4",
            "category": "code_behavior",
            "question": "在冻结版本的 src/blinker/base.py 中，Signal.send 和 Signal.connect 分别做了什么？请附源码出处。",
            "rubric": [
                "说明 Signal.connect 将接收器与发送者绑定/弱引用注册进信号状态",
                "说明 Signal.send 触发并返回匹配的接收器响应结果并附源码出处",
            ],
            "reference": {"file": "src/blinker/base.py", "url": code_target["url"]},
        },
        {
            "id": "BL5",
            "category": "decision_or_pr_rationale",
            "question": (
                f"关于 {dec_subj['properties'].get('title') or dec_subj['key']}，仓库记录了什么维护决定及原因？请附出处。"
                if sample_dec and dec_subj
                else f"PR #{pr_n} 为什么要做这个改动？请给出讨论原文和出处。"
            ),
            "rubric": [
                "准确陈述该讨论涉及的维护决定或变更状态",
                "给出原文依据出处，若未明示理由则如实说明",
            ],
            "reference": (
                sample_dec["properties"] if sample_dec else {"pr": pr_n, "title": pr_title}
            ),
        },
        {
            "id": "BL6",
            "category": "false_premise_abstention",
            "question": "为什么 blinker 在 2.0 中移除了 Signal 类并改为集成 GraphQL 客户端？请给出对应 PR 和提交。",
            "rubric": [
                "拒绝编造不存在的移除 Signal 或集成 GraphQL 客户端事件与 PR",
                "基于冻结范围指出记录中查不到相关提交/决定并如实拒答",
            ],
            "reference": {"premise_status": "false_premise", "expected": "abstain cleanly without fabricating PR/SHA"},
        },
    ]

    # Answer config matching updated itsdangerous.example.json
    example_ans = read_json(ROOT / "demo/final/itsdangerous.example.json")["answer"]
    q_cfg = {
        "database_url": db_url,
        "graph": {"neo4j_uri": neo4j_uri},
        "answer": example_ans,
        "budget": budget_config(),
        "answer_output_root": str(LOCAL_BLINKER / "qa_answers"),
        "query_output_root": str(LOCAL_BLINKER / "qa_queries"),
    }
    sources_by_id = {s["source_id"]: s for s in pkg["sources"]}

    arm_summaries = {}
    for arm_name, sys_mode in (("A_v2", "A"), ("B_v2_fast", "B")):
        rows = []
        for item in questions:
            rec_path = LOCAL_BLINKER / "qa_records" / f"{arm_name}-{item['id']}.json"
            if rec_path.exists():
                rec = read_json(rec_path)
            else:
                t0 = time.perf_counter()
                res = query(
                    {"dataset_id": dataset_id, "question": item["question"], "kind": "search"},
                    config={**q_cfg, "system": sys_mode, "query_mode": "cypher_subgraph"},
                )
                elapsed = round(time.perf_counter() - t0, 3)
                rec = res.model_dump(mode="json")
                rec["seconds"] = elapsed
                write_json(rec_path, rec)
            cit = verify_citations(sources_by_id, rec)
            assert cit["all_valid"], f"Invalid quote in blinker {arm_name} {item['id']}"
            jd = judge_answer(
                f"blinker-{arm_name}-{item['id']}",
                item["question"],
                item["rubric"],
                item["reference"],
                rec,
            )
            rows.append(
                {
                    "id": item["id"],
                    "category": item["category"],
                    "status": rec["status"],
                    "seconds": rec["seconds"],
                    "paths": len(rec.get("paths", [])),
                    "citations": cit["total"],
                    **jd,
                }
            )
            print(f"Blinker {arm_name} {item['id']}: {jd['score']}/{jd['max']} in {rec['seconds']}s", flush=True)
        tot_s = sum(r["score"] for r in rows)
        tot_m = sum(r["max"] for r in rows)
        arm_summaries[arm_name] = {
            "score": tot_s,
            "max": tot_m,
            "accuracy": round(tot_s / tot_m, 4),
            "median_seconds": round(median(r["seconds"] for r in rows), 2),
            "total_citations": sum(r["citations"] for r in rows),
            "per_question": rows,
        }

    out = {
        "repo": "pallets-eco/blinker",
        "dataset_id": dataset_id,
        "validation_status": val["status"],
        "entity_counts": dict(ent_counts),
        "relation_counts": dict(rel_counts),
        "closes_edges": rel_counts.get("Closes", 0),
        "claims_to_close_edges": rel_counts.get("ClaimsToClose", 0),
        "qa_results": arm_summaries,
        "spend": spend_summary(),
    }
    write_json(OUT_DIR / "blinker-generalization.json", out)
    print("BLINKER_SUMMARY:", json.dumps({
        "closes": out["closes_edges"],
        "entities": out["entity_counts"],
        "qa": {k: (v["score"], v["max"], v["median_seconds"]) for k, v in arm_summaries.items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
