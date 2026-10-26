#!/usr/bin/env python3
"""Synchronize the complete shared contract embedded in all six work orders."""
from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '<!-- BEGIN COMMON CONTRACT -->'
END = '<!-- END COMMON CONTRACT -->'


def main():
    contract = (ROOT / '01_统一执行契约.md').read_text(encoding='utf-8').rstrip() + '\n'
    digest = hashlib.sha256(contract.encode('utf-8')).hexdigest()
    paths = sorted(ROOT.glob('P[1-6]_*.md'))
    if len(paths) != 6:
        raise SystemExit('Expected exactly six work orders')
    for path in paths:
        current = path.read_text(encoding='utf-8')
        if current.count(BEGIN) != 1 or current.count(END) != 1:
            raise SystemExit(f'Invalid common-section markers: {path.name}')
        before, rest = current.split(BEGIN, 1)
        _, after = rest.split(END, 1)
        before = re.sub(r'公共契约 SHA-256：[^\n]+', '公共契约 SHA-256：' + digest, before)
        result = before + BEGIN + '\n' + contract + END + after
        if result != current:
            with path.open('w', encoding='utf-8', newline='\n') as stream:
                stream.write(result)
    print(f'Synchronized {len(paths)} work orders; contract SHA-256 {digest}')


if __name__ == '__main__':
    main()
