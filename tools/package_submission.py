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
DEFAULT_FINAL_PPT = Path("demo/midterm/期中汇报_20261111_20261030正式结果版.pptx")
PACKAGE_STATUSES = ("stage_candidate", "final_candidate", "final")
FORBIDDEN_PARTS = {".local", "clones", "private_test", "submission"}
FORBIDDEN_NAMES = {"credentials.json", "id_ed25519", "id_rsa", "secrets.json"}


def assert_public_member(name: str) -> None:
    """Reject private tests, credentials, and local-only package members."""
    parts = Path(name).parts
    if any(part.lower() in FORBIDDEN_PARTS for part in parts):
        raise ValueError(f"拒绝私有或本地路径: {name}")
    for part in parts:
        lower = part.lower()
        if lower == ".env.example" or lower.endswith(".example"):
            continue
        if lower == ".env" or lower.startswith(".env."):
            raise ValueError(f"拒绝凭据文件: {name}")
        if lower in FORBIDDEN_NAMES or lower.startswith("id_rsa"):
            raise ValueError(f"拒绝凭据文件: {name}")
        if lower.endswith((".key", ".pem")):
            raise ValueError(f"拒绝凭据文件: {name}")


def inspect_presentation(
    path: Path | None,
    *,
    require_exists: bool = False,
    require_tracked: bool = False,
    root: Path = ROOT,
) -> dict | None:
    """Return final-deck metadata, enforcing presence before a final package."""
    if path is None:
        if require_exists:
            raise ValueError("final状态要求最终PPT存在")
        return None
    candidate = path if path.is_absolute() else root / path
    if not candidate.exists():
        if require_exists:
            raise ValueError(f"final状态要求最终PPT存在: {path}")
        return None
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("最终PPT必须是非符号链接的普通文件")
    if candidate.suffix.lower() != ".pptx":
        raise ValueError("最终PPT必须是.pptx文件")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("最终PPT必须位于待打包仓库内")
    relative = resolved.relative_to(root.resolve()).as_posix()
    if require_tracked:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", relative],
            capture_output=True,
            text=True,
        )
        if tracked.returncode:
            raise ValueError("final状态要求最终PPT由待打包提交跟踪")
    body = resolved.read_bytes()
    return {
        "path": relative,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }


def presentation_for_status(status: str, final_ppt: Path | None) -> dict | None:
    if status not in PACKAGE_STATUSES:
        raise ValueError(f"未知包状态: {status}")
    require = status == "final"
    if require and final_ppt is None:
        final_ppt = DEFAULT_FINAL_PPT
    return inspect_presentation(
        final_ppt,
        require_exists=require or final_ppt is not None,
        require_tracked=require,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--package-status",
        choices=PACKAGE_STATUSES,
        default="final_candidate",
        help="包状态；final仅在最终PPT存在且由待打包提交跟踪时允许",
    )
    parser.add_argument(
        "--final-ppt",
        type=Path,
        help=f"最终PPT路径；final默认使用 {DEFAULT_FINAL_PPT.as_posix()}",
    )
    args = parser.parse_args(argv)
    presentation = presentation_for_status(args.package_status, args.final_ppt)
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
            assert_public_member(name)
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
            "# 课程复现包\n\n"
            "source/ 是准确提交的源码与锁定依赖；frozen/ 是冻结生产来源、图与模型运行记录。\n"
            "包内不含密钥、个人运行配置、完整clone或P6私有测试。\n\n"
            "PACKAGE.json 的 package_status 区分 stage_candidate、final_candidate 与 final；\n"
            "final 只在最终PPT存在且由待打包提交跟踪时允许，final_candidate 仍需成员核对\n"
            "姓名、学号、互评及现场材料。\n\n"
            "1. 无付费重建：按 source/repro/README.md 安装、配置本机数据库，然后在source中运行\n"
            "   python tools/run_platform_rebuild.py --dataset ../frozen"
            " --out .local/rebuild.json\n"
            "   --question 'stream context'。原始模型日志用于审计，不会自动再次调用。\n"
            "2. 实验重算：只使用source/evaluation/results中P6已公开的汇总与统计入口；\n"
            "   未发布的私有参考不在本包，包状态不能替代课程要求的成员互评。\n"
            "3. 外部模型重跑：配置自己的账号、密钥、数据库和批准预算，按source/README.md\n"
            "   从URL另建作业；模型服务变化时不保证逐字复现。\n\n"
            "报告在source/output/pdf，演示和PPT按source/deliveries/P5说明。\n"
            "SHA256SUMS.json逐文件校验本包；第三方许可见source/THIRD_PARTY_NOTICES.md。\n"
        )
        put("REPRODUCE.md", instructions.encode())
        put("PACKAGE.json", json.dumps({
            "source_commit": commit, "dataset_id": manifest["dataset_id"],
            "package_status": args.package_status,
            "final_ppt": presentation,
            "excluded": [
                "P6 private test material",
                "API credentials and personal local configuration",
                "complete Git clones",
            ],
            "new_model_requests": 0,
            "validation": report,
        }, ensure_ascii=False, indent=2).encode())
        out.writestr("SHA256SUMS.json", json.dumps(hashes, indent=2))
    with zipfile.ZipFile(args.out) as archive:
        for name, digest in hashes.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    args.out.with_suffix(args.out.suffix + ".sha256").write_text(digest + "\n")
    print(json.dumps({
        "out": str(args.out),
        "sha256": digest,
        "files": len(hashes),
        "source_commit": commit,
        "package_status": args.package_status,
        "final_ppt": presentation,
        "new_model_requests": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
