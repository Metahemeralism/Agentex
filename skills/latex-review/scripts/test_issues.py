"""Run: python3 -m unittest discover -s skills/latex-review/scripts"""
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import issues

REVIEW = """Official Review of Submission 1234 by Reviewer xY7z

Summary:
The paper proposes a sparse attention method for long documents.

Strengths:
1. Clear writing and a well motivated problem.
2. Strong results on two benchmarks.

Weaknesses:
The paper has the following weaknesses:
1. The baselines are weak: no comparison with Longformer or BigBird,
   which are the obvious competitors.
   - in particular the 16k setting is missing
2. Results use a single seed, so the 0.4 point gain may be noise.
3. Minor: the font in Figure 2 is too small to read.

Questions:
- How sensitive is the method to the window size w?
- N/A

Rating: 5: marginally below the acceptance threshold
Confidence: 4
"""


def run_cli(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = issues.main([str(a) for a in argv])
    return code, buf.getvalue()


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'sec').mkdir()
        (self.root / 'sec' / 'exp.tex').write_text('\\section{Experiments}\nWe win.\n')
        (self.root / 'main.tex').write_text('\\documentclass{article}\n\\begin{document}\n\\input{sec/exp}\n\\end{document}\n')

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *argv):
        return run_cli('--project', self.root, *argv)

    def ledger(self):
        return json.loads((self.root / '.agentex' / 'issues.json').read_text())

    def test_stable_ids_and_dedupe(self):
        a = issues.issue_id('self', 'The baselines are weak.')
        self.assertEqual(a, issues.issue_id('self', '  the BASELINES are weak '))
        self.assertNotEqual(a, issues.issue_id('reviewer:R2', 'The baselines are weak.'))
        self.assertTrue(issues.issue_id('reviewer:R2', 'x').startswith('R2-'))
        code, out = self.cli('add', '--source', 'self', '--anchor', 'sec/exp.tex:2', '--severity', 'major',
                             '--text', 'The baselines are weak.')
        self.assertEqual((code, out.strip()), (0, f'added {a}'))
        code, out = self.cli('add', '--source', 'self', '--anchor', 'sec/exp.tex:2', '--severity', 'minor',
                             '--text', 'the baselines are WEAK')
        self.assertIn(f'exists {a}', out)
        self.assertEqual(len(self.ledger()['issues']), 1)
        self.assertEqual(self.cli('add', '--source', 'self', '--anchor', 'nope.tex:1', '--severity', 'major',
                                  '--text', 'x')[0], 2)  # anchor file must exist
        self.assertEqual(self.cli('add', '--source', 'bob', '--anchor', 'main.tex', '--severity', 'major',
                                  '--text', 'x')[0], 2)

    def test_verdict_fix_status_and_stop(self):
        def add(text, sev='major'):
            return self.cli('add', '--source', 'self', '--anchor', 'sec/exp.tex:2', '--severity', sev,
                            '--text', text)[1].split()[-1]
        weak, seeds, typo = add('Baselines are weak.'), add('Single seed only.'), add('Typo in Eq. 3.', 'minor')
        code, out = self.cli('stop')
        self.assertEqual(code, 1)
        self.assertIn('round 1 raised 2 new major', out)  # the minor one doesn't count
        self.assertIn('without a verdict', out)

        self.assertEqual(self.cli('fix', weak)[0], 2)  # no verdict yet: refuse to edit
        self.cli('verdict', weak, 'fixable', '--note', 'add Longformer row')
        self.cli('verdict', seeds, 'author', '--note', 'needs 3 more GPU days')
        self.assertEqual(self.cli('fix', seeds)[0], 2)  # author-required issues are never edited
        status = json.loads((self.root / '.agentex' / 'status' / 'review.json').read_text())
        self.assertEqual(set(status), {'tool', 'status', 'summary', 'counts', 'items', 'updated'})
        self.assertEqual((status['tool'], status['status']), ('review', 'fail'))  # weak is fixable, not fixed
        self.assertEqual(status['counts'], {'open major': 1, 'open minor': 1, 'author-required': 1, 'round': 1})
        self.assertLessEqual(len(status['summary']), 100)

        self.cli('fix', weak, '--commit', 'abc1234')
        self.assertEqual(self.ledger()['issues'][weak]['commits'], ['abc1234'])
        code, out = self.cli('stop')
        self.assertEqual(code, 1)  # round 1 raised new majors: one more round must confirm
        self.assertIn('round 1 raised 2 new major', out)

        self.assertIn('round 2 started', self.cli('round')[1])
        add('Baselines are weak.')  # re-raised in round 2: deduped, so not new
        code, out = self.cli('stop')
        self.assertEqual(code, 0, out)
        self.assertIn('done: round 2', out)
        self.assertIn(seeds, out)  # author-required items are reported
        _, out = self.cli('list', '--open')
        self.assertIn(typo, out)
        self.assertNotIn(weak, out)

        self.cli('reopen', weak)
        self.assertIsNone(self.ledger()['issues'][weak]['verdict'])
        self.assertEqual(self.cli('stop')[0], 1)
        self.cli('round')
        code, out = self.cli('stop')  # round 3 = cap
        self.assertEqual(code, 0)
        self.assertIn('cap reached', out)

    def test_self_issue_cap(self):
        with mock.patch.object(issues, 'MAX_SELF_PER_ROUND', 2):
            for n in range(2):
                self.cli('add', '--source', 'self', '--anchor', 'main.tex', '--severity', 'minor', '--text', f'issue {n}')
            code, out = self.cli('add', '--source', 'self', '--anchor', 'main.tex', '--severity', 'minor', '--text', 'three')
        self.assertEqual(code, 1)
        self.assertIn('cap', out)

    def test_import_reviews(self):
        points = issues.parse_review(REVIEW)
        texts = [t for _, t in points]
        self.assertEqual(len(points), 4, texts)  # 3 weaknesses + 1 question; strengths, N/A and scores skipped
        self.assertTrue(texts[0].startswith('The baselines are weak'))
        self.assertIn('16k setting', texts[0])  # nested bullet stays with its parent
        self.assertEqual([s for s, _ in points], ['major', 'major', 'minor', 'major'])
        self.assertFalse(any('Clear writing' in t or 'following weaknesses' in t for t in texts))
        self.assertEqual(len(issues.parse_review('The proof of Lemma 2 assumes convexity.\n\nTable 3 lacks std.\n')), 2)

        f = self.root / 'R2.txt'
        f.write_text(REVIEW)
        code, out = self.cli('import-reviews', f)
        self.assertEqual(code, 0)
        self.assertIn('R2: 4 new point(s) (3 major)', out)
        self.assertIn('4 already in the ledger', self.cli('import-reviews', f)[1])  # idempotent
        self.assertEqual({i['source'] for i in self.ledger()['issues'].values()}, {'reviewer:R2'})
        iid = next(iter(self.ledger()['issues']))
        self.cli('verdict', iid, 'fixable', '--anchor', 'sec/exp.tex:2')
        self.assertEqual(self.ledger()['issues'][iid]['anchor'], 'sec/exp.tex:2')
        self.assertEqual(self.cli('list', '--source', 'reviewer:R2')[1].count('R2-'), 4)
        self.assertIn('0 shown', self.cli('list', '--source', 'self')[1])


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'main.tex').write_text('\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n')
        self.skills = self.root / 'skills'
        for rel in ('latex-debug/scripts/build.py', 'latex-references/scripts/check_refs.py',
                    'latex-results-sync/scripts/results.py'):
            (self.skills / rel).parent.mkdir(parents=True)
            (self.skills / rel).write_text('')

    def tearDown(self):
        self.tmp.cleanup()

    def guard(self, outputs):
        def fake_run(cmd, **kw):
            rc, out = outputs[Path(cmd[1]).name]
            return subprocess.CompletedProcess(cmd, rc, out, '')
        with mock.patch.object(issues, 'SKILLS', self.skills), mock.patch('subprocess.run', fake_run):
            return run_cli('--project', self.root, 'guard')

    def test_all_pass_and_claims_absent(self):
        code, out = self.guard({'build.py': (0, 'OK main.pdf | 1 pages | latexmk pdflatex\nclean'),
                                'check_refs.py': (0, '\n0 error(s).'),
                                'results.py': (1, 'HARD-CODED main.tex:3  42\nstale 0 · undefined 0 · hard-coded 1')})
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertEqual([l.split()[:2] for l in lines], [['PASS', 'build'], ['PASS', 'refs'], ['PASS', 'results'],
                                                          ['SKIP', 'claims']])
        self.assertIn('not installed', lines[3])

    def test_failures(self):
        (self.skills / 'latex-consistency' / 'scripts').mkdir(parents=True)
        (self.skills / 'latex-consistency' / 'scripts' / 'claims.py').write_text('')
        code, out = self.guard({'build.py': (1, 'FAILED main.tex (latexmk pdflatex)\nmain.tex:3: Undefined control sequence'),
                                'check_refs.py': (0, '0 error(s).'),
                                'results.py': (1, 'STALE main.tex:3 87.3\nstale 1 · undefined 0 · hard-coded 0'),
                                'claims.py': (1, 'CHANGED C2 sec/intro.tex:4 "we outperform all baselines"')})
        self.assertEqual(code, 1)
        states = {l.split()[1]: l.split()[0] for l in out.splitlines() if l[:4] in ('PASS', 'FAIL', 'SKIP')}
        self.assertEqual(states, {'build': 'FAIL', 'refs': 'PASS', 'results': 'FAIL', 'claims': 'FAIL'})
        self.assertIn('Undefined control sequence', out)  # the failing digest is shown, briefly

    def test_no_engine_is_skip(self):
        code, out = self.guard({'build.py': (2, 'no TeX engine: install TeX Live'), 'check_refs.py': (0, '0 error(s).'),
                                'results.py': (0, 'stale 0 · undefined 0 · hard-coded 0')})
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('SKIP build'))


if __name__ == '__main__':
    unittest.main()
