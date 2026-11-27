"""Inspect the exact bytes to be shared, without printing sensitive matches."""

import argparse
import getpass
import io
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

USER_PATH = re.compile(r"(?:/Users/([\w.-]+)/|[A-Z]:\\+Users\\+([\w.-]+)\\+)", re.I)
CREDENTIAL = re.compile(r"(?:\bgh[pousr]_[a-z0-9]{30,}\b|\bgithub_pat_[a-z0-9_]{40,}\b|"
                        r"\bsk-[a-z0-9]{25,}\b|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----)", re.I)
PRIVATE_PPT = "demo/midterm/期中汇报_科研架构详解版_20261111.pptx"
UPSTREAM = {"frozen/sources.jsonl", "frozen/p1/evidence.jsonl",
            "frozen/exports/discussion_input.json"}
HISTORICAL_LINES = {
    ("deliveries/P1/2026-10-30/final_package.json", 2),
    ("deliveries/P4/2026-10-30/model_validation.json", 222),
    ("deliveries/P5/2026-10-30/final_presentation_validation.json", 6),
    ("evaluation/results/cross_source_chain.json", 54),
    ("deliveries/P3/2026-10-30/developer_function_validation.json", 92),
    ("deliveries/P3/2026-10-30/developer_function_validation.json", 107),
    ("demo/replay/flask-public-20261030.json", 5645),
    ("demo/replay/flask-public-20261030.json", 5669),
    ("demo/replay/flask-public-20261030.json", 22694),
    ("demo/replay/flask-public-20261030.json", 22718),
}


def _texts(name, data):
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".pptx":
        with ZipFile(io.BytesIO(data)) as deck:
            for item in deck.namelist():
                if item.endswith((".xml", ".rels")):
                    yield item, deck.read(item).decode("utf-8")
    elif suffix == ".pdf":
        # The host PDF reader decodes embedded font mappings before matching.
        result = subprocess.run(
            ["/usr/bin/python3", "-c",
             "import io,sys; from pypdf import PdfReader; "
             "print('\u000c'.join(p.extract_text() for p in PdfReader(io.BytesIO(sys.stdin.buffer.read())).pages))"],
            input=data, capture_output=True, check=True,
        )
        yield "", result.stdout.decode("utf-8")
    elif b"\0" not in data[:8192]:
        try:
            yield "", data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return


def _prohibited(name):
    path = PurePosixPath(name)
    return (name == PRIVATE_PPT or "_实名提交版." in path.name
            or bool({".local", "submission", ".git", ".venv", "clones"} & set(path.parts))
            or "evaluation/private_test/" in name
            or (path.name.startswith(".env") and path.name != ".env.example")
            or path.suffix.lower() in {".pem", ".key"})


def scan(members, *, roster=None, tracked=False, frozen_sources=None):
    errors, review = [], set()
    user = getpass.getuser().casefold()
    identities = [(str(m["name"]), str(m["student_id"])) for m in roster] if roster else []
    for name, content in members:
        if _prohibited(name):
            errors.append({"file": name, "reason": "private_path"})
            continue
        try:
            for inner, body in _texts(name, content):
                reasons = set()
                if CREDENTIAL.search(body):
                    reasons.add("credential")
                text = re.sub(r"<[^>]+>", "", body) if inner else body
                if any(n in text or re.search(r"(?<!\d)" + re.escape(i) + r"(?!\d)", text)
                       for n, i in identities):
                    reasons.add("member_identity")
                inspect_paths = body
                if frozen_sources is not None and name in {
                    "frozen/p3/sources.jsonl", "frozen/p3/evidence.jsonl",
                    "materials/itsdangerous-replay.json",
                }:
                    inspect_paths, reviewed = verify_upstream_paths(
                        name, body, frozen_sources, user
                    )
                    if reviewed:
                        review.add((name, "upstream_path"))
                for line_number, line in enumerate(inspect_paths.splitlines(), 1):
                    for match in USER_PATH.finditer(line):
                        if tracked and (name, line_number) in HISTORICAL_LINES:
                            review.add((name, "historical_path"))
                        elif name in UPSTREAM and (match[1] or match[2]).casefold() != user:
                            review.add((name, "upstream_path"))
                        else:
                            reasons.add("user_path")
                for reason in sorted(reasons):
                    errors.append({"file": name, "part": inner, "reason": reason})
        except (OSError, ValueError, TypeError, KeyError, BadZipFile, subprocess.CalledProcessError) as exc:
            errors.append({"file": name, "reason": f"parse_failed:{type(exc).__name__}"})
    return {"passed": not errors, "member_roster_checked": bool(roster),
            "errors": errors, "review": [{"file": n, "reason": r} for n, r in sorted(review)]}


def verify_upstream_paths(name, body, sources, user):
    def allowed(row, field):
        nonlocal reviewed
        value = row.get(field, "")
        if not isinstance(value, str) or not USER_PATH.search(value):
            return
        source = sources.get(row.get("source_id")) or {}
        original = source.get("text", "")
        link = source.get("url", "")
        if not link.startswith(("https://api.github.com/", "https://github.com/",
                                "https://raw.githubusercontent.com/")):
            return
        if field == "quote":
            start, end = row.get("start"), row.get("end")
            if not (isinstance(start, int) and isinstance(end, int)
                    and 0 <= start <= end <= len(original) and value == original[start:end]):
                return
        row[field], count = USER_PATH.subn(
            lambda match: match[0] if (match[1] or match[2]).casefold() == user else "",
            value,
        )
        reviewed |= count > 0

    reviewed = False
    if name.endswith(".jsonl"):
        rows = [json.loads(line) for line in body.splitlines() if line]
        for row in rows:
            allowed(row, "text" if name.endswith("/sources.jsonl") else "quote")
        return "\\n".join(json.dumps(row, ensure_ascii=False) for row in rows), reviewed
    replay = json.loads(body)
    for query in replay.get("queries", []):
        for row in query.get("evidence", []):
            allowed(row, "quote")
    return json.dumps(replay, ensure_ascii=False), reviewed


def scan_zip(path, roster=None):
    with ZipFile(path) as archive:
        sources = {}
        for name in ("frozen/sources.jsonl", "frozen/p3/sources.jsonl"):
            if name in archive.namelist():
                for line in archive.read(name).splitlines():
                    row = json.loads(line)
                    sources[row["source_id"]] = row
        return scan(((i.filename, archive.read(i)) for i in archive.infolist()),
                    roster=roster, frozen_sources=sources)


def load_roster(path):
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    members = data["members"] if isinstance(data, dict) else data
    if (not isinstance(members, list) or len(members) != 6
            or any(not isinstance(m, dict) or not str(m.get("name", "")).strip()
                   or not re.fullmatch(r"\d{11}", str(m.get("student_id", ""))) for m in members)
            or len({str(m["student_id"]) for m in members}) != 6):
        raise ValueError("私有名单须包含六组姓名与学号。")
    return members


def git_members(staged):
    command = ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"] if staged else [
        "git", "ls-files", "-z"]
    for raw in filter(None, subprocess.check_output(command).split(b"\0")):
        name = raw.decode("utf-8")
        revision = ":" if staged else "HEAD:"
        yield name, subprocess.check_output(["git", "show", revision + name])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--tracked", action="store_true")
    group.add_argument("--zip", type=Path)
    parser.add_argument("--roster", type=Path, default=Path(".local/member-privacy-roster.json"))
    parser.add_argument("--require-roster", action="store_true")
    args = parser.parse_args()
    roster = load_roster(args.roster)
    if roster is None:
        print("成员信息未核验（未加载私有名单）")
    if args.zip:
        result = scan_zip(args.zip, roster)
    else:
        result = scan(git_members(args.staged), roster=roster, tracked=args.tracked)
    if args.require_roster and roster is None:
        result["errors"].append({"reason": "member_roster_required"})
        result["passed"] = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
