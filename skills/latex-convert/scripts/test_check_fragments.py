"""Run: python3 -m unittest discover skills/latex-convert/scripts"""
import tempfile
import unittest
from pathlib import Path

from check_fragments import extract_preamble_commands, validate_file

GOOD = r"""\section{Graphs}
\begin{theorem}A tree on $n$ vertices has $n-1$ edges.\end{theorem}
\begin{align} a &= b \\ c &= d \end{align}
\begin{tikzpicture}\node (a) {A};\draw (a) -- (1,0);\end{tikzpicture}
"""
BAD = r"""\begin{itemize}
\item one
\draw (0,0) -- (1,1);
Tom & Jerry
\begin{theorem}
\begin{figure}[H]\end{figure}
\end{theorem}
"""


class CheckFragmentsTest(unittest.TestCase):
    def test_good_and_bad(self):
        with tempfile.TemporaryDirectory() as d:
            good, bad = Path(d) / 'batch_001.tex', Path(d) / 'batch_002.tex'
            good.write_text(GOOD)
            bad.write_text(BAD)
            self.assertEqual([str(e) for e in validate_file(str(good), set())], [])
            cats = {e.category for e in validate_file(str(bad), set())}
            self.assertTrue({'ENV_MISMATCH', 'TIKZ_OUTSIDE'} <= cats or {'ENV_UNCLOSED', 'TIKZ_OUTSIDE'} <= cats, cats)
            self.assertTrue(any('&' in str(e) for e in validate_file(str(bad), set())))

    def test_preamble_commands(self):
        with tempfile.TemporaryDirectory() as d:
            pre = Path(d) / 'preamble.tex'
            pre.write_text(r'\newcommand{\R}{\mathbb{R}}\DeclareMathOperator{\rank}{rank}')
            self.assertTrue({r'\R', r'\rank'} <= extract_preamble_commands(str(pre)))


if __name__ == '__main__':
    unittest.main()
