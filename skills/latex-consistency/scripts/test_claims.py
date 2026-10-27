"""Run: python3 -m unittest discover -s skills/latex-consistency/scripts"""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from claims import kinds, main, sentences
from test_settings_audit import make_project


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(argv))
    return code, out.getvalue()


class SentenceTest(unittest.TestCase):
    def test_split_and_skip(self):
        tex = ('\\documentclass{article}\\usepackage{x} We do not count preamble words here.\n\\begin{document}\n'
               '\\section{Intro} We compare to Smith et al. and to e.g. Adam in Fig. 2 here. Second sentence follows now.\n'
               '\\begin{equation} a = 1.5 \\end{equation}\n'
               '\\begin{figure}\\caption{Accuracy of all models on the test set.}\\end{figure}\n'
               '\\begin{tabular}{ll} lr & 0.1 \\\\ \\end{tabular}\n\\end{document}\n')
        got = sentences(tex)
        self.assertEqual([s for _, s in got], ['We compare to Smith et al. and to e.g. Adam in Fig. 2 here.',
                                               'Second sentence follows now.', 'Accuracy of all models on the test set.'])
        self.assertEqual([n for n, _ in got], [3, 3, 5])

    def test_kinds(self):
        self.assertEqual(kinds('Our model outperforms all baselines by 3.2 points.'), ['number', 'comparative'])
        self.assertEqual(kinds('We train the encoder with AdamW.'), ['method'])
        self.assertEqual(kinds('We show that the bound is tight.'), ['show'])
        self.assertEqual(kinds('Accuracy reaches \\res{m.acc} on the test set.'), ['number'])
        self.assertEqual(kinds('As shown in Table 2 and in 2019, this works.'), [])
        self.assertEqual(kinds('\\label{sec:first} Given $\\{x_i\\}_{i=1}^{N}$ we define the task.'), [])
        self.assertEqual(kinds('We report the mean over 5 seeds.'), ['number', 'method'])


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_project(self.root)
        self.setup = self.root / 'paper/sections/setup.tex'

    def tearDown(self):
        self.tmp.cleanup()

    def cl(self, *argv):
        return run('--root', str(self.root), *argv)

    def ledger(self):
        return json.loads((self.root / '.agentex/claims.json').read_text())

    def claim_id(self, needle):
        return next(i for i, c in self.ledger()['claims'].items() if needle in c['text'])

    def test_extract_next_record_report(self):
        code, out = self.cl('extract', str(self.root / 'paper'))
        self.assertEqual(code, 0)
        self.assertIn('6 claims (6 new', out)
        led = self.ledger()
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{8}', i) for i in led['claims']))
        lr = self.claim_id('learning rate')
        self.assertEqual(led['claims'][lr]['where'], 'paper/sections/setup.tex:1')
        self.assertEqual(led['claims'][lr]['kinds'], ['number', 'method'])
        self.assertNotIn('plain prose', json.dumps(led))

        code, out = self.cl('next', '--n', '1', '--code', str(self.root / 'code'))
        self.assertIn(lr, out)
        self.assertIn('? code/train.py:11  opt = torch.optim.AdamW', out)  # number + optimizer name match
        self.assertLessEqual(len(re.findall(r'^  \? ', out, re.M)), 3)

        best = self.claim_id('outperforms')
        self.assertEqual(self.cl('record', lr, '--verdict', 'supported')[0], 2)  # evidence required
        self.assertIn('not found', self.cl('record', lr, '--verdict', 'supported', '--evidence', 'code/nope.py:1')[1])
        self.assertIn('has 14 lines', self.cl('record', lr, '--verdict', 'supported', '--evidence', 'code/train.py:99')[1])
        self.assertEqual(self.cl('record', 'deadbeef', '--verdict', 'unclear')[0], 2)
        self.assertEqual(self.cl('record', lr, '--verdict', 'supported', '--evidence', 'code/train.py:11')[0], 0)
        self.assertEqual(self.cl('record', best, '--verdict', 'unsupported', '--note', 'no baseline runs in results/')[0], 0)

        code, out = self.cl('report')
        self.assertEqual(code, 1)
        self.assertIn('2/6 claims checked: 1 unsupported', out)
        self.assertIn('UNSUPPORTED paper/sections/setup.tex:7', out)
        self.assertIn('no baseline runs', out)
        st = json.loads((self.root / '.agentex/status/consistency.json').read_text())
        self.assertEqual(set(st), {'tool', 'status', 'summary', 'counts', 'items', 'updated'})
        self.assertEqual((st['tool'], st['status'], st['counts']['supported']), ('consistency', 'fail', 1))
        self.assertEqual(st['items'][0]['where'], 'paper/sections/setup.tex:7')

        # re-extract after edits: verdicts survive unchanged claims, edited ones become CHANGED, deleted ones REMOVED
        text = self.setup.read_text().replace('outperforms all', 'outperforms most').replace('We show that gradient clipping is essential. ', '')
        self.setup.write_text(text)
        code, out = self.cl('extract', str(self.root / 'paper'))
        self.assertIn('(0 new, 1 changed, 1 removed; 1 verdicts kept)', out)
        claims = self.ledger()['claims']
        self.assertEqual(claims[lr]['verdict'], 'supported')
        edited = self.claim_id('outperforms most')
        self.assertEqual((claims[edited]['status'], claims[edited]['verdict']), ('changed', None))
        self.assertEqual(claims[edited]['was'], {'id': best, 'text': claims[edited]['was']['text'], 'verdict': 'unsupported'})
        self.assertEqual([c['status'] for c in claims.values() if 'essential' in c['text']], ['removed'])
        self.assertIn('CHANGED', self.cl('next', '--n', '1', '--code', str(self.root / 'code'))[1].splitlines()[0])

    def test_freeze_and_diff(self):
        self.assertEqual(self.cl('diff')[0], 2)  # no ledger: the review guard skips
        self.cl('extract', str(self.root / 'paper'))
        code, out = self.cl('diff')
        self.assertEqual(code, 2)
        self.assertIn('no frozen claims', out)
        self.assertEqual(self.cl('freeze')[0], 0)
        self.assertEqual(self.cl('diff'), (0, '6 frozen claims intact\n'))
        self.setup.write_text(self.setup.read_text().replace('\n\\section', ' Extra words only.\n\\section'))  # prose edit
        self.assertEqual(self.cl('diff')[0], 0)
        self.setup.write_text(self.setup.read_text().replace('for 100 epochs', 'for 200 epochs')
                              .replace('We show that gradient clipping is essential. ', ''))
        code, out = self.cl('diff')
        self.assertEqual(code, 1)
        self.assertIn('was: "We train with AdamW', out)
        self.assertIn('for 200 epochs', out)
        self.assertRegex(out, r'REMOVED  [0-9a-f]{8}  paper/sections/setup.tex:8  "We show that gradient clipping is essential."')
        self.assertIn('2 of 6 frozen claims changed or removed', out)


if __name__ == '__main__':
    unittest.main()
