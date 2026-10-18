"""Run: python3 -m unittest discover skills/latex-plagiarism-check/scripts"""
import tempfile
import unittest
from pathlib import Path

from overlap import check

SOURCE = ('Deep residual learning makes it possible to train networks that are substantially deeper than '
          'those used previously, because identity shortcut connections ease optimisation. '
          'We evaluate residual nets with a depth of up to 152 layers on the ImageNet dataset.')
PAPER = r"""\section{Intro}
Deep residual learning makes it possible to train networks that are substantially deeper than those used previously.
As shown by~\cite{he2016}, identity shortcut connections ease optimisation in very deep models of this kind.
Our method instead studies a completely different question about sparse attention in language models.
% We evaluate residual nets with a depth of up to 152 layers on the ImageNet dataset.
"""


class OverlapTest(unittest.TestCase):
    def test_findings(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'he2016.txt'
            src.write_text(SOURCE)
            paper = Path(d) / 'paper.tex'
            paper.write_text(PAPER)
            findings, total = check(paper, [src])
        self.assertEqual(total, 3)  # the commented-out copy is not counted
        lines = {f['line']: f for f in findings}
        self.assertEqual(set(lines), {2})  # sentence on line 3 shares < 12-word run and < 50 %
        f = lines[2]
        self.assertFalse(f['cited'])
        self.assertGreaterEqual(f['run'], 12)
        self.assertEqual(f['share'], 1.0)


if __name__ == '__main__':
    unittest.main()
