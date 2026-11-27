# ruff: noqa: E501
"""Build the classroom comparison from immutable first-run records and reviewed scores."""

import collections
import json
import statistics

from experiment import HERE, LOCAL, P, save

LABELS = {
    "O": "旧版图谱 API",
    "A": "新版纯文本 API",
    "B": "新版图谱 API",
    "C": "新版图谱 API 再给关系",
    "D": "Codex 查本地",
    "E": "Codex 查 GitHub",
}
SHORT = ["2.0.1 日期", "2.0.0 日期", "讨论 #370", "讨论 #150", "首次包含 #372", "能否确认 #407"]


def read(path):
    return json.loads(path.read_text())


def seconds(record):
    return record.get("seconds", record.get("elapsed_seconds"))


def build():
    records = {f.stem: read(f) for f in (HERE / "records").glob("*.json")}
    scores = {n: read(HERE / "scores" / f"q{n}.json")["scores"] for n in range(1, 7)}
    override = HERE / "score-review.json"
    if override.exists():
        for change in read(override):
            scores[change["q"]][change["arm"]]["points"] = change["points"]

    def pts(a, n):
        return sum(scores[n][a]["points"])

    arms = {}
    for a in LABELS:
        ns = [n for n in scores if a in scores[n]]
        secs = [seconds(records[f"{a}{n}"]) for n in ns]
        arms[a] = dict(
            n=len(ns),
            points=sum(pts(a, n) for n in ns),
            max=sum(len(P["rubric"][n - 1]) for n in ns),
            points_in_300s=sum(pts(a, n) for n in ns if seconds(records[f"{a}{n}"]) <= 300),
            median_seconds=round(statistics.median(secs), 1),
        )
    save(HERE / "totals.json", arms)
    lines = [
        "# HistoryKG 课堂对照表",
        "",
        "ItsDangerous · 2026 年 11 月 16 日冻结 · 同一百炼 DeepSeek-V4.1-Flash-1017，均请求最高思考档。",
        "",
        "每格为「有原文支持的得分 / 满分 · 用户等待秒数」。空白表示事前未安排这组。错误或超时得到 0 分。",
        "",
        "| 同一道新题 | " + " | ".join(LABELS.values()) + " |",
        "|---|" + "---:|" * 6,
    ]
    for n, name in enumerate(SHORT, 1):
        cells = []
        for a in LABELS:
            if a not in scores[n]:
                cells.append("　")
                continue
            r = records[f"{a}{n}"]
            t = seconds(r)
            flag = " †" if t > 300 else ""
            if r["status"] == "error":
                flag += " 服务失败"
            if r["status"] == "timeout":
                flag += " 超时"
            cells.append(f"{pts(a, n):g}/{len(P['rubric'][n - 1])} · {t:.0f}s{flag}")
        lines.append("| " + name + " | " + " | ".join(cells) + " |")
    common = P["codex_and_edges"]
    lines.append(
        "| **三道共同题** | "
        + " | ".join(f"**{sum(pts(a, n) for n in common):g}/10**" for a in LABELS)
        + " |"
    )
    lines.append(
        "| **共同题五分钟内得分** | "
        + " | ".join(
            f"{sum(pts(a, n) for n in common if seconds(records[f'{a}{n}']) <= 300):g}/10"
            for a in LABELS
        )
        + " |"
    )
    lines.append(
        "| **全部六题** | "
        + " | ".join(f"**{arms[a]['points']:g}/20**" if arms[a]["n"] == 6 else "　" for a in LABELS)
        + " |"
    )
    lines.extend(
        [
            "",
            "† 表示用时超过五分钟。每组每题只跑一次正式首答。分数同时反映能否交付和答案质量。以下故障复测另计。",
            "",
            "## 图谱帮到了哪一步",
            "",
            "两道日期题，新版纯文本与图谱都找到了正式发布记录。讨论 #370 要追查一次具体改动。纯文本找到了弃用旧版本属性的理由，图谱进一步接到 PR #371、合并提交和文件变更记录。学生可从答案点到各自原文。[该题图谱原答](records/B3.json) · [该题纯文本原答](records/A3.json)",
            "",
            "## 版本题和服务失败",
            "",
            "每个正式版用自己标签的 Git 历史核查，草稿和预发布版单独处理。六个正式标签中只有 2.2.0 包含 #372 的合并，六个均未包含 #407 的合并。独立复核对 12 个「标签、合并」组合逐个运行 Git 检查。范围限本次冻结历史中的正式发布。[标准出处](reference.json) · [独立核验](verification.json)",
            "",
        ]
    )
    errors = []
    for key, r in sorted(records.items()):
        if key.startswith(("output-", "passages-", "live-")) or r["status"] != "error":
            continue
        retry = records.get("output-" + key)
        errors.append((key, r, retry))
    if errors:
        lines.extend(
            [
                "原定 8,192 个输出 token 由思考和写答案共用。百炼的部分回执显示模型用完整个额度，仍未交付文字。下列复测保持同一份输入原文和相同思考档，把输出上限调到 16,384。两轮得分分别保存。",
                "",
                "| 题次 | 首次 | 加大输出上限后的实测 |",
                "|---|---|---|",
            ]
        )
        for key, row, retry in errors:
            new = (
                f"[{retry['status']} · {seconds(retry):.0f} 秒](records/output-{key}.json)"
                if retry
                else "未复测"
            )
            lines.append(
                f"| {key} | [未交付 · {seconds(row):.0f} 秒](records/{key}.json) | {new} |"
            )
    lines.extend(
        [
            "",
            "## 怎样复核与演示",
            "",
            "先看普通提问框里的答案，再展开「原文证据」，点对应版本或提交。课堂可以换一个版本号，也可以从讨论追问具体文件。[本机现场演示](http://127.0.0.1:8517) · [实际提交表单记录](demo-receipt.json)",
            "",
            "旧题只用于开发。六道新题和参考事实在修改查询代码前封存。评分先隐藏组名和耗时，由模型逐项核查，再核对原答。仍是单仓库小样本。Codex 两组计时包含工具操作、网络和启动；本地与在线实际可读范围不同。历史图构建用时与单题等待分开，原建图实测约 39 分钟。",
            "",
            "[六道题及实验条件](protocol.json) · [各组原始回答](records/) · [分项分数](scores/) · [模型用量与耗时](measurements.json) · [原来的三题](../agent-comparison-20261120/实验报告.md)",
            "",
        ]
    )
    (HERE / "8192首答.md").write_text("\n".join(lines))
    measurements = {}
    for k, r in records.items():
        data = dict(
            seconds=seconds(r),
            status=r["status"],
            delivered_by_300s=seconds(r) <= 300 and r["status"] == "ok",
        )
        if "responses" in r:
            data.update(
                requests=[
                    {"http": v["status"], "finish": v["reason"], "usage": v["usage"]}
                    for v in r["responses"]
                ]
            )
        else:
            data["usage"] = r.get("usage", [])
            traces = LOCAL / k / "events.jsonl"
            calls = collections.Counter()
            if traces.exists():
                for line in traces.read_text().splitlines():
                    v = json.loads(line)
                    item = v.get("item") or {}
                    if v.get("type") == "item.completed" and item.get("type") in (
                        "mcp_tool_call",
                        "command_execution",
                        "web_search",
                    ):
                        calls[item.get("tool", item["type"])] += 1
            data["observed_tools"] = dict(calls)
        measurements[k] = data
    save(HERE / "measurements.json", measurements)


def classroom():
    totals = {}
    rows = []
    for n, topic in enumerate(SHORT, 1):
        score = read(HERE / "scores" / f"live-q{n}.json")["scores"]
        review = HERE / "live-score-review.json"
        if review.exists():
            for fix in read(review):
                if fix["q"] == n:
                    score[fix["arm"]]["points"] = fix["points"]
        cells = []
        for arm in LABELS:
            if arm not in score:
                cells.append("　")
                continue
            key = ("" if arm in "DE" else "live-") + f"{arm}{n}"
            rec = read(HERE / "records" / f"{key}.json")
            pts = sum(score[arm]["points"])
            duration = seconds(rec)
            total = totals.setdefault(arm, dict(points=0, max=0, common=0, in_time=0, times=[]))
            total["points"] += pts
            total["max"] += len(P["rubric"][n - 1])
            total["times"].append(duration)
            if n in P["codex_and_edges"]:
                total["common"] += pts
                total["in_time"] += pts if duration <= 300 else 0
            flag = "†" if duration > 300 else ""
            cells.append(
                f"[{pts:g}/{len(P['rubric'][n - 1])} · {duration:.0f}s{flag}](records/{key}.json)"
            )
        rows.append("| " + topic + " | " + " | ".join(cells) + " |")
    table = ["| 同题比较 | " + " | ".join(LABELS.values()) + " |", "|---|" + "---:|" * 6, *rows]
    for title, metric in [("三道共同题合计", "common"), ("共同题五分钟内得分", "in_time")]:
        table.append(
            "| **"
            + title
            + "** | "
            + " | ".join(f"**{totals[a][metric]:g}/10**" for a in LABELS)
            + " |"
        )
    table.append(
        "| **六题合计** | "
        + " | ".join(
            f"**{totals[a]['points']:g}/20**" if totals[a]["max"] == 20 else "　" for a in LABELS
        )
        + " |"
    )
    save(HERE / "live-totals.json", totals)
    lines = [
        "# HistoryKG 课堂对照表",
        "",
        "ItsDangerous · 2026 年 11 月 16 日冻结。把最高思考档问答的输出上限从 8,192 提高到 32,768 后，"
        "新版图谱 API 六题全部交付，成绩从 12/20 升到 20/20；两道额外封存的版本题也全部答对。",
        "",
        "同一百炼 DeepSeek-V4.1-Flash-1017。API 各组均请求 max 思考、32,768 个输出 token、单次最多等待 240 秒。每格是有据得分和实际等待时间，可点开原答。",
        "",
        *table,
        "",
        "† 表示超过五分钟。Codex 各查三道事先选定的题，计时包含启动和查找资料，沿用实际首答。API 的六道题都用同一份冻结资料复跑。",
        "",
        "## 哪一步有用",
        "",
        "两道日期题只需找到正式发布记录。讨论 #370 要追到 PR #371、合并提交和实际改过的文件。版本题则要核对每个正式标签的提交历史。图谱组在表格中保留每项结论的原文或可复查的核对记录。",
        "",
        "第一轮在改程序前封存了六道题，使用 8,192 的输出上限。旧图谱得 2/20，改进检索后得 12/20，两道版本题都因回答未能交付得零。"
        "回查输入发现，足够回答的资料已经找齐。把相同原文编成短号码，让模型指出编号、由程序附上对应引文，在 8,192 上限下两道版本题就能完成。"
        "上表按后来选定的 32,768 上限再测，成绩和初次结果分开保存。这轮复测使用同一批六题，不是新题。"
        "[8,192 首答与 16,384 复核](8192首答.md) · [第一遍资料核查](first-pass-coverage.json) · [编号引用实例](records/passages-B5.json)",
        "",
        "## 两道额外封存的版本题",
        "",
    ]
    for n, ref in enumerate(read(HERE / "citation-check-protocol.json"), 7):
        row = read(HERE / "records" / f"live-B{n}.json")
        lines.append(
            f"- PR #{ref['pr'].rsplit('/', 1)[-1]} 的参考结论是"
            f"「{ref['first'] or '冻结资料中的正式版均未包含'}」。"
            f"图谱组用时 {seconds(row):.1f} 秒。[完整回答](records/live-B{n}.json)"
        )
    lines += [
        "",
        "## 现场提问",
        "",
        "在普通提问框输入一道项目历史问题，展开原文证据，点开正式版本页或提交页。"
        "[打开本机演示](http://127.0.0.1:8517) · [真实表单运行记录](demo-receipt.json)",
        "",
        "各方法每题每设置一次，原始回答与独立运行计时均保留。评分时隐藏方法和时间，按预设评分项核对出处。"
        "本地与在线资料的范围不同。预建图约 39 分钟，单题时间从提问算起。"
        "[题目和评分条件](protocol.json) · [评分明细](scores/) · [用量记录](measurements.json) · [复核结果](verification.json)",
        "",
    ]
    (HERE / "课堂对照表.md").write_text("\n".join(lines))


if __name__ == "__main__":
    build()
    classroom()
