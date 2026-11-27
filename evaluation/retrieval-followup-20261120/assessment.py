"""Blind per-fact assessment of delivered answers, with a separately saved identity key."""

import json
import random
import sys
import time

from experiment import HERE, LOCAL, P, load_runner, save


def grade(n, live=False):
    version = "live-" if live else ""
    dest = HERE / "scores" / f"{version}q{n}.json"
    if dest.exists():
        return
    reference = json.loads((HERE / "reference.json").read_text())
    arms = list("OABCDE" if n in P["codex_and_edges"] else "OAB")
    random.SystemRandom().shuffle(arms)
    answers = {}
    labels = {}
    for i, arm in enumerate(arms):
        label = str(i + 1)
        labels[label] = arm
        key = (version if arm not in "DE" else "") + f"{arm}{n}"
        record = json.loads((HERE / "records" / f"{key}.json").read_text())
        if "answer" in record:
            answer = record["answer"] if record["status"] == "ok" else "未交付答案"
        else:
            refs = {e["evidence_id"]: e for e in record.get("evidence", [])}
            answer = [
                {
                    "text": c["text"],
                    "sources": [
                        {
                            k: refs[i][k]
                            for k in ("quote", "url", "context_note", "detail_url")
                            if k in refs[i]
                        }
                        for i in c["evidence_ids"]
                    ],
                }
                for c in record["claims"]
            ]
            answer = (
                {"claims": answer, "gaps": record["gaps"][-4:]}
                if record["status"] in ("ok", "empty")
                else "未交付答案"
            )
        answers[label] = answer
    prompt = dict(
        question=P["questions"][n - 1],
        rubric=P["rubric"][n - 1],
        reference=reference[n - 1],
        answers=answers,
    )
    save(LOCAL / f"{version}blind-{n}.json", prompt)
    save(LOCAL / f"{version}labels-{n}.json", labels)
    system = (
        "按评分项顺序核查匿名答案。"
        "只给实际说出且有对应出处支持的事实计1分。"
        "部分事实或出处不足给0.5分，错误或未答为0。"
        "不能用参考答案或用户题目替回答填空。"
        "日期题的发布出处可以是对应的官方 releases API 原文片段或正式版网页。"
        "修改文件须有历史改动记录。"
        "版本归属题中发布清单须有日期和范围，正式发布和普通标签区分。"
        "标签包含关系项要实际核对所问合并与标签历史，单凭日期/缺边不能得该项满分。"
        "程序可以核查完整冻结原文并在附于引用的 context_note 记录核对结果。"
        "若回答只说'需要核对'，不算实际查过。"
        "限定到冻结来源与截止日的可验证结论可获满分。"
        "只返回 JSON 对象，键为匿名编号，值为 "
        '{"points":[0或0.5或1,...],"note":"简短说明具体扣分项"}。'
    )
    run = load_runner()
    for attempt in range(3):
        try:
            result = run.BailianTransport().handle_request(
                run.httpx.Request(
                    "POST",
                    "https://unused",
                    json={
                        "model": "deepseek-flash",
                        "thinking": {"type": "disabled"},
                        "max_tokens": 6500,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                        ],
                    },
                )
            )
            if result.status_code != 200:
                raise ValueError(f"judge HTTP {result.status_code}")
            body = result.json()
            judged = json.loads(body["choices"][0]["message"]["content"])
            assert set(judged) == set(labels)
            assert all(
                len(row["points"]) == len(prompt["rubric"])
                and all(x in (0, 0.5, 1) for x in row["points"])
                for row in judged.values()
            )
            break
        except (ValueError, KeyError, IndexError, AssertionError, run.httpx.HTTPError):
            if attempt == 2:
                raise
            time.sleep(1)
    save(
        dest,
        dict(
            rubric=prompt["rubric"],
            model=body.get("model"),
            usage=body.get("usage"),
            scores={labels[k]: v for k, v in judged.items()},
        ),
    )
    print("scored", n, flush=True)


if __name__ == "__main__":
    for n in (int(v) for v in sys.argv[1:] if v != "--live"):
        grade(n, "--live" in sys.argv)
