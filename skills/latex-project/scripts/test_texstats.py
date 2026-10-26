"""Run: python3 -m unittest discover skills/latex-project/scripts"""
import tempfile
import unittest
from pathlib import Path

from texstats import prose_words, stats

MAIN = r"""\documentclass{article}
\usepackage{amsmath}
\begin{document}
\begin{abstract}
We study three small things.
\end{abstract}
\section{Intro}\label{sec:intro}
As shown by~\citet{a,b}, the loss $L = x^2$ falls.% a comment with words
See \cref{fig:x} and \href{https://x.org}{our site}.\footnote{Really.}
\begin{equation} E = mc^2 \end{equation}
\[ a + b \]
\input{fig}
\input{more}
\end{document}
"""
MORE = r"""\section{More}
\begin{figure}\centering\includegraphics{x.pdf}\caption{A plot.}\label{fig:x}\end{figure}
\begin{table}\begin{tabular}{cc} 1 & 2 \end{tabular}\caption{Numbers \cite{a}.}\end{table}
\begin{tikzpicture}\node {not prose};\end{tikzpicture}
"""


class TexstatsTest(unittest.TestCase):
    def test_prose_words(self):
        self.assertEqual(prose_words(r'Hello \textbf{bold} world~\cite{k} with $x$ and \ref{a}.'), 5)  # Hello bold world with and

    def test_stats(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'more.tex').write_text(MORE)
            (Path(d) / 'fig.tex').write_text('\\documentclass{standalone}\\begin{document}\\begin{tikzpicture}\\end{tikzpicture}\\end{document}')
            main = Path(d) / 'main.tex'
            main.write_text(MAIN)
            s = stats(main)
        self.assertEqual(s['abstract words'], 5)
        self.assertEqual((s['sections'], s['figures'], s['tables'], s['equations'], s['citations'], s['footnotes']),
                         (2, 1, 1, 2, 2, 1))
        # abstract 5 + "Intro" 1 + "As shown by the loss falls" 6 + "See and our site Really" 5
        # + "More" 1 + "A plot" 2 + "Numbers" 1
        self.assertEqual(s['words'], 21)


if __name__ == '__main__':
    unittest.main()
