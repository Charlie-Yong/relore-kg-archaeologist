"""Package committed source and an explicit frozen production dataset, without calls."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

from historykg.io import read_json, validate_dataset

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    if "private_test" in dataset.parts:
        raise ValueError("只接收冻结生产数据，不打包P6私有目录")
    report = validate_dataset(dataset)
    if report["status"] != "ok":
        raise ValueError(report["errors"])
    if subprocess.check_output([
        "git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no",
    ]).strip():
        raise ValueError("先保存并提交源文件，打包使用准确的干净提交")
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
    ).strip()
    source = subprocess.check_output([
        "git", "-C", str(ROOT), "archive", "--format=zip", "--prefix=source/", commit,
    ])
    manifest = read_json(dataset / "manifest.json")
    files = ["manifest.json", *manifest["files"]]
    files += ["exports/" + p.name for p in (dataset / "exports").glob("*.json")]
    files += [p.relative_to(dataset).as_posix()
              for p in (dataset / "llm").glob("*/extract/**/*.json")]
    files += [p.relative_to(dataset).as_posix()
              for p in (dataset / "llm").glob("*/answer/**/*.json")]
    hashes = {}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out, "w", compression=zipfile.ZIP_DEFLATED) as out:
        def put(name, body):
            if "private_test" in Path(name).parts:
                raise ValueError("拒绝私有目录")
            out.writestr(name, body)
            hashes[name] = hashlib.sha256(body).hexdigest()

        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            for name in archive.namelist():
                if not name.endswith("/"):
                    put(name, archive.read(name))
        for name in sorted(set(files)):
            original = dataset / name
            path = original.resolve()
            if not path.is_relative_to(dataset) or original.is_symlink():
                raise ValueError("冻结文件必须位于生产数据目录")
            put("frozen/" + name, path.read_bytes())
        instructions = (
            "# 课程复现候选包\n\n"
            "source/ 是准确提交的源码与锁定依赖；frozen/ 是冻结生产来源、图与模型运行记录。\n"
            "包内不含密钥、个人运行配置、完整clone或P6私有测试。\n\n"
            "1. 无付费重建：按 source/repro/README.md 安装、配置本机数据库，然后在source中运行\n"
            "   python tools/run_platform_rebuild.py --dataset ../frozen"
            " --out .local/rebuild.json\n"
            "   --question 'stream context'。原始模型日志用于审计，不会自动再次调用。\n"
            "2. 实验重算：只使用source/evaluation/results中P6已公开的汇总与统计入口；\n"
            "   未发布的参考和成绩不在本包，阶段候选不能冒称完整正式实验包。\n"
            "3. 外部模型重跑：配置自己的账号、密钥、数据库和批准预算，按source/README.md\n"
            "   从URL另建作业；模型服务变化时不保证逐字复现。\n\n"
            "报告在source/output/pdf，演示和PPT按source/deliveries/P5说明。\n"
            "SHA256SUMS.json逐文件校验本包；第三方许可见source/THIRD_PARTY_NOTICES.md。\n"
        )
        put("REPRODUCE.md", instructions.encode())
        put("PACKAGE.json", json.dumps({
            "source_commit": commit, "dataset_id": manifest["dataset_id"],
            "package_status": "stage_candidate_until_formal_results_and_human_peer_review",
            "new_model_requests": 0, "validation": report,
        }, ensure_ascii=False, indent=2).encode())
        out.writestr("SHA256SUMS.json", json.dumps(hashes, indent=2))
    with zipfile.ZipFile(args.out) as archive:
        for name, digest in hashes.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    args.out.with_suffix(args.out.suffix + ".sha256").write_text(digest + "\n")
    print(json.dumps({"out": str(args.out), "sha256": digest, "files": len(hashes),
                      "source_commit": commit, "new_model_requests": 0}))


if __name__ == "__main__":
    main()
