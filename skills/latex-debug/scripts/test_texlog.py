"""Run: python3 -m unittest discover skills/latex-debug/scripts"""
import unittest

from texlog import digest

LOG = r"""
(./main.tex
! Undefined control sequence.
l.42 \mathbb
            {R}
./sections/intro.tex:7: LaTeX Error: File `foo.sty' not found.
LaTeX Warning: Reference `fig:missing' on page 2 undefined on input line 30.
LaTeX Warning: Citation `ghost2020' on page 3 undefined on input line 31.
Overfull \hbox (0.4pt too wide) in paragraph at lines 10--12
Overfull \hbox (14.2pt too wide) in paragraph at lines 50--52
Package hyperref Warning: Token not allowed in a PDF string
LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.
"""


class TexlogTest(unittest.TestCase):
    def test_digest(self):
        report, has_errors = digest(LOG)
        self.assertTrue(has_errors)
        self.assertIn(r'line 42  Undefined control sequence.  <- near: \mathbb', report)
        self.assertIn("sections/intro.tex:7  LaTeX Error: File `foo.sty' not found.", report)
        self.assertIn('undefined reference (1): fig:missing', report)
        self.assertIn('undefined citation (1): ghost2020', report)
        self.assertIn('overfull box (1): 14.2pt @ lines 50--52', report)  # 0.4pt is ignored
        self.assertIn('hyperref: Token not allowed', report)

    def test_clean(self):
        self.assertEqual(digest('This is pdfTeX\nOutput written on main.pdf')[0],
                         'clean: no errors or notable warnings')


if __name__ == '__main__':
    unittest.main()
