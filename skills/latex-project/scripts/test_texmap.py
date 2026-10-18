"""Run: python3 -m unittest discover skills/latex-project/scripts"""
import tempfile
import unittest
from pathlib import Path

from texmap import build_map


class TexmapTest(unittest.TestCase):
    def test_map(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'sections').mkdir()
            (root / 'figures').mkdir()
            (root / 'main.tex').write_text(
                '\\documentclass{article}\n\\usepackage{amsmath}\n\\newcommand{\\vx}{x}\n'
                '\\begin{document}\n\\input{sections/intro}\n% \\input{sections/old}\n'
                '\\includegraphics{figures/a}\\includegraphics{figures/gone}\n\\end{document}\n')
            (root / 'sections' / 'intro.tex').write_text(
                '\\section{Intro}\\label{sec:intro}\n\\cite{k1,k2} % TODO: expand\n')
            (root / 'sections' / 'old.tex').write_text('\\section{Old}\n')
            (root / 'figures' / 'a.pdf').write_bytes(b'%PDF')
            (root / 'figures' / 'fig.tex').write_text(
                '\\documentclass{standalone}\n\\begin{document}x\\end{document}\n')
            m = build_map(root)
        self.assertIn('main.tex  [article; 2 files', m)
        self.assertIn('Intro [sec:intro]  sections/intro.tex:1', m)
        self.assertNotIn('Old', m)  # commented-out \input is not followed
        self.assertIn('macros (1): \\vx', m)
        self.assertIn('2 keys cited', m)
        self.assertIn('MISSING: figures/gone', m)
        self.assertIn('todos (1): sections/intro.tex:2', m)
        self.assertIn('standalone figures (1): figures/fig.tex', m)

    def test_budget(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'main.tex').write_text('\\documentclass{article}\\begin{document}\n' +
                                              ''.join(f'\\section{{S{i}}}\n' for i in range(200)) + '\\end{document}')
            m = build_map(Path(d), budget=500)
        self.assertLessEqual(len(m), 560)
        self.assertIn('truncated', m)


if __name__ == '__main__':
    unittest.main()
