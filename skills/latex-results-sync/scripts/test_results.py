"""Run: python3 -m unittest discover skills/latex-results-sync/scripts"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from results import audit, build, main, make, status, table


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'results').mkdir()
        (self.root / 'paper').mkdir()
        self.reg = self.root / 'paper' / 'results.tex'

    def tearDown(self):
        self.tmp.cleanup()

    def write_results(self, acc):
        (self.root / 'results' / 'resnet.json').write_text(json.dumps(
            {'cifar10': {'acc': acc, 'loss': 0.2871}, 'params': 11173962, 'name': 'ResNet_18', 'nan': float('nan')}))

    def test_build_audit_and_stale(self):
        self.write_results(0.8731)
        values, changed = build([self.root / 'results'], self.reg)
        self.assertEqual(values['resnet.cifar10.acc'], '0.8731')
        self.assertEqual(values['resnet.name'], 'ResNet\\_18')  # escaped for LaTeX
        self.assertNotIn('resnet.nan', values)
        self.assertEqual(changed, [])

        (self.root / 'paper' / 'main.tex').write_text(
            'Abstract: we reach 87.3\\% accuracy.\n'                      # hand-typed, will go stale
            'Table: \\num{\\res{resnet.cifar10.acc}} and loss 0.287.\n'  # second number hard-coded
            'Undefined \\res{resnet.cifar100.acc}; model has 11173962 params.\n'
            '\\includegraphics[width=0.873\\linewidth]{x}  % 87.3 in a comment\n')
        _, f = audit(self.root / 'paper')
        kinds = {(k, line, tok) for k, _, line, tok, _ in f}
        self.assertIn(('HARD-CODED', 1, '87.3'), kinds)      # 0.8731 shown as a percentage
        self.assertIn(('HARD-CODED', 2, '0.287'), kinds)
        self.assertIn(('HARD-CODED', 3, '11173962'), kinds)
        self.assertIn(('UNDEFINED', 3, 'resnet.cifar100.acc'), kinds)
        self.assertEqual(len(kinds), 4)                      # width=0.873 and the comment are ignored

        self.write_results(0.8694)                           # the rerun from the research example
        _, changed = build([self.root / 'results'], self.reg)
        self.assertEqual(changed, ['resnet.cifar10.acc'])
        _, f = audit(self.root / 'paper')
        stale = [msg for k, _, line, tok, msg in f if k == 'STALE']
        self.assertEqual(len(stale), 1)
        self.assertIn('OLD value of resnet.cifar10.acc', stale[0])
        self.assertIn('0.8694', stale[0])

        self.write_results(0.8702)                           # two reruns later 87.3 is still stale
        build([self.root / 'results'], self.reg)
        _, f = audit(self.root / 'paper')
        self.assertEqual(sum(k == 'STALE' for k, *_ in f), 1)

    def test_table(self):
        csv_path = self.root / 'results' / 'main.csv'
        csv_path.write_text('method,acc_mean,acc_std,loss\nBaseline,88.1,0.4,0.41\nOurs & co,91.3,0.3,0.29\n')
        out = self.root / 'paper' / 'tables' / 'main.tex'
        table(csv_path, out, decimals=1, bold_max={'acc'}, bold_min={'loss'}, pm=True)
        t = out.read_text()
        self.assertIn('method & acc & loss', t)
        self.assertIn('Ours \\& co & \\textbf{91.3 $\\pm$ 0.3} & \\textbf{0.3}', t)
        self.assertIn('Baseline & 88.1 $\\pm$ 0.4 & 0.4', t)
        self.assertIn('\\toprule', t)

    def test_provenance(self):
        script = self.root / 'plot.py'
        script.write_text("import sys; open('fig.txt','w').write(open('data.csv').read().upper())")
        (self.root / 'data.csv').write_text('a,b\n')
        manifest = self.root / 'agentex-artifacts.json'
        manifest.write_text(json.dumps({'outputs': {'fig.txt': {
            'cmd': f'"{sys.executable}" plot.py', 'inputs': ['plot.py', '*.csv']}}}))
        outputs = json.loads(manifest.read_text())['outputs']
        self.assertEqual(status(self.root, outputs)[0]['fig.txt'][0], 'missing')
        self.assertEqual(make(manifest)[0][1], 'built')
        self.assertEqual(status(self.root, outputs)[0]['fig.txt'][0], 'ok')
        (self.root / 'data.csv').write_text('a,b\n1,2\n')
        st, msg = status(self.root, outputs)[0]['fig.txt']
        self.assertEqual((st, msg), ('stale', 'changed inputs: data.csv'))
        make(manifest)
        (self.root / 'fig.txt').write_text('edited by hand')
        self.assertEqual(status(self.root, outputs)[0]['fig.txt'][0], 'modified')
        self.assertEqual(main(['stale', '--manifest', str(manifest)]), 1)


if __name__ == '__main__':
    unittest.main()
