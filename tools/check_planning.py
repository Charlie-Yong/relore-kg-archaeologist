#!/usr/bin/env python3
"""Check planning documents and legal module states without running the system."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '<!-- BEGIN COMMON CONTRACT -->'
END = '<!-- END COMMON CONTRACT -->'
VALID_STATES = {'todo', 'in_progress', 'blocked', 'ready_for_integration', 'verified_real', 'done'}
EXCLUDED_ROOTS = {'.git', '.venv', 'venv', 'node_modules', 'data', 'clones', '.local', 'submission', 'vendor'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, help='Optional JSON check report')
    parser.add_argument('--initial-snapshot', action='store_true', help='Also require all modules to remain todo for an initial planning snapshot')
    args = parser.parse_args()
    errors = []
    contract = (ROOT / '01_统一执行契约.md').read_text(encoding='utf-8').rstrip() + '\n'
    versions = re.search(r'规划\s*(v[\d.]+)｜契约\s*([\d.]+)', contract)
    if versions is None:
        raise SystemExit('Missing planning/contract versions')
    planning_version, contract_version = versions.groups()
    report_path = None if args.report is None else (args.report if args.report.is_absolute() else ROOT / args.report)
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
        if f'规划{planning_version}｜契约{contract_version}' not in text:
            errors.append(f'{path.name}: stale version header')
        if text.count('<!-- BEGIN AUTO START -->') != 1 or text.count('<!-- END AUTO START -->') != 1:
            errors.append(f'{path.name}: missing automatic-start section')
        else:
            boot = text.split('<!-- BEGIN AUTO START -->', 1)[1].split('<!-- END AUTO START -->', 1)[0]
            for term in [f'自动开工：{role}第一轮', '0. **先讲清项目原理。**', '公共契约C0', f'STATUS_{role}.md', f'feat/{role.lower()}', '本轮首个可运行产物', '最小接管', '恢复']:
                if term not in boot:
                    errors.append(f'{path.name}: automatic-start section missing {term}')
        tasks = text.split('<!-- BEGIN ROLE TASKS -->', 1)[-1]
        if len(tasks) < 2000:
            errors.append(f'{path.name}: role tasks unexpectedly short')
        role_checks.append({'role': role, 'file': path.name, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
    required = ['2026-10-26', '11-11', '12-20', 'DeepSeek', 'GPT', '5000', 'QueryResult_v1', 'reference/judge', 'ReachableIn', 'MentionsPR']
    for term in required:
        if term not in contract:
            errors.append(f'Contract missing expected requirement: {term}')
    for term in ['C0. 开工前必须向成员讲清项目原理', '先讲清项目原理', 'C3.1', 'C3.2', '人工接管', '无须额外启动提示', '所属AI当轮登记', '已批准预算', '离线电脑']:
        if term not in contract:
            errors.append(f'Contract missing autonomy requirement: {term}')
    link_count = 0
    documents = [
        path for path in sorted(ROOT.rglob('*.md'))
        if path.relative_to(ROOT).parts[0] not in EXCLUDED_ROOTS
        and path.relative_to(ROOT).parts[:2] != ('evaluation', 'private_test')
    ]
    for path in documents:
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
            if not target.exists() and (report_path is None or target.resolve() != report_path.resolve()):
                errors.append(f'{path.relative_to(ROOT)}: missing link {href}')
        for forbidden in ['pandas-kg-archaeologist', 'pandas-dev/pandas', 'DataFrame.append', 'Series.append', 'PR 5774', '`ReleasedIn`', '四页骨架', '四页联调']:
            if forbidden in text:
                errors.append(f'{path.relative_to(ROOT)}: stale or inconsistent term {forbidden}')
        if re.search(r'/Users/|[A-Z]:\\Users\\', text):
            errors.append(f'{path.relative_to(ROOT)}: personal absolute path')
        if 'deliveries' not in path.relative_to(ROOT).parts:
            for term in ['由成员转交P1', '由成员转P1', '由成员转给P1', '在后续实施阶段先实现', '后续先实现']:
                if term in text:
                    errors.append(f'{path.relative_to(ROOT)}: unnecessary human relay or deferred start: {term}')
    role_states = {}
    for n in range(1, 7):
        p = ROOT / f'coordination/STATUS_P{n}.md'
        if not p.exists():
            errors.append(f'P{n}: missing status file')
            continue
        fields = re.findall(r'^状态[：:][ \t]*(.*)$', p.read_text(encoding='utf-8'), flags=re.M)
        if len(fields) != 1:
            errors.append(f'P{n}: expected exactly one status field')
            continue
        match = re.fullmatch(r'([a-z_]+)[。.]?', fields[0].strip())
        state = match.group(1) if match else None
        if state not in VALID_STATES:
            errors.append(f'P{n}: invalid module status')
            continue
        role_states[f'P{n}'] = state
        if args.initial_snapshot and state != 'todo':
            errors.append(f'P{n}: initial snapshot requires todo')
    checked_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    report = {
        'checked_date': checked_at[:10], 'checked_at': checked_at,
        'planning_version': planning_version, 'contract_version': contract_version,
        'contract_sha256': digest,
        'markdown_files': len(documents), 'local_links_checked': link_count,
        'workorders': role_checks, 'errors': errors,
        'role_states': role_states, 'initial_snapshot': args.initial_snapshot,
        'passed': not errors, 'runtime_system_tested': False,
        'note': 'Checks planning documents only; no model, ingestion, graph or course experiment was executed.'
    }
    if report_path:
        destination = report_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
