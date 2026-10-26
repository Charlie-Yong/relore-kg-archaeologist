"""Regression scenarios for the planning check; no project runtime or API calls."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('planning_check', Path(__file__).with_name('check_planning.py'))
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class PlanningCheckTests(unittest.TestCase):
    def run_check(self, p1_status='状态：todo。\n', args=()):
        original = Path.read_text

        def read(path, *read_args, **kwargs):
            if path.parent == CHECK.ROOT / 'coordination' and re.fullmatch(r'STATUS_P[1-6]\.md', path.name):
                return p1_status if path.name == 'STATUS_P1.md' else '状态：todo。\n'
            return original(path, *read_args, **kwargs)

        output = io.StringIO()
        with patch.object(Path, 'read_text', read), patch.object(sys, 'argv', ['check_planning.py', *args]), redirect_stdout(output):
            with self.assertRaises(SystemExit) as result:
                CHECK.main()
        return result.exception.code, json.loads(output.getvalue())

    def test_normal_progress_accepts_all_six_states(self):
        for state in sorted(CHECK.VALID_STATES):
            with self.subTest(state=state):
                code, report = self.run_check(f'状态：{state}。\n')
                self.assertEqual(code, 0, report['errors'])
                self.assertEqual(report['role_states']['P1'], state)
                self.assertFalse(report['runtime_system_tested'])

    def test_invalid_or_empty_status_is_rejected(self):
        for text in ['状态：started。\n', '状态：\n']:
            with self.subTest(text=text):
                code, report = self.run_check(text)
                self.assertEqual(code, 1)
                self.assertIn('P1: invalid module status', report['errors'])

    def test_duplicate_status_is_rejected(self):
        code, report = self.run_check('状态：todo。\n状态：in_progress。\n')
        self.assertEqual(code, 1)
        self.assertIn('P1: expected exactly one status field', report['errors'])

    def test_missing_status_is_rejected(self):
        code, report = self.run_check('下一步：开始实施。\n')
        self.assertEqual(code, 1)
        self.assertIn('P1: expected exactly one status field', report['errors'])

    def test_initial_snapshot_is_explicit_and_optional(self):
        code, _ = self.run_check(args=('--initial-snapshot',))
        self.assertEqual(code, 0)
        code, report = self.run_check('状态：in_progress。\n', args=('--initial-snapshot',))
        self.assertEqual(code, 1)
        self.assertIn('P1: initial snapshot requires todo', report['errors'])

    def test_report_date_uses_execution_time_in_beijing(self):
        class LaterDate(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2030, 5, 6, 23, 45, tzinfo=timezone.utc).astimezone(tz)

        with patch.object(CHECK, 'datetime', LaterDate):
            code, report = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(report['checked_date'], '2030-05-07')
        self.assertTrue(report['checked_at'].endswith('+08:00'))

    def test_runtime_and_private_markdown_are_not_read(self):
        original = Path.rglob
        excluded = [CHECK.ROOT / '.venv' / 'README.md', CHECK.ROOT / 'evaluation' / 'private_test' / 'reference.md']

        def rglob(path, pattern):
            yield from original(path, pattern)
            if path == CHECK.ROOT:
                yield from excluded

        # These nonexistent paths would fail if the checker attempted to read them.
        with patch.object(Path, 'rglob', rglob):
            code, report = self.run_check()
        self.assertEqual(code, 0, report['errors'])


if __name__ == '__main__':
    unittest.main()
