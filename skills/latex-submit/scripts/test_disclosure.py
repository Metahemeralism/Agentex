"""Run: python3 -m unittest discover -s skills/latex-submit/scripts -p test_disclosure.py"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disclosure  # noqa: E402

LOG = [{'time': '2026-10-01T09:00:00Z', 'file': 'paper/sections/intro.tex', 'tool': 'Edit', 'added_lines': 30,
        'removed_lines': 5, 'section': 'Introduction'},
       {'time': '2026-10-03T09:00:00Z', 'file': 'paper/sections/method.tex', 'tool': 'Write', 'added_lines': 50,
        'removed_lines': 0}]


class DisclosureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()  # macOS: /var -> /private/var
        (self.root / '.git').mkdir()
        self.paper = self.root / 'paper'
        (self.paper / '.agentex').mkdir(parents=True)
        (self.paper / 'main.tex').write_text('\\section{Intro}\n' + 'Accuracy is \\res{acc}.\n' * 199)
        (self.paper / '.agentex' / 'cite-cache.json').write_text(json.dumps(
            {'keys': {'a': {'status': 'verified'}, 'b': {'status': 'published'}, 'c': {'status': 'unverifiable'}}}))
        (self.paper / '.agentex' / 'build-state.json').write_text('{}')
        (self.root / '.agentex').mkdir()  # the hook logs in the session folder, above the paper
        (self.root / '.agentex' / 'activity.jsonl').write_text('\n'.join(map(json.dumps, LOG)) + '\n{"truncated\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_draft(self):
        with mock.patch.object(disclosure, 'git_counts', return_value=(7, 3)):
            text = disclosure.draft(self.paper)
        self.assertTrue(text.startswith('% DRAFT'))
        for want in ('Between 2026-10-01 and 2026-10-03', '2 edits to 2 source files', 'Introduction',
                     'adding 80 and removing 5 lines', 'at most about 40\\% of the current 200 lines',
                     '3 of the 7 commits', '3 references were checked', '2 matched automatically',
                     'say how the others were checked', '199 uses', 'recompiled', '[AUTHORS: model name'):
            self.assertIn(want, text)

    def test_no_log(self):
        (self.root / '.agentex' / 'activity.jsonl').unlink()
        with mock.patch.object(disclosure, 'git_counts', return_value=None):
            text = disclosure.draft(self.paper)
        self.assertIn('no agent edits were logged', text)
        self.assertNotIn('commits', text)

    def test_find_up_stops_at_git_root(self):
        self.assertEqual(disclosure.find_up(self.paper, '.agentex/activity.jsonl'), self.root / '.agentex' / 'activity.jsonl')
        self.assertIsNone(disclosure.find_up(self.paper, 'nowhere.txt'))
        self.assertEqual(len(disclosure.read_activity(self.paper)), 2)  # the half-written line is skipped
        self.assertEqual(disclosure.agentex_root(self.paper), self.paper)

    @unittest.skipUnless(shutil.which('git'), 'needs git')
    def test_git_counts(self):
        with tempfile.TemporaryDirectory() as d:
            git = ['git', '-c', 'user.name=T', '-c', 'user.email=t@example.org', '-c', 'commit.gpgsign=false']
            subprocess.run(['git', 'init', '-q', d], check=True)
            for i, msg in enumerate(['first', 'second\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>']):
                Path(d, 'main.tex').write_text(f'v{i}\n')
                subprocess.run(git + ['-C', d, 'add', '.'], check=True)
                subprocess.run(git + ['-C', d, 'commit', '-q', '-m', msg], check=True)
            self.assertEqual(disclosure.git_counts(Path(d)), (2, 1))


if __name__ == '__main__':
    unittest.main()
