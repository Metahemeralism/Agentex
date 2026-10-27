"""Run: python3 -m unittest discover -s hooks -p test_activity_log.py"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import activity_log  # noqa: E402

DOC = '\\section{Intro}\nOld text.\n\\section{Method}\nWe use a new loss.\nMore.\n'


class ActivityLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tex = self.root / 'paper' / 'main.tex'
        self.tex.parent.mkdir()
        self.tex.write_text(DOC)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, data):
        with mock.patch('sys.stdin', io.StringIO(json.dumps(data))):
            self.assertEqual(activity_log.main(), 0)
        log = self.root / '.agentex' / 'activity.jsonl'
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def hook(self, tool, ti, tr=None):
        return {'cwd': str(self.root), 'tool_name': tool, 'tool_input': {'file_path': str(self.tex), **ti},
                'tool_response': tr or {}}

    def test_edit_fallback_counts_and_section(self):
        recs = self.call(self.hook('Edit', {'old_string': 'Old loss.', 'new_string': 'We use a new loss.\nMore.'}))
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual((r['file'], r['tool'], r['added_lines'], r['removed_lines']), ('paper/main.tex', 'Edit', 2, 1))
        self.assertEqual(r['section'], 'Method')
        self.assertRegex(r['time'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertEqual((self.root / '.agentex' / '.gitignore').read_text(), '*\n')

    def test_structured_patch_wins(self):
        tr = {'structuredPatch': [{'lines': [' ctx', '-a', '-b', '+c']}, {'lines': ['+d', '+e']}]}
        r = self.call(self.hook('Edit', {'old_string': 'x', 'new_string': 'y'}, tr))[0]
        self.assertEqual((r['added_lines'], r['removed_lines']), (3, 2))

    def test_multiedit_and_write(self):
        r = self.call(self.hook('MultiEdit', {'edits': [{'old_string': 'a', 'new_string': 'b\nc'},
                                                          {'old_string': '', 'new_string': 'd'}]}))[0]
        self.assertEqual((r['added_lines'], r['removed_lines']), (3, 1))
        r = self.call(self.hook('Write', {'content': 'one\ntwo\nthree\n'}))[1]
        self.assertEqual((r['tool'], r['added_lines'], r['removed_lines']), ('Write', 3, 0))
        self.assertNotIn('section', r)

    def test_ignored_and_safe(self):
        data = self.hook('Edit', {'old_string': 'a', 'new_string': 'b'})
        data['tool_input']['file_path'] = str(self.root / 'notes.md')
        self.assertEqual(self.call(data), [])
        self.assertEqual(self.call(self.hook('Read', {})), [])
        with mock.patch.dict(os.environ, {'AGENTEX_ACTIVITY_LOG': '0'}):
            self.assertEqual(self.call(self.hook('Edit', {'old_string': 'a', 'new_string': 'b'})), [])
        with mock.patch('sys.stdin', io.StringIO('not json')):
            self.assertEqual(activity_log.main(), 0)


if __name__ == '__main__':
    unittest.main()
