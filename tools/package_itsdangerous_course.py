"""Create the final-course candidate from an explicit portable file inventory."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from historykg.io import read_json, validate_dataset
from tools.check_public_privacy import load_roster, scan, scan_zip
from tools.package_submission import assert_public_member

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "demo/final"
EXPERIMENT = ROOT / "evaluation/itsdangerous-final-20261121"
V2_EXPERIMENT = ROOT / "evaluation/itsdangerous-v2-20261126"
ACTIVE_FIGURES = (
    "fig1_architecture.png",
    "fig2_schema_and_evidence_chain.png",
    "fig3_extraction_v2.png",
    "fig4_qa_pareto_and_unseen.png",
    "fig5_generalization_evolution.png",
    "fig6_workbench_demo.png",
)
CANDIDATE = "course_candidate_pending_member_reviews"
REHEARSAL = "course_rehearsal"
REALNAME_COURSE = "course_final_realname_submission"
REALNAME_MATERIAL_MEMBERS = {
    "materials/ItsDangerous-期末汇报.pptx",
    "materials/ItsDangerous-技术报告.pdf",
    "materials/ItsDangerous-技术报告.md",
}


def _scan_realname_archive(archive_path: Path, roster: list[dict]) -> dict:
    """Verify source/frozen/other files stay privacy-clean while 3 materials include all 6 real members."""
    from tools.check_public_privacy import _texts

    with ZipFile(archive_path) as archive:
        sources = {}
        for name in ("frozen/sources.jsonl", "frozen/p3/sources.jsonl"):
            if name in archive.namelist():
                for line in archive.read(name).splitlines():
                    row = json.loads(line)
                    sources[row["source_id"]] = row
        clean_items = []
        realname_items = []
        for info in archive.infolist():
            data = archive.read(info)
            if info.filename in REALNAME_MATERIAL_MEMBERS:
                realname_items.append((info.filename, data))
            else:
                clean_items.append((info.filename, data))
    clean_scan = scan(clean_items, roster=roster, frozen_sources=sources)
    material_scan = scan(realname_items, roster=None, frozen_sources=sources)
    errors = [*clean_scan["errors"], *material_scan["errors"]]
    for filename, data in realname_items:
        joined = "\n".join(body for _, body in _texts(filename, data))
        missing = [
            f"{m['name']}({m['student_id']})"
            for m in roster
            if m["name"] not in joined or m["student_id"] not in joined
        ]
        if missing:
            errors.append({"file": filename, "reason": f"missing_realname_members:{','.join(missing)}"})
    return {
        "passed": not errors,
        "member_roster_checked": True,
        "errors": errors,
        "review": [*clean_scan["review"], *material_scan["review"]],
    }


def build(dataset, out, replay, *, report_md=None, report_pdf=None, deck=None,
          require_roster=True, package_status=CANDIDATE, realname_course=False):
    if realname_course:
        package_status = REALNAME_COURSE
        require_roster = True
    if package_status not in {CANDIDATE, REHEARSAL, REALNAME_COURSE}:
        raise ValueError("Choose a supported package status")
    if package_status == REALNAME_COURSE and not realname_course:
        realname_course = True
        require_roster = True
    roster_path = ROOT / ".local/member-privacy-roster.json"
    roster = load_roster(roster_path)
    roster_raw = read_json(roster_path) if roster_path.is_file() else {}
    if require_roster and roster is None:
        raise ValueError("成员信息未核验（未加载私有名单）")
    if realname_course:
        if not isinstance(roster_raw, dict) or not roster_raw.get("confirmed_for_course_submission"):
            raise ValueError("课程实名提交版要求 .local/member-privacy-roster.json 中 confirmed_for_course_submission=true")
    validated = validate_dataset(dataset)
    if validated["status"] != "ok":
        raise ValueError("Frozen dataset validation failed")
    manifest = read_json(dataset / "manifest.json")
    if manifest["repo"] != "pallets/itsdangerous":
        raise ValueError("Wrong course dataset")
    for filename in ("extraction-summary.json", "extraction-audit.json", "qa-summary.json",
                     "portable-rehearsal.json", "retrieval-recheck.json"):
        if not (EXPERIMENT / filename).is_file():
            raise ValueError(f"Missing accepted experiment receipt: {filename}")
    default_deck = FINAL / ("ItsDangerous-期末汇报_实名提交版.pptx" if realname_course else "ItsDangerous-期末汇报.pptx")
    default_pdf = ROOT / ("output/pdf/ItsDangerous-技术报告_实名提交版.pdf" if realname_course else "output/pdf/ItsDangerous-技术报告.pdf")
    default_md = ROOT / ("reports/itsdangerous_final_实名提交版.md" if realname_course else "reports/itsdangerous_final.md")
    public = {
        "README.md": FINAL / "ItsDangerous-操作与讲稿.md",
        "materials/ItsDangerous-期末汇报.pptx": deck or default_deck,
        "materials/ItsDangerous-技术报告.pdf": report_pdf or default_pdf,
        "materials/ItsDangerous-技术报告.md": report_md or default_md,
        "materials/itsdangerous.example.json": FINAL / "itsdangerous.example.json",
        "materials/itsdangerous-replay.json": replay,
        "materials/答辩追问应答小抄.md": FINAL / "答辩追问应答小抄.md",
        ".streamlit/config.toml": ROOT / ".streamlit/config.toml",
        "source/.streamlit/config.toml": ROOT / ".streamlit/config.toml",
    }
    report_root = public["materials/ItsDangerous-技术报告.md"].parent
    for name in ACTIVE_FIGURES:
        public["materials/figures/" + name] = report_root / "figures" / name
    for suffix in ("md", "json"):
        sample = FINAL / f"decision-ab-samples.{suffix}"
        if sample.is_file():
            public["materials/" + sample.name] = sample
    for rel in ("requirements.txt", "pyproject.toml", "THIRD_PARTY_NOTICES.md",
                "tools/serve_frozen.py"):
        public[f"source/{rel}"] = ROOT / rel
    for directory in ("app", "historykg"):
        for source in sorted((ROOT / directory).rglob("*.py")):
            public[f"source/{source.relative_to(ROOT).as_posix()}"] = source
    for file in sorted(EXPERIMENT.rglob("*.json")):
        public[f"evaluation/{file.relative_to(EXPERIMENT).as_posix()}"] = file
    if V2_EXPERIMENT.is_dir():
        for file in sorted(V2_EXPERIMENT.glob("*.json")):
            public[f"evaluation-v2/{file.name}"] = file
    public["source/tools/summarize.py"] = EXPERIMENT / "summarize.py"
    for member in ["manifest.json", *manifest["files"], "exports/discussion_input.json"]:
        source = dataset / member
        if not source.resolve().is_relative_to(dataset.resolve()):
            raise ValueError("Frozen file outside dataset")
        public[f"frozen/{member}"] = source
    missing_files = [k for k, f in public.items() if not (f.is_file() and not f.is_symlink())]
    if missing_files:
        raise ValueError(f"Missing required package files: {missing_files}")
    license_text = subprocess.check_output([
        "git", f"--git-dir={dataset / 'p3/history.git'}", "show",
        "672971d66a2ef9f85151e53283113f33d642dabd:LICENSE.txt",
    ])

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(".partial")
    hashes = {}
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
        def write(name, body):
            assert_public_member(name)
            archive.writestr(name, body)
            hashes[name] = hashlib.sha256(body).hexdigest()

        for name, source in sorted(public.items()):
            if name == "frozen/manifest.json":
                portable_manifest = {**manifest, "collection": dict(manifest.get("collection", {}))}
                portable_manifest["collection"].pop("capture_path", None)
                body = json.dumps(portable_manifest, ensure_ascii=False, indent=2).encode() + b"\n"
            else:
                body = source.read_bytes()
            write(name, body)
        write("materials/ItsDangerous-LICENSE.txt", license_text)
        source_snapshot = [item for item in sorted(hashes.items()) if item[0].startswith("source/")]
        write("PACKAGE.json", json.dumps({
            "package_status": package_status,
            "local_course_submission_only": realname_course,
            "member_roster_checked": roster is not None,
            "member_roster_confirmed": bool(
                isinstance(roster_raw, dict) and roster_raw.get("confirmed_for_course_submission")
            ),
            "dataset_id": manifest["dataset_id"], "repo": manifest["repo"],
            "source_snapshot_sha256": hashlib.sha256(
                json.dumps(source_snapshot, separators=(",", ":")).encode()).hexdigest(),
        }, ensure_ascii=False, indent=2).encode())
        archive.writestr("SHA256SUMS.json", json.dumps(hashes, ensure_ascii=False, indent=2))
    with ZipFile(temporary) as archive:
        if archive.testzip() is not None or any(
            hashlib.sha256(archive.read(name)).hexdigest() != h for name, h in hashes.items()
        ):
            raise ValueError("Package digest verification failed")
    scan_result = _scan_realname_archive(temporary, roster) if realname_course else scan_zip(temporary, roster=roster)
    if not scan_result["passed"]:
        raise ValueError(json.dumps(scan_result["errors"], ensure_ascii=False))
    if not scan_result["member_roster_checked"]:
        print("成员信息未核验（未加载私有名单）")
    temporary.replace(out)
    print(json.dumps({"out": str(out), "package_status": package_status,
                      "verified_members": len(hashes),
                      "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--report-pdf", type=Path)
    parser.add_argument("--deck", type=Path)
    parser.add_argument("--package-status", choices=(CANDIDATE, REHEARSAL, REALNAME_COURSE), default=CANDIDATE)
    parser.add_argument("--realname-course", action="store_true",
                        help="Build local-only real-name course submission package (must stay outside public git).")
    parser.add_argument("--require-roster", action="store_true", default=True)
    parser.add_argument("--allow-missing-roster", action="store_true")
    args = parser.parse_args()
    build(args.dataset.resolve(strict=True), args.out, args.replay.resolve(strict=True),
          report_md=args.report_md, report_pdf=args.report_pdf, deck=args.deck,
          require_roster=args.require_roster and not args.allow_missing_roster,
          package_status=args.package_status, realname_course=args.realname_course)


if __name__ == "__main__":
    main()
