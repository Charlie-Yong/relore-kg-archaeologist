"""Offline scoring and source-only freezing, exposed through historykg evaluate."""

import argparse
import json
from pathlib import Path

from historykg.io import read_json, write_json

from .metrics import score_extraction, score_qa
from .pool_check import retry_failed_whole_pool
from .reference import freeze_sources
from .statistics import summarize_qa


def main(argv=None):
    parser = argparse.ArgumentParser(description="P6独立参考与可复算评分")
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("score", help="用已保存逐项判断离线重算，无模型费用")
    score.add_argument("records", type=Path)
    score.add_argument("--out", type=Path)
    summary = commands.add_parser("summarize", help="从逐题QA指标离线重算汇总和配对统计")
    summary.add_argument("records", type=Path)
    summary.add_argument("--split", choices=("dev", "test"), default="test")
    summary.add_argument("--out", type=Path)
    freeze = commands.add_parser("freeze", help="冻结来源清单/主题划分，不读取生产预测")
    freeze.add_argument("dataset_dir", type=Path)
    freeze.add_argument("--out", type=Path, required=True)
    freeze.add_argument("--dev-threads", type=int, nargs="+", required=True)
    retry_pool = commands.add_parser(
        "retry-pool", help="只重试全池核验的失败位置；成功缓存与原记录保留"
    )
    retry_pool.add_argument("freeze", type=Path)
    retry_pool.add_argument("--model-config", type=Path, required=True)
    retry_pool.add_argument("--ledger", type=Path, required=True)
    retry_pool.add_argument("--approved-cny", type=float, required=True)
    args = parser.parse_args(argv)
    if args.command == "score":
        data = read_json(args.records)
        if data["task"] == "extraction":
            result = score_extraction(
                data["references"],
                data["predictions"],
                data["judgments"],
                reference_complete=data.get("reference_complete", True),
            )
        elif data["task"] == "qa":
            result = score_qa(
                data["reference"], data["answer"], data["judgment"], data["fragments"]
            )
        else:
            raise ValueError("unsupported scoring task")
        if args.out:
            write_json(args.out, result)
    elif args.command == "summarize":
        result = summarize_qa(read_json(args.records), split=args.split)
        if args.out:
            write_json(args.out, result)
    elif args.command == "freeze":
        frozen = freeze_sources(args.dataset_dir, args.out, dev_threads=args.dev_threads)
        result = {"status": "ok", "counts": frozen["counts"], "freeze_hash": frozen["freeze_hash"]}
    else:
        freeze = read_json(args.freeze)
        config = read_json(args.model_config)
        budget = {
            **config.get("budget", {}),
            "ledger_path": str(args.ledger),
            "approved_cny": args.approved_cny,
            "max_cost_cny": args.approved_cny,
        }
        result = retry_failed_whole_pool(
            freeze, args.freeze.parent, config["model"], budget
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
