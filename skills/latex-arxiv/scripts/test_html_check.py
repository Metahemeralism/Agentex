"""Run: python3 -m unittest discover skills/latex-arxiv/scripts"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import html_check

NAMES = {'article.cls', 'graphicx.sty', 'amsmath.sty', 'neurips.sty', 'revtex4-2.cls', 'tikz.sty', 'jhep.cls'}
MAIN = r"""\documentclass{article}
\usepackage{graphicx,amsmath}
\usepackage[final]{neurips_2025}
\usepackage{xstring}
\usepackage{mymacros}
\usepackage{tikz}
\newcommand{\R}{\mathbb{R}}
\newcommand{\tight}[1]{\kern-1pt\raisebox{1pt}{#1}}
% \usepackage{commentedout}
\title{A Paper}
\begin{document}
\maketitle
\input{sec}
\end{document}
"""
SEC = r"""\section{Intro}
Some {\it emphasis} and \emph{fine}.
\includegraphics[width=\linewidth]{plot}
\includegraphics[width=2cm, alt={Loss falls}]{plot}
\noindent\textbf{Results.}
{\Large\bfseries Method}
\begin{tikzpicture}\draw (0,0)--(1,1);\end{tikzpicture}
\begin{figure}\begin{tikzpicture}\draw (0,0);\end{tikzpicture}\caption{Pipeline.}\end{figure}
\usepackage{xstring}
"""


def project(root):
    for name, text in {'main.tex': MAIN, 'sec.tex': SEC, 'styles/mymacros.sty': '\\RequirePackage{amsmath}\n',
                       'plot.pdf': '%PDF-1.4\n'}.items():
        (root / name).parent.mkdir(exist_ok=True)
        (root / name).write_text(text)


class BindingTest(unittest.TestCase):
    def test_fallback_matches_latexml(self):
        self.assertTrue(html_check.has_binding('neurips_2025', 'sty', NAMES))  # versioned -> generic
        self.assertTrue(html_check.has_binding('JHEP', 'cls', NAMES))           # case-insensitive
        self.assertTrue(html_check.has_binding('revtex4-2', 'cls', NAMES))
        self.assertFalse(html_check.has_binding('tikz-cd', 'sty', NAMES))       # '-cd' is not a version suffix
        self.assertFalse(html_check.has_binding('xstring', 'sty', NAMES))

    def test_snapshot_loads(self):
        names = html_check.load_bindings()
        self.assertGreater(len(names), 400)
        self.assertIn('hyperref.sty', names)
        self.assertFalse(any(n.startswith('#') for n in names))


class CheckTest(unittest.TestCase):
    def run_check(self, which=lambda tool: None, run=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project(root)
            with mock.patch('shutil.which', which), mock.patch('subprocess.run', run or mock.DEFAULT):
                status, out, found = html_check.check(root / 'main.tex', NAMES)
            saved = json.loads((root / '.agentex' / 'status' / 'arxiv-html.json').read_text())
            self.assertEqual((root / '.agentex' / '.gitignore').read_text(), '*\n')
        return status, out, {(g, w) for g, w, _ in found}, saved

    def test_static(self):
        status, out, found, saved = self.run_check()
        self.assertEqual(status, 'warn')
        self.assertIn(('packages', 'main.tex:4'), found)          # xstring
        self.assertIn(('local-styles', 'main.tex:5'), found)      # styles/mymacros.sty is local
        self.assertNotIn(('packages', 'sec.tex:9'), found)        # xstring is reported once
        self.assertNotIn(('packages', 'main.tex:3'), found)       # neurips_2025 falls back to neurips
        self.assertNotIn(('packages', 'main.tex:9'), found)       # commented out
        self.assertIn(('alt-text', 'sec.tex:3'), found)
        self.assertNotIn(('alt-text', 'sec.tex:4'), found)
        self.assertIn(('markup', 'sec.tex:2'), found)             # {\it
        self.assertIn(('markup', 'sec.tex:5'), found)             # bold line as heading
        self.assertIn(('markup', 'sec.tex:6'), found)             # size + bold
        self.assertIn(('tikz', 'sec.tex:7'), found)
        self.assertNotIn(('tikz', 'sec.tex:8'), found)            # captioned figure
        self.assertIn(('macros', 'main.tex:8'), found)
        self.assertNotIn(('macros', 'main.tex:7'), found)
        self.assertEqual({w for g, w in found if g == 'front-matter'}, {'main.tex:11'})  # author + abstract missing
        self.assertTrue(any('arXiv shows the HTML during submission' in l for l in out))
        self.assertEqual(saved['tool'], 'arxiv-html')
        self.assertEqual(saved['status'], 'warn')
        self.assertLessEqual(len(saved['summary']), 100)
        self.assertEqual(saved['counts']['alt-text'], 1)
        self.assertTrue(all(set(i) == {'where', 'message'} for i in saved['items']))

    def test_conversion_digest(self):
        log = ('latexml_oxide (latexml-oxide 0.7.6) started\n'
               'Warning:missing_file:xstring Can\'t find binding or file for \'xstring.sty\'.\n'
               'Error:undefined:\\StrLeft The control sequence is undefined\n'
               '\tat sec.tex; line 2 col 4\n'
               'Conversion complete: 1 warning; 1 error; 1 undefined macro[\\StrLeft]\n')
        calls = []

        def run(cmd, cwd=None, **kw):
            calls.append((cmd, cwd))
            self.assertTrue((Path(cwd) / 'sec.tex').exists())  # converts a scratch copy with the used files
            return mock.Mock(stdout='', stderr=log, returncode=0)

        which = lambda tool: '/bin/latexml_oxide' if tool == 'latexml_oxide' else None
        status, out, found, saved = self.run_check(which, run)
        self.assertEqual(calls[0][0], ['latexml_oxide', 'main.tex', '--destination=main.html'])
        self.assertEqual(status, 'fail')
        self.assertIn(('conversion', 'sec.tex:2'), found)
        self.assertTrue(out[-1].startswith('latexml_oxide: Conversion complete: 1 warning; 1 error'))
        self.assertEqual(saved['items'][0]['where'], 'sec.tex:2')  # failures sort first


if __name__ == '__main__':
    unittest.main()
