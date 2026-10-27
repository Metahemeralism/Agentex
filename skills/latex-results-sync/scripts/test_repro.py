"""Run: python3 -m unittest discover -s skills/latex-results-sync/scripts"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from repro import END, START, compare, main, rows
from results import make

PAPER = r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
Code: none yet.
\begin{figure}
  \includegraphics[width=\linewidth]{figures/loss}
  \caption{Training loss of all \textbf{models} over 100 epochs, averaged.}\label{fig:loss}
\end{figure}
\input{sections/results}
\begin{figure}
  \includegraphics{figures/arch}
  \caption{Architecture.}\label{fig:arch}
\end{figure}
\begin{figure}\begin{tikzpicture}\draw (0,0) -- (1,1);\end{tikzpicture}\caption{Diagram.}\end{figure}
\end{document}
"""
SECTION = r"""\begin{table}
  \caption{Main results}\label{tab:main}
  \input{tables/main}
\end{table}
"""


def git(root, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', *args],
                          cwd=root, capture_output=True, text=True, check=True).stdout


class ReproTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.root = Path(self.tmp.name)
        (r / 'paper' / 'sections').mkdir(parents=True)
        (r / 'paper' / 'main.tex').write_text(PAPER)
        (r / 'paper' / 'sections' / 'results.tex').write_text(SECTION)
        (r / 'data.csv').write_text('epoch,loss\n1,0.5\n')
        (r / 'table.csv').write_text('acc,acc_std\n0.9,0.01\n')
        (r / 'plot.py').write_text("import os, random; random.seed(42); os.makedirs('paper/figures', exist_ok=True)\n"
                                   "open('paper/figures/loss.pdf', 'w').write(open('data.csv').read().upper())\n")
        (r / 'tab.py').write_text("import os; os.makedirs('paper/tables', exist_ok=True)\n"
                                  "a, s = open('table.csv').read().split()[1].split(',')\n"
                                  "open('paper/tables/main.tex', 'w').write(f'\\\\begin{{tabular}}{{r}}{a} $\\\\pm$ {s}\\\\end{{tabular}}')\n")
        py = f'"{sys.executable}"'
        self.manifest = r / 'agentex-artifacts.json'
        self.manifest.write_text(json.dumps({'outputs': {
            'paper/figures/loss.pdf': {'cmd': f'{py} plot.py', 'inputs': ['plot.py', 'data.csv']},
            'paper/tables/main.tex': {'cmd': f'{py} tab.py', 'inputs': ['tab.py', 'table.csv']}}}, indent=1))
        git(r, 'init', '-q')
        self.assertTrue(all(st == 'built' for _, st, _ in make(self.manifest)))
        git(r, 'add', '-A')
        git(r, 'commit', '-qm', 'fixture')
        (r / 'table.csv').write_text('acc,acc_std\n0.8,0.02\n')  # the table is now stale, the figure fresh

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([*argv, '--manifest', str(self.manifest)])
        return code, buf.getvalue()

    def test_rows_map_outputs_to_floats(self):
        _, rs = rows(self.manifest, self.root / 'paper')
        by = {r['output'] or r['paper'][0][1]: r for r in rs}
        fig, tab = by['paper/figures/loss.pdf'], by['paper/tables/main.tex']
        self.assertEqual(fig['status'], 'fresh')
        self.assertEqual(fig['paper'], [('paper/main.tex:6', 'fig:loss', 'Training loss of all models over 100 epochs,…')])
        self.assertEqual(tab['status'], 'stale')
        self.assertEqual(tab['paper'], [('paper/sections/results.tex:3', 'tab:main', 'Main results')])
        self.assertRegex(fig['inputs'][0], r'^data\.csv@[0-9a-f]{8}$')
        self.assertIn('CPUs', fig['run'])
        self.assertEqual(by['fig:arch']['status'], 'no-source')
        self.assertEqual(len(rs), 3)  # the hand-drawn TikZ diagram is not a NO-SOURCE result

    def test_table_cli_writes_block_and_status(self):
        readme = self.root / 'README.md'
        readme.write_text('# Project\n\nIntro.\n')
        code, out = self.run_main('table', '--paper', str(self.root / 'paper'), '--write', str(readme))
        self.assertEqual(code, 1)  # stale + no-source
        self.assertIn('+' + START, out)
        self.assertEqual(readme.read_text(), '# Project\n\nIntro.\n')  # diff only without --apply
        self.run_main('table', '--paper', str(self.root / 'paper'), '--write', str(readme), '--apply')
        readme.write_text(readme.read_text() + '\n## Licence\nMIT\n')
        text = readme.read_text()
        self.assertIn('| `fig:loss` "Training loss', text)
        self.assertIn('| STALE |', text)
        (self.root / 'table.csv').write_text('acc,acc_std\n0.9,0.01\n')  # back to fresh: only the block changes
        self.run_main('table', '--paper', str(self.root / 'paper'), '--write', str(readme), '--apply')
        new = readme.read_text()
        self.assertTrue(new.startswith('# Project\n\nIntro.\n\n' + START) and new.endswith(END + '\n\n## Licence\nMIT\n'))
        self.assertNotIn('| STALE |', new)
        st = json.loads((self.root / '.agentex' / 'status' / 'repro.json').read_text())
        self.assertEqual((st['tool'], st['status'], st['counts']), ('repro', 'warn', {'fresh': 2, 'no-source': 1}))
        self.assertEqual(st['items'], [{'where': 'paper/main.tex:10', 'message': 'no-source: figure/table with no producer'}])

    def test_smoke_reproduces_and_cleans_up(self):
        (self.root / 'paper' / 'figures' / 'loss.pdf').write_text('EDITED BY HAND')
        (self.root / 'bad.json').write_text(json.dumps({'outputs': {
            'boom.txt': {'cmd': f'"{sys.executable}" -c "raise SystemExit(\'boom: error\')"', 'inputs': []},
            'x.txt': {'cmd': 'true', 'inputs': ['table.csv', 'local-only.csv']}}}))
        (self.root / 'local-only.csv').write_text('not committed\n')
        code, out = self.run_main('smoke')
        self.assertEqual(code, 1)
        self.assertIn('note: uncommitted changes', out)
        self.assertRegex(out, r'DIFFERS +paper/figures/loss\.pdf  sha256 differs')
        self.assertRegex(out, r'REPRODUCED paper/tables/main\.tex')
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(['smoke', '--manifest', str(self.root / 'bad.json'), '--outputs', 'boom.txt,x.txt,nope'])
        out = buf.getvalue()
        self.assertIn('FAILED     boom.txt  boom: error', out)
        self.assertIn('FAILED     x.txt  not in the HEAD checkout: local-only.csv', out)
        self.assertIn('FAILED     nope  not an output in the manifest', out)
        self.assertEqual(git(self.root, 'worktree', 'list').count('\n'), 1)  # throwaway checkout removed
        st = json.loads((self.root / '.agentex' / 'status' / 'smoke.json').read_text())
        self.assertEqual((st['status'], st['counts']['failed']), ('fail', 3))

    def test_compare_json_within_tolerance(self):
        a, b = self.root / 'a.json', self.root / 'b' / 'a.json'
        b.parent.mkdir()
        a.write_text(json.dumps({'acc': 0.9, 'runs': [1, 2], 'name': 'x'}))
        b.write_text(json.dumps({'acc': 0.9 + 1e-9, 'runs': [1, 2], 'name': 'x'}))
        self.assertEqual(compare(a, b, 1e-6)[0], 'reproduced')
        b.write_text(json.dumps({'acc': 0.91, 'runs': [1], 'name': 'x'}))
        st, msg = compare(a, b, 1e-6)
        self.assertEqual(st, 'differs')
        self.assertIn('2 keys differ: acc 0.9 -> 0.91, runs.1 2 -> -', msg)

    def test_checklist_is_a_draft_with_pointers(self):
        code, out = self.run_main('checklist', '--paper', str(self.root / 'paper'))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('DRAFT'))
        self.assertIn('2 recorded runs', out)
        self.assertIn('plot.py:1  import os, random; random.seed(42)', out)
        self.assertIn('paper/tables/main.tex:1', out)                       # the generated ± column
        self.assertIn('Code availability\n  - not found', out)              # never claims what it can't point to
        self.assertIn('data.csv, table.csv', out)


if __name__ == '__main__':
    unittest.main()
