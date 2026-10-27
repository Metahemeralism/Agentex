"""Run: python3 -m unittest discover skills/latex-arxiv/scripts"""
import tarfile
import tempfile
import unittest
from pathlib import Path

from arxiv_pack import main, strip_comments, Packer

MAIN = r"""\pdfoutput=1
\documentclass{article}
\usepackage{mystyle}
\usepackage{graphicx,biblatex}
\addbibresource{refs.bib}
\graphicspath{{figures/}}
\begin{document}
\input{sections/intro}
% \input{sections/old}
\includegraphics[width=\linewidth]{plot}
\subimport{chapters/}{ch1}
\printbibliography
\end{document}
"""


def project(root):
    files = {
        'main.tex': MAIN,
        'mystyle.sty': '\\RequirePackage{amsmath}\n',
        'refs.bib': '@misc{a, title={A}}\n',
        'main.bbl': '% $ biblatex auxiliary file $\n% $ biblatex bbl format version 3.3 $\n',
        'sections/intro.tex': 'Text % private note\n50\\% done \\url{http://x.org/a%20b}\n',
        'sections/old.tex': 'old\n',
        'figures/plot.pdf': '%PDF-1.4\n',
        'figures/unused.png': 'png',
        'chapters/ch1.tex': '\\includegraphics{img/local}\n',
        'chapters/img/local.png': 'png',
        'notes.txt': 'scratch',
    }
    for name, content in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


class StripCommentsTest(unittest.TestCase):
    def test_rules(self):
        src = ('a % note\n'
               '% whole line\n'
               '50\\% kept \\\\% gone\n'
               '\\url{x%20y} % gone\n'
               '% \\begin{verbatim} commented, must not start verbatim\n'
               '\\begin{verbatim}\n% literal\n\\end{verbatim}\n'
               '\\begin{comment}\nsecret\n\\end{comment}\n'
               'end\n')
        self.assertEqual(strip_comments(src),
                         'a %\n50\\% kept \\\\%\n\\url{x%20y} %\n'
                         '\\begin{verbatim}\n% literal\n\\end{verbatim}\nend\n')


class PackTest(unittest.TestCase):
    def test_package(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project(root)
            pk = Packer(root / 'main.tex')
            pk.run()
            used = sorted(pk.rel(p) for p in pk.files)
            self.assertEqual(pk.errors, [])
            self.assertEqual(used, ['chapters/ch1.tex', 'chapters/img/local.png', 'figures/plot.pdf',
                                    'main.bbl', 'main.tex', 'mystyle.sty', 'sections/intro.tex'])
            self.assertIn('notes.txt', pk.unused(root / 'arxiv_submission'))

            self.assertEqual(main([str(root / 'main.tex')]), 0)
            out = root / 'arxiv_submission'
            self.assertEqual((out / 'sections/intro.tex').read_text(),
                             'Text %\n50\\% done \\url{http://x.org/a%20b}\n')
            with tarfile.open(root / 'arxiv_submission.tar.gz') as tf:
                self.assertIn('main.bbl', tf.getnames())
            self.assertEqual(main([str(root / 'main.tex')]), 1)  # refuses to overwrite without --force

    def test_bib_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project(root)
            (root / 'main.bbl').unlink()  # no .bbl: arXiv runs biber on the shipped .bib
            pk = Packer(root / 'main.tex')
            pk.run()
            self.assertEqual(pk.errors, [])
            self.assertIn('refs.bib', {pk.rel(p) for p in pk.files})

    def test_errors(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project(root)
            (root / 'main.bbl').write_text('% $ biblatex bbl format version 3.2 $\n')
            (root / 'main.tex').write_text(MAIN.replace('{plot}', '{Plot}').replace(
                '\\input{sections/intro}', '\\input{sections/intro}\\input{../outside}\\input{nothere}'
                '\\begin{verbatim}\\input{shown-as-code}\\end{verbatim}\\verb|\\includegraphics{alsocode}|'))
            pk = Packer(root / 'main.tex')
            pk.run()
            errs = '\n'.join(pk.errors)
            self.assertIn('bbl format 3.2', errs)
            self.assertIn('outside the project', errs)
            self.assertIn('missing file "nothere"', errs)
            self.assertNotIn('shown-as-code', errs)  # code in verbatim is not an input
            self.assertNotIn('alsocode', errs)
            self.assertTrue('letter case' in errs or 'missing file "Plot"' in errs)  # macOS vs Linux FS
            self.assertEqual(main([str(root / 'main.tex')]), 1)
            self.assertFalse((root / 'arxiv_submission').exists())


if __name__ == '__main__':
    unittest.main()
