"""Freeze questions and verify their reference facts against the untouched source pool."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = next((ROOT / ".local/full-history-itsdangerous/datasets").glob("*/sources.jsonl"))
BASE = "https://api.github.com/repos/pallets/itsdangerous/"
WEB = "https://github.com/pallets/itsdangerous/"
BASELINE_SHA = "29145a752b080a2a80d4f2b54a4b52628b621de0e7c581fbb91642505ecff8ec"
QUESTIONS = [
    "ItsDangerous 2.0.1 在 GitHub 正式发布的 UTC 日期是哪天？请给出正式发布出处。",
    "请核实 2.0.0 正式版的 GitHub 发布日期（UTC），并指出从哪条发布记录可以核对。",
    "Issue #370 为什么提出改动？由哪个 PR 和哪次合并落实？举一个实际改过的文件，并给出处。",
    "请追溯 Issue #150：为什么改，哪个 PR 被合并，合并提交是什么？举一处"
    "实际改动的测试文件并给出处。",
    "PR #372 的合并提交最早包含在哪个 GitHub 正式发布版？请用合并记录、"
    "发布清单和标签提交历史说明。",
    "截止给定日期，PR #407 的合并提交能确认已进入哪个 GitHub 正式发布版吗？请用合并记录、"
    "发布清单和标签提交历史说明依据及结论范围。",
]
RUBRICS = (
    [["UTC 日期", "与该日期对应的正式发布出处"]] * 2
    + [
        ["动机", "对应 PR", "实际合并 SHA", "历史改动文件及来源"],
        ["动机", "对应 PR", "实际合并 SHA", "实际改动测试文件及来源"],
    ]
    + [
        [
            "实际合并",
            "截止日前正式发布清单或有据的边界",
            "对应标签的实际祖先核对",
            "首次版本或有限结论",
        ]
    ]
    * 2
)


def freeze():
    source = [json.loads(line) for line in DATA.open()]
    api = {s["url"]: json.loads(s["text"]) for s in source if s["kind"] == "api_response"}
    git = {
        tuple(s["git_metadata"]["command"][1:]): json.loads(s["text"])["stdout"]
        for s in source
        if s["kind"] == "git_output" and s["git_metadata"]["returncode"] == 0
    }
    releases = sorted(
        (
            r
            for r in api[BASE + "releases"]
            if not r["draft"]
            and not r["prerelease"]
            and r["published_at"] <= "2026-11-16T06:31:18Z"
        ),
        key=lambda r: r["published_at"],
    )
    reference = []
    for tag in ("2.0.1", "2.0.0"):
        r = next(r for r in releases if r["tag_name"] == tag)
        reference.append(dict(tag=tag, utc=r["published_at"], url=r["html_url"]))
    for issue, pr in ((370, 371), (150, 151)):
        i, p = api[BASE + f"issues/{issue}"], api[BASE + f"pulls/{pr}"]
        sha = p["merge_commit_sha"]
        changed = next(v for args, v in git.items() if args[0] == "diff-tree" and args[-1] == sha)
        reference.append(
            dict(
                issue=i["html_url"],
                motive=i["body"],
                pr=p["html_url"],
                pr_body=p["body"],
                merged=p["merged_at"],
                sha=sha,
                changes=changed.rstrip("\0").split("\0"),
                diff=WEB + "commit/" + sha,
            )
        )
    for pr in (372, 407):
        p = api[BASE + f"pulls/{pr}"]
        membership = []
        for r in releases:
            tag = r["tag_name"]
            target = git["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"].strip()
            parents = git["rev-list", target].splitlines()
            membership.append(
                dict(
                    tag=tag,
                    published=r["published_at"],
                    url=r["html_url"],
                    tip=target,
                    contains=p["merge_commit_sha"] in parents,
                )
            )
        reference.append(
            dict(
                pr=p["html_url"],
                merged=p["merged_at"],
                sha=p["merge_commit_sha"],
                tags=membership,
                first=next((r["tag"] for r in membership if r["contains"]), None),
            )
        )
    old = json.loads((HERE.parent / "agent-comparison-20261120/protocol.json").read_text())
    protocol = {
        **{k: old[k] for k in ("repo", "cutoff_utc", "head", "primary_seconds", "stop_seconds")},
        "questions": QUESTIONS,
        "rubric": RUBRICS,
        "codex_and_edges": [1, 3, 5],
        "route": "bailian/deepseek-v4.1-flash-1017",
        "reasoning_effort": "max",
        "context_characters": 12000,
        "source_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
        "baseline_archive_sha256": BASELINE_SHA,
        "scoring": "每项有据且完整为1，部分正确或出处不足为0.5，缺失或错误为0；"
        "不把系统诊断或图后台材料当成已经作答。",
    }
    for name, obj in (("protocol", protocol), ("reference", reference)):
        dest = HERE / (name + ".json")
        data = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode()
        if dest.exists():
            assert dest.read_bytes() == data, f"{dest.name} differs from the sealed copy"
        else:
            dest.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    freeze()
