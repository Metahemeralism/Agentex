"""Run: python3 -m unittest discover skills/latex-references/scripts"""
import tempfile
import unittest
from pathlib import Path

from check_refs import analyse

TEX = r"""
\addbibresource{refs.bib}
\section{Intro}\label{sec:intro}
See \cref{sec:intro,fig:missing} and \eqref{eq:a}.
\begin{equation}x\label{eq:a}\end{equation}
\label{sec:intro}
\parencite[p.~3]{knuth84}, \citet{ghost2020}.
% \cite{commented} \ref{commented}
50\% \label{unused}
"""
BIB = """
@book{knuth84, title={TeX}}
@article{unused2001, title={x}}
@string{foo = "bar"}
"""


class CheckRefsTest(unittest.TestCase):
    def test_report(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "main.tex").write_text(TEX)
            (root / "refs.bib").write_text(BIB)
            r = analyse(root)
        e, w = r["errors"], r["warnings"]
        self.assertEqual(set(e["undefined reference"]), {"fig:missing"})
        self.assertEqual(set(e["duplicate label"]), {"sec:intro"})
        self.assertEqual(set(e["citation not in .bib"]), {"ghost2020"})  # commented cite ignored
        self.assertEqual(set(w["label never referenced"]), {"unused"})  # escaped \% is not a comment
        self.assertEqual(set(w["bib entry never cited"]), {"unused2001"})


if __name__ == "__main__":
    unittest.main()
