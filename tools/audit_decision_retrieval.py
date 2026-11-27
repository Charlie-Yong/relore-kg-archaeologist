"""Compare which frozen evidence is visible in the two actual answer inputs."""

import argparse
import json
from pathlib import Path

from historykg.llm.answer import render_context
from historykg.pipeline import query_config
from historykg.query.service import prepare_query
from tools.check_public_privacy import USER_PATH

QUESTIONS = (
    "为什么改用标准库 JSON？早期有没有拒绝过类似提议，最终由哪个 PR 合并落地并改了哪些文件？",
    "项目历史上有哪些被拒绝的特性提案及理由？",
    "为什么移除了 simplejson？",
)
SOURCE_LABEL = {"graph_relation": "图谱关系找到原文", "pr_api_lookup": "冻结 PR API 回查",
                "git_diff_lookup": "冻结 Git 差异回查", "shared_retrieval": "共同文本检索"}


def matching(parts, sid, start, end):
    return [i for i, row in enumerate(parts, 1)
            if row["source_id"] == sid and row["start"] <= start < end <= row["end"]]


def compare(config, dataset_id, question):
    arms = {}
    for arm in "AB":
        prepared = prepare_query(
            {"dataset_id": dataset_id, "question": question, "kind": "search"},
            config={**config, "system": arm},
        )
        visible = render_context(prepared["candidates"], max_characters=12000)
        arms[arm] = prepared, visible["fragments"]
        assert prepared["search_intent"] == "decision"
    shared = arms["A"][0]["retrieval"]["source_ids"]
    assert shared == arms["B"][0]["retrieval"]["source_ids"]
    before_b = arms["B"][0]["candidates"]
    keys = []
    for candidate in before_b:
        source = candidate.get("acquisition_source")
        text = candidate["quote"].strip()
        if source not in SOURCE_LABEL or not text or USER_PATH.search(text):
            continue
        if source == "graph_relation" and len(text) > 480:
            text = next((line.strip() for line in text.splitlines()
                         if "simplejson" in line.lower() and 0 < len(line.strip()) <= 480), "")
        if not text:
            continue
        sid = candidate["source_id"]
        start = candidate["start"] + candidate["quote"].index(text)
        end = start + len(text)
        source_text = arms["B"][0]["source_by_id"][sid]["text"]
        assert source_text[start:end] == text
        observations = {}
        for arm, (prepared, visible) in arms.items():
            before = prepared["candidates"]
            observations[arm] = {
                "candidate_ranks": matching(before, sid, start, end),
                "candidate_intervals": [
                    [i, c["start"], c["end"]] for i, c in enumerate(before, 1)
                    if c["source_id"] == sid and c["start"] < end and c["end"] > start
                ],
                "visible_ranks": matching(visible, sid, start, end),
                "visible_intervals": [[f["start"], f["end"]] for f in visible if f["source_id"] == sid],
            }
        a, b = observations.values()
        reason = "两组都可见" if a["visible_ranks"] and b["visible_ranks"] else "按实际可见性记录"
        if b["visible_ranks"] and not a["visible_ranks"]:
            if a["candidate_ranks"] and not a["visible_intervals"]:
                reason = "A 有完整候选但预算用尽，片段排序影响可见性"
            elif a["candidate_ranks"]:
                reason = "A 有完整候选，最终裁剪未保留整个区间"
            elif a["candidate_intervals"]:
                reason = "A 的候选窗口没有完整覆盖该区间"
            else:
                reason = "A 没有覆盖该区间的候选"
        keys.append({"source_id": sid, "start": start, "end": end, "quote": text,
                     "url": candidate.get("detail_url", candidate["url"]),
                     "shared_rank": shared.index(sid) + 1 if sid in shared else None,
                     "acquisition_source": source, "evidence_visibility": observations,
                     "interpretation": reason})
    assert keys
    return {"question": question, "evidence": keys}, arms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("private_output", type=Path)
    args = parser.parse_args()
    project = json.loads(args.config.read_text())
    dataset_id = json.loads((Path(project["dataset_dir"]) / "manifest.json").read_text())["dataset_id"]
    comparisons, private = [], []
    for question in QUESTIONS:
        case, inputs = compare(query_config(project), dataset_id, question)
        comparisons.append(case)
        private.append({name: {"candidates": p["candidates"], "visible": visible,
                               "retrieval_notices": p["retrieval_notices"]}
                        for name, (p, visible) in inputs.items()})
        print(f"核对 {len(case['evidence'])} 条证据区间", flush=True)
    args.private_output.write_text(json.dumps(private, ensure_ascii=False, indent=2) + "\n")
    args.output.with_suffix(".json").write_text(json.dumps(
        {"dataset_id": dataset_id, "context_limit": 12000, "cases": comparisons},
        ensure_ascii=False, indent=2,
    ) + "\n")
    lines = ["# 无编号历史决策题的 A/B 原文对照", "",
             "A 和 B 共用冻结来源、关键词与逐字引文提示。下表记录同一原文区间是否完整进入两组的 12,000 字符输入。"
             "共同列表的排名、B 的取证来源与裁剪结果见 JSON。", ""]
    for case in comparisons:
        lines.extend(["## " + case["question"], ""])
        selected = [row for row in case["evidence"] if row["evidence_visibility"]["B"]["visible_ranks"]]
        for row in selected:
            origin = SOURCE_LABEL[row["acquisition_source"]]
            a, b = row["evidence_visibility"].values()
            status = f"A {'可见' if a['visible_ranks'] else '缺失'}，B {'可见' if b['visible_ranks'] else '缺失'}"
            rank = str(row["shared_rank"]) if row["shared_rank"] else "未入共同前 20 名"
            lines.extend([
                f"- **{status}**。共同检索 {rank}，B 经{origin}。{row['interpretation']}。"
                f"原文区间 {row['start']}–{row['end']}。[出处]({row['url']})", "",
                *["> " + part for part in row["quote"].splitlines()], "",
            ])
    args.output.with_suffix(".md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
