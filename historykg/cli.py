"""Public command line. Algorithms and job state stay in owning modules."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from historykg import collector, pipeline
from historykg.ingest.capture import map_capture
from historykg.ingest.fixture import create_fixture
from historykg.io import read_json, validate_dataset, write_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="项目历史知识图谱：输入公开GitHub Python仓库URL自动构建"
    )
    parser.add_argument("--config", type=Path, help="本机项目JSON配置；凭据用环境变量")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="从URL自动构建，默认等待当前执行结束")
    build.add_argument("repo_url")
    build.add_argument("--profile", default="course_small_v1")
    resume = sub.add_parser("resume", help="从持久检查点恢复")
    resume.add_argument("job_id")
    status = sub.add_parser("build-status", help="只读取构建状态，不启动任务")
    status.add_argument("job_id")
    sub.add_parser("doctor", help="检查运行源码/数据库/模块，不调用模型")
    fixture = sub.add_parser("fixture", help="生成并校验明确标注的toy_v1合成数据")
    fixture.add_argument("--out", type=Path, default=Path("fixtures/toy_v1"))
    ingest = sub.add_parser("ingest", help="把已有P4冻结capture映射成C5数据（开发复现）")
    ingest.add_argument("capture", type=Path)
    ingest.add_argument("--dataset-id", required=True)
    ingest.add_argument("--out", type=Path, required=True)
    for command in ("code", "extract"):
        stage = sub.add_parser(command, help="使用同一pipeline推进已有job至指定开发阶段")
        stage.add_argument("job_id")
    validate = sub.add_parser("validate", help="校验来源、ID、引文、端点与冻结清单")
    validate.add_argument("dataset_dir", type=Path)
    load = sub.add_parser("load", help="调用P2同源索引与Neo4j导入")
    load.add_argument("dataset_dir", type=Path)
    query = sub.add_parser("query", help="调用P2公共问答入口")
    query.add_argument("question")
    query.add_argument("--dataset-id", required=True)
    query.add_argument(
        "--kind",
        default="search",
        choices=["search", "trace", "timeline", "dependencies", "compare"],
    )
    export = sub.add_parser("export", help="导出当前数据集的生产可见来源清单")
    export.add_argument("dataset_dir", type=Path)
    export.add_argument("--out", type=Path, required=True)
    evaluate = sub.add_parser("evaluate", help="转交P6实验入口")
    evaluate.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        config = pipeline.load_config(read_json(args.config) if args.config else None)
        if args.command == "build":
            result = pipeline.start_build(
                {"repo_url": args.repo_url, "profile": args.profile}, config=config
            )
            result = pipeline.wait_build(result["job_id"], config=config)
        elif args.command == "resume":
            result = pipeline.resume_build(args.job_id, config=config)
            result = pipeline.wait_build(result["job_id"], config=config)
        elif args.command == "build-status":
            result = pipeline.get_build(args.job_id, config=config)
        elif args.command in {"code", "extract"}:
            result = pipeline.run_stage(args.job_id, args.command, config=config)
        elif args.command == "doctor":
            result = collector.doctor(config.get("database_url"))
            result["modules"] = {}
            for module in (
                "historykg.code",
                "historykg.extract",
                "historykg.graph",
                "historykg.query",
            ):
                try:
                    result["modules"][module] = importlib.util.find_spec(module) is not None
                except ModuleNotFoundError:
                    result["modules"][module] = False
        elif args.command == "fixture":
            create_fixture(args.out)
            result = validate_dataset(args.out)
        elif args.command == "ingest":
            result = map_capture(args.capture, dataset_dir=args.out, dataset_id=args.dataset_id)
        elif args.command == "validate":
            result = validate_dataset(args.dataset_dir)
        elif args.command == "load":
            result = pipeline._call(
                config["load_module"],
                "load_dataset",
                args.dataset_dir,
                config=pipeline.query_config(config),
            )
        elif args.command == "query":
            result = pipeline._call(
                "historykg.query",
                "query",
                {
                    "dataset_id": args.dataset_id,
                    "kind": args.kind,
                    "question": args.question,
                    "seed_ids": [],
                    "filters": {},
                },
                config=pipeline.query_config(config),
            )
        elif args.command == "evaluate":
            try:
                entry = importlib.import_module("historykg.evaluation").main
            except (ModuleNotFoundError, AttributeError) as exc:
                raise pipeline.StageBlocked("等待P6 evaluate入口") from exc
            return entry(args.args)
        else:
            manifest = read_json(args.dataset_dir / "manifest.json")
            write_jsonl(args.out, manifest["sources"])
            result = {"status": "ok", "dataset_id": manifest["dataset_id"], "out": str(args.out)}
    except pipeline.StageBlocked as exc:
        result = {"status": "blocked", "error": {"code": "module_unavailable", "message": str(exc)}}
    except (ValueError, KeyError) as exc:
        result = {"status": "unsupported", "error": {"code": "input", "message": str(exc)}}
    except OSError as exc:
        result = {"status": "error", "error": {"code": "local_io", "type": type(exc).__name__}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {
        "ok": 0,
        "ready": 0,
        "empty": 0,
        "partial": 3,
        "blocked": 3,
        "queued": 3,
        "running": 3,
    }.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
