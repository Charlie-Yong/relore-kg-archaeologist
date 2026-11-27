"""Evaluate QA latency-accuracy Pareto frontier, Codex E audit, and sealed unseen 8-question test."""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from budget_guard import budget_config, record_external_call, spend_summary

from historykg.io import read_json, read_jsonl, write_json
from historykg.llm.gateway import bailian_connection, digest
from historykg.query import query

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
FINAL_DIR = ROOT / "evaluation/itsdangerous-final-20261121"
FROZEN_DS = (
    ROOT
    / ".local/full-history-itsdangerous/datasets"
    / "dataset-0c94c5af1f7f64c628c4a7fe05b496647ad8ef760e18eee01287fd43f1ea3ef2"
)
LOCAL_QA = ROOT / ".local/itsdangerous-v2-20261126/qa_v2"
REPLAY_BACKUP = ROOT / ".local/itsdangerous-v2-20261126/itsdangerous-replay-v6-backup.json"
REG_CFG_PATH = Path("/tmp/historykg-v7-itsdangerous/regression.json")

DATASET_ID = "dataset:0c94c5af1f7f64c628c4a7fe05b496647ad8ef760e18eee01287fd43f1ea3ef2"
JUDGE_MODEL = "bailian/glm-5.3"
ANSWER_ROUTE = "bailian/deepseek-v4.1-flash-1017"

UNSEEN_QUESTIONS = [
    {
        "id": "U1",
        "category": "decision_rationale",
        "question": "Issue #145 中有人建议更换默认的 SHA1 摘要算法，维护者为何决定保持现状而不直接切换？请给出原文理由与出处。",
        "rubric": [
            "说明维护者拒绝立即切换默认算法并保持 SHA1 默认行为",
            "给出核心技术理由：SHA1 仅作为 HMAC 的中间步骤，不直接受碰撞攻击影响",
            "给出历史兼容性理由：此前修改默认算法曾导致已有 token 全部失效并引发大量升级问题",
            "附上 Issue #145 与维护者回复的对应原文出处",
        ],
        "reference": {
            "issue": "https://github.com/pallets/itsdangerous/issues/145",
            "maintainer_decision": "保持 SHA1 作为默认摘要算法，不直接切换默认算法",
            "reasons": [
                "SHA1 仅作为 HMAC 的中间步骤（intermediate step），即使 MD5 在当前讨论攻击下也非漏洞场景",
                "过去曾修改过默认算法，结果使所有已有 token 失效并造成严重的升级兼容性问题（另有 fallback 迁移机制）",
            ],
            "sources": [
                "https://github.com/pallets/itsdangerous/issues/145#issuecomment-572582943",
                "https://github.com/pallets/itsdangerous/issues/145#issuecomment-572583453",
            ],
        },
    },
    {
        "id": "U2",
        "category": "decision_rejected",
        "question": "Issue #224 提出的加密载荷存储需求为什么被维护者拒绝？如果用户确实需要该能力，维护者建议如何实现？请附出处。",
        "rubric": [
            "准确说明该需求因超出项目范围（out of scope）而被拒绝",
            "指出维护者建议用户在需要时自行继承/子类化 Signer 实现",
            "附上 Issue #224 与维护者评论原文出处",
        ],
        "reference": {
            "issue": "https://github.com/pallets/itsdangerous/issues/224",
            "decision": "rejected / out of scope（超出 itsdangerous 范围）",
            "workaround": "如果用户需要，可以继承（subclass）Signer 自行扩展实现",
            "source": "https://github.com/pallets/itsdangerous/issues/224#issuecomment-804883135",
        },
    },
    {
        "id": "U3",
        "category": "pr_change_trace",
        "question": "PR #377 做了什么改动？它的合并提交 SHA 是什么，实际修改了哪些文件？请附官方记录出处。",
        "rubric": [
            "给出 PR #377 的目标与改动说明（Generic serializer / 泛型支持）",
            "给出精确合并提交 SHA 135eb234ed4a07520779ffb679407b7d27c8ffe6 与出处",
            "列出实际修改的两个文件 src/itsdangerous/serializer.py 和 src/itsdangerous/timed.py",
        ],
        "reference": {
            "pr": "https://github.com/pallets/itsdangerous/pull/377",
            "merged_sha": "135eb234ed4a07520779ffb679407b7d27c8ffe6",
            "merged_at": "2024-04-16T16:48:22Z",
            "files": ["src/itsdangerous/serializer.py", "src/itsdangerous/timed.py"],
        },
    },
    {
        "id": "U4",
        "category": "pr_change_trace",
        "question": "PR #405 做了什么调整？它的合并提交 SHA 和实际修改的文件分别是什么？请附出处。",
        "rubric": [
            "说明 PR #405 移除了已结束生命周期（EOL）的 Python 版本支持",
            "给出精确合并提交 SHA 4dffa1963f896a0a311dec3c14f003a5f382c446 与出处",
            "列出实际修改的文件 src/itsdangerous/serializer.py 和 tests/test_itsdangerous/test_serializer.py",
        ],
        "reference": {
            "pr": "https://github.com/pallets/itsdangerous/pull/405",
            "merged_sha": "4dffa1963f896a0a311dec3c14f003a5f382c446",
            "merged_at": "2025-05-28T20:57:10Z",
            "files": [
                "src/itsdangerous/serializer.py",
                "tests/test_itsdangerous/test_serializer.py",
            ],
        },
    },
    {
        "id": "U5",
        "category": "release_date",
        "question": "2.2.0 正式版在 GitHub 是哪天发布的？请给出 UTC 发布日期和官方 Release 出处。",
        "rubric": [
            "给出精确 UTC 发布时间 2024-04-16T21:46:38Z（或 2024-04-16）",
            "附上官方 GitHub Release 出处（releases API 或 tag/2.2.0 链接）",
        ],
        "reference": {
            "tag": "2.2.0",
            "published_at": "2024-04-16T21:46:38Z",
            "source": "https://github.com/pallets/itsdangerous/releases/tag/2.2.0",
        },
    },
    {
        "id": "U6",
        "category": "release_membership",
        "question": "PR #373 最早进入哪个正式 GitHub Release？请说明其合并提交、版本标签核查结果与出处。",
        "rubric": [
            "给出 PR #373 精确合并提交 SHA bc88e945d31c407e16c3f4e1c713c12dd598e58d",
            "基于发布清单与标签历史核查指出：2.1.2 及更早正式版不包含，最早正式 GitHub Release 为 2.2.0（2.1.x 为分支标签非正式 Release）",
            "附上合并记录、tags/compare 与 releases 清单出处",
        ],
        "reference": {
            "pr": "https://github.com/pallets/itsdangerous/pull/373",
            "merged_sha": "bc88e945d31c407e16c3f4e1c713c12dd598e58d",
            "first_official_release": "2.2.0",
            "note": "2.1.x 存在标签但非正式 GitHub Release；2.1.2 及之前正式 Release 均不包含",
        },
    },
    {
        "id": "U7",
        "category": "code_behavior",
        "question": "在冻结版本的 src/itsdangerous/timed.py 中，TimedSerializer.loads 是如何结合 max_age 和 return_timestamp 进行校验与返回的？请附源码出处。",
        "rubric": [
            "说明 TimedSerializer.loads 先调用父类/签名器的 unsign(..., max_age=max_age, return_timestamp=True) 获取载荷字节与时间戳，再调用 load_payload 反序列化",
            "说明当 return_timestamp=True 时返回 (data, timestamp) 二元组，否则仅返回 data，并附上 timed.py 源码出处",
        ],
        "reference": {
            "file": "src/itsdangerous/timed.py",
            "behavior": "TimedSerializer.loads calls make_signer(salt).unsign(s, max_age=max_age, return_timestamp=True), decodes payload with self.load_payload(base64d), and returns (data, timestamp) when return_timestamp is True else data.",
            "source": "https://github.com/pallets/itsdangerous/blob/672971d66a2ef9f85151e53283113f33d642dabd/src/itsdangerous/timed.py",
        },
    },
    {
        "id": "U8",
        "category": "false_premise_abstention",
        "question": "为什么 itsdangerous 在 2.2.0 中内置了 encrypted_payload 加密载荷模块并在 Serializer 中默认启用？请给出对应的 PR 和合并提交。",
        "rubric": [
            "明确拒绝回答不存在的“内置 encrypted_payload 模块及 PR/合并提交”前提，不编造 PR 编号或 SHA",
            "基于冻结数据说明未找到 encrypted_payload 相关记录（或引用 Issue #224 表明加密功能属于 out of scope），结论限至冻结范围",
        ],
        "reference": {
            "premise_status": "false_premise / unrecorded",
            "expected": "Refuse to fabricate an encrypted_payload module or PR/merge SHA; report gap or note Issue #224 out-of-scope rejection.",
        },
    },
]


def load_base_config() -> dict:
    cfg = read_json(REG_CFG_PATH)
    cfg = {k: v for k, v in cfg.items() if k != "dataset_dir"}
    cfg["answer_output_root"] = str(LOCAL_QA / "answers")
    cfg["query_output_root"] = str(LOCAL_QA / "queries")
    cfg["budget"] = budget_config()
    return cfg


def verify_citations(sources_by_id: dict[str, dict], result_dict: dict) -> dict:
    total, valid = 0, 0
    for ev in result_dict.get("evidence", []):
        total += 1
        src = sources_by_id.get(ev["source_id"])
        if src and src["text"][ev["start"] : ev["end"]] == ev["quote"]:
            valid += 1
    return {"total": total, "valid": valid, "all_valid": total == valid}


def run_arm_query(tag: str, qid: str, question: str, *, system: str, answer_cfg: dict, cfg: dict) -> dict:
    LOCAL_QA.mkdir(parents=True, exist_ok=True)
    rec_path = LOCAL_QA / "records" / f"{tag}-{qid}.json"
    if rec_path.exists():
        return read_json(rec_path)
    full_cfg = {**cfg, "system": system, "query_mode": "cypher_subgraph", "answer": answer_cfg}
    t0 = time.perf_counter()
    res = query({"dataset_id": DATASET_ID, "question": question, "kind": "search"}, config=full_cfg)
    elapsed = round(time.perf_counter() - t0, 3)
    dumped = res.model_dump(mode="json")
    dumped["seconds"] = elapsed
    dumped["arm"] = tag
    dumped["qid"] = qid
    write_json(rec_path, dumped)
    return dumped


def format_answer_for_judge(record: dict) -> dict | str:
    refs = {e["evidence_id"]: e for e in record.get("evidence", [])}
    claims = [
        {
            "text": c["text"],
            "sources": [
                {k: refs[i][k] for k in ("quote", "url", "context_note", "detail_url") if k in refs.get(i, {})}
                for i in c.get("evidence_ids", [])
            ],
        }
        for c in record.get("claims", [])
    ]
    if record.get("status") not in ("ok", "empty"):
        return "未交付答案"
    return {"claims": claims, "gaps": (record.get("gaps") or [])[-5:]}


def judge_answer(cache_key: str, question: str, rubric: list[str], reference: dict | str, record: dict) -> dict:
    dest = LOCAL_QA / "scores" / f"{cache_key}.json"
    if dest.exists():
        return read_json(dest)
    payload = {
        "question": question,
        "rubric": rubric,
        "reference": reference,
        "answer": format_answer_for_judge(record),
    }
    system = (
        "按评分项顺序严格核查答案。"
        "只给实际说出且有对应出处支持的事实计 1 分；部分事实或出处略缺给 0.5 分；"
        "错误、遗漏、只说'需要核对'或编造给 0 分。"
        "若题目属于假前提/库中不存在的事件，拒绝编造并准确说明范围缺口得满分，编造则得 0 分。"
        '只返回合法单行 JSON 对象：{"points":[0或0.5或1,...],"note":"不超过60字单行短评"}，note 严禁换行或使用未转义英文双引号。'
    )
    endpoint, headers = bailian_connection()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    for attempt in range(1, 5):
        try:
            resp = httpx.post(
                endpoint,
                headers=headers,
                trust_env=False,
                timeout=120,
                json={
                    "model": JUDGE_MODEL,
                    "temperature": 0,
                    "max_tokens": 8192,
                    "thinking": {"type": "disabled"},
                    "enable_thinking": False,
                    "reasoning_effort": "none",
                    "response_format": {"type": "json_object"},
                    "messages": messages,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            usage = body.get("usage") or {}
            record_external_call(f"qa-judge-{cache_key}-a{attempt}", "qa_judge", JUDGE_MODEL, usage)
            choice = body["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError(f"incomplete_finish_reason_{choice.get('finish_reason')}")
            content = (choice["message"].get("content") or "").strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)
            pts = parsed["points"]
            if len(pts) != len(rubric) or any(x not in (0, 0.5, 1) for x in pts):
                raise ValueError(f"Bad rubric points: {pts}")
            out = {"points": pts, "score": sum(pts), "max": len(rubric), "note": str(parsed.get("note", ""))[:200]}
            write_json(dest, out)
            return out
        except Exception as exc:
            if attempt == 4:
                raise RuntimeError(f"Judge failed for {cache_key}: {exc}") from exc
            messages.append(
                {
                    "role": "user",
                    "content": f"上次输出解析/校验失败（{str(exc)[:180]}）。请只返回合法 JSON：{{\"points\":[... 共{len(rubric)}项 ...],\"note\":\"简短单行总结\"}}。",
                }
            )
            time.sleep(1)
    raise AssertionError("unreachable")


def compute_codex_e_audit(orig_summary: dict) -> dict:
    common_qs = [1, 3, 5, 7, 9, 11]
    all_rows, valid_rows = [], []
    for row in orig_summary["per_question"]:
        if "E" not in row:
            continue
        e = row["E"]
        rec = read_json(FINAL_DIR / e["record"])
        entry = {
            "q": rec["q"],
            "status": e["status"],
            "score": e["score"],
            "max": e["max"],
            "seconds": e["seconds"],
            "answer_preview": (rec.get("answer") or "")[:120],
            "input_tokens": sum(u.get("input_tokens", 0) for u in rec.get("usage", [])),
            "output_tokens": sum(u.get("output_tokens", 0) for u in rec.get("usage", [])),
        }
        all_rows.append(entry)
        if e["status"] == "ok":
            valid_rows.append(entry)
    return {
        "common_questions": common_qs,
        "all_6": {
            "score": sum(r["score"] for r in all_rows),
            "max": sum(r["max"] for r in all_rows),
            "accuracy": round(sum(r["score"] for r in all_rows) / sum(r["max"] for r in all_rows), 4),
            "median_seconds": round(median(r["seconds"] for r in all_rows), 2),
            "empty_wrapper_questions": [r["q"] for r in all_rows if r["status"] != "ok"],
        },
        "valid_prose_4": {
            "questions": [r["q"] for r in valid_rows],
            "score": sum(r["score"] for r in valid_rows),
            "max": sum(r["max"] for r in valid_rows),
            "accuracy": round(sum(r["score"] for r in valid_rows) / sum(r["max"] for r in valid_rows), 4),
            "median_seconds": round(median(r["seconds"] for r in valid_rows), 2),
        },
        "per_question": all_rows,
    }


def main():
    sources_by_id = {s["source_id"]: s for s in read_jsonl(FROZEN_DS / "sources.jsonl")}
    cfg = load_base_config()
    proto = read_json(FINAL_DIR / "qa-protocol.json")
    refs = read_json(FINAL_DIR / "reference.json")
    orig_summary = read_json(FINAL_DIR / "qa-summary.json")
    common_nums = proto["codex_and_edges"]  # [1, 3, 5, 7, 9, 11]

    pareto_configs = {
        "B_v2_fast_nothink": {
            "route": ANSWER_ROUTE,
            "model_id": "deepseek-flash",
            "thinking": "disabled",
            "citation_style": "passage_numbers",
            "max_output_tokens": 8192,
            "timeout_seconds": 120,
            "max_retries": 2,
        },
        "B_v2_fast_low": {
            "route": ANSWER_ROUTE,
            "model_id": "deepseek-flash",
            "thinking": "enabled",
            "reasoning_effort": "low",
            "citation_style": "passage_numbers",
            "max_output_tokens": 16384,
            "timeout_seconds": 180,
            "max_retries": 2,
        },
    }

    pareto_arms = {}
    for arm_name, ans_cfg in pareto_configs.items():
        per_q = []
        for qnum in common_nums:
            q_text = proto["questions"][qnum - 1]
            rubric = proto["rubric"][qnum - 1]
            ref = refs[qnum - 1]
            rec = run_arm_query(arm_name, f"Q{qnum}", q_text, system="B", answer_cfg=ans_cfg, cfg=cfg)
            cit = verify_citations(sources_by_id, rec)
            assert cit["all_valid"], f"Invalid verbatim quote in {arm_name} Q{qnum}"
            jd = judge_answer(f"{arm_name}-Q{qnum}", q_text, rubric, ref, rec)
            per_q.append(
                {
                    "q": qnum,
                    "status": rec["status"],
                    "seconds": rec["seconds"],
                    "retrieve_ms": rec.get("timings_ms", {}).get("retrieve_graph"),
                    "answer_ms": rec.get("timings_ms", {}).get("answer_ms"),
                    "citations": cit["total"],
                    **jd,
                }
            )
            print(f"{arm_name} Q{qnum}: {jd['score']}/{jd['max']} in {rec['seconds']}s", flush=True)
        score_sum = sum(x["score"] for x in per_q)
        max_sum = sum(x["max"] for x in per_q)
        med_sec = round(median(x["seconds"] for x in per_q), 2)
        pareto_arms[arm_name] = {
            "score": score_sum,
            "max": max_sum,
            "accuracy": round(score_sum / max_sum, 4),
            "median_seconds": med_sec,
            "total_citations": sum(x["citations"] for x in per_q),
            "per_question": per_q,
        }

    # Pick Pareto winner for fast live demo: prioritize higher accuracy; on tie >=0.9, prefer faster median_seconds
    ranked_fast = sorted(
        pareto_arms.items(),
        key=lambda kv: (-kv[1]["accuracy"], kv[1]["median_seconds"]),
    )
    winner_name, winner_stats = ranked_fast[0]
    winner_cfg = pareto_configs[winner_name]

    # Sealed Unseen 8-Question Evaluation: A_v2 vs B_v2_fast (winner) vs B_v2_deep
    unseen_arms_cfg = {
        "A_v2": ("A", winner_cfg),
        "B_v2_fast": ("B", winner_cfg),
        "B_v2_deep": (
            "B",
            {
                "route": ANSWER_ROUTE,
                "model_id": "deepseek-flash",
                "thinking": "enabled",
                "reasoning_effort": "max",
                "citation_style": "passage_numbers",
                "max_output_tokens": 32768,
                "timeout_seconds": 240,
                "max_retries": 2,
            },
        ),
    }
    unseen_results = {}
    for arm_label, (sys_mode, ans_cfg) in unseen_arms_cfg.items():
        rows = []
        for item in UNSEEN_QUESTIONS:
            rec = run_arm_query(
                f"unseen-{arm_label}", item["id"], item["question"],
                system=sys_mode, answer_cfg=ans_cfg, cfg=cfg,
            )
            cit = verify_citations(sources_by_id, rec)
            assert cit["all_valid"], f"Invalid verbatim quote in unseen {arm_label} {item['id']}"
            jd = judge_answer(
                f"unseen-{arm_label}-{item['id']}",
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
            print(f"Unseen {arm_label} {item['id']}: {jd['score']}/{jd['max']} in {rec['seconds']}s", flush=True)
        tot_s = sum(r["score"] for r in rows)
        tot_m = sum(r["max"] for r in rows)
        unseen_results[arm_label] = {
            "score": tot_s,
            "max": tot_m,
            "accuracy": round(tot_s / tot_m, 4),
            "median_seconds": round(median(r["seconds"] for r in rows), 2),
            "total_citations": sum(r["citations"] for r in rows),
            "per_question": rows,
        }

    # Assemble frozen baseline comparison on the 6 common questions
    frozen_common = {
        arm: {
            "score": orig_summary["totals"][arm]["common"]["score"],
            "max": orig_summary["totals"][arm]["common"]["max"],
            "accuracy": round(
                orig_summary["totals"][arm]["common"]["score"]
                / orig_summary["totals"][arm]["common"]["max"],
                4,
            ),
            "median_seconds": orig_summary["totals"][arm]["common"]["median_seconds"],
            "statuses": orig_summary["totals"][arm]["common"]["statuses"],
        }
        for arm in "OABCDE"
    }

    pareto_summary = {
        "common_questions": common_nums,
        "frozen_baselines": frozen_common,
        "v2_pareto_arms": pareto_arms,
        "pareto_winner": winner_name,
        "codex_e_audit": compute_codex_e_audit(orig_summary),
        "spend": spend_summary(),
    }
    write_json(OUT_DIR / "qa-pareto-summary.json", pareto_summary)
    write_json(
        OUT_DIR / "qa-unseen-summary.json",
        {
            "questions": len(UNSEEN_QUESTIONS),
            "results": unseen_results,
            "spend": spend_summary(),
        },
    )

    # Update demo/final/itsdangerous.example.json to the Pareto winning fast answer config
    example_path = ROOT / "demo/final/itsdangerous.example.json"
    example_cfg = read_json(example_path)
    example_cfg["answer"] = {
        k: winner_cfg[k]
        for k in (
            "route",
            "model_id",
            "thinking",
            "reasoning_effort",
            "citation_style",
            "max_output_tokens",
            "timeout_seconds",
            "max_retries",
        )
        if k in winner_cfg
    }
    write_json(example_path, example_cfg)
    print("PARETO_WINNER=", winner_name, winner_stats["score"], "/", winner_stats["max"], winner_stats["median_seconds"], "s")
    print("UNSEEN_SUMMARY=", {k: (v["score"], v["max"], v["median_seconds"]) for k, v in unseen_results.items()})
    print("SPEND=", spend_summary())


if __name__ == "__main__":
    main()
