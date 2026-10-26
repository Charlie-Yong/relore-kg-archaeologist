#!/usr/bin/env python3
"""Check document links, standalone work orders and honest initial module states."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import argparse
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '<!-- BEGIN COMMON CONTRACT -->'
END = '<!-- END COMMON CONTRACT -->'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, help='Optional JSON check report')
    args = parser.parse_args()
    errors = []
    contract = (ROOT / '01_统一执行契约.md').read_text(encoding='utf-8').rstrip() + '\n'
    digest = hashlib.sha256(contract.encode('utf-8')).hexdigest()
    paths = sorted(ROOT.glob('P[1-6]_*.md'))
    if len(paths) != 6:
        errors.append('Expected six work orders')
    role_checks = []
    for path in paths:
        text = path.read_text(encoding='utf-8')
        role = path.name[:2]
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            errors.append(f'{path.name}: invalid markers')
            continue
        embedded = text.split(BEGIN + '\n', 1)[1].split(END, 1)[0]
        if embedded != contract:
            errors.append(f'{path.name}: common section differs')
        if f'公共契约 SHA-256：{digest}' not in text:
            errors.append(f'{path.name}: wrong contract hash')
        if f'你已被分配为{role}' not in text or '<!-- BEGIN ROLE TASKS -->' not in text:
            errors.append(f'{path.name}: missing standalone assignment/tasks')
        tasks = text.split('<!-- BEGIN ROLE TASKS -->', 1)[-1]
        if len(tasks) < 2000:
            errors.append(f'{path.name}: role tasks unexpectedly short')
        role_checks.append({'role': role, 'file': path.name, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
    required = ['2026-10-26', '11-11', '12-20', 'DeepSeek', 'GPT', '5000', 'QueryResult_v1', 'reference/judge', 'ReachableIn', 'MentionsPR']
    for term in required:
        if term not in contract:
            errors.append(f'Contract missing expected requirement: {term}')
    link_count = 0
    documents = sorted(ROOT.rglob('*.md'))
    for path in documents:
        if '.git' in path.parts:
            continue
        text = path.read_text(encoding='utf-8')
        # Code examples can contain placeholder paths and are not navigation links.
        prose = re.sub(r'(?ms)^(```|~~~).*?^\1\s*$', '', text)
        for match in re.finditer(r'(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)', prose):
            href = match.group(1).strip().strip('<>')
            parsed = urlsplit(href)
            if parsed.scheme or href.startswith('#'):
                continue
            target = path.parent / unquote(parsed.path)
            link_count += 1
            if not target.exists():
                errors.append(f'{path.relative_to(ROOT)}: missing link {href}')
        for forbidden in ['pandas-kg-archaeologist', 'pandas-dev/pandas', 'DataFrame.append', 'Series.append', 'PR 5774', '`ReleasedIn`', '四页骨架', '四页联调']:
            if forbidden in text:
                errors.append(f'{path.relative_to(ROOT)}: stale or inconsistent term {forbidden}')
        if re.search(r'/Users/|[A-Z]:\\Users\\', text):
            errors.append(f'{path.relative_to(ROOT)}: personal absolute path')
    for n in range(1, 7):
        p = ROOT / f'coordination/STATUS_P{n}.md'
        if not p.exists() or '状态：todo' not in p.read_text(encoding='utf-8'):
            errors.append(f'P{n}: initial implementation status must be todo')
    report = {
        'checked_date': '2026-10-26',
        'planning_version': 'v1.0', 'contract_version': '1.0.0',
        'contract_sha256': digest,
        'markdown_files': len(documents), 'local_links_checked': link_count,
        'workorders': role_checks, 'errors': errors,
        'passed': not errors, 'runtime_system_tested': False,
        'note': 'Checks planning documents only; no model, ingestion, graph or course experiment was executed.'
    }
    if args.report:
        destination = args.report if args.report.is_absolute() else ROOT / args.report
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
