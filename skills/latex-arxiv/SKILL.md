---
name: latex-arxiv
description: "Package a LaTeX project for arXiv. Ships only the files the document uses, strips comments, includes the .bbl, catches arXiv-specific failures (path case, biblatex/biber, minted, EPS, size) and test-compiles the package. Use when submitting to arXiv or cleaning a source folder to share."
---

# arXiv Packaging

## Workflow

1. **Compile locally first** so the `.bbl` is fresh: `latexmk -pdf main.tex`.
2. **Package and test:**
   ```bash
   python3 scripts/arxiv_pack.py paper/main.tex --compile
   ```
   This writes `paper/arxiv_submission/` and `arxiv_submission.tar.gz`. It prints the included files, the excluded files (so nothing private ships by accident), then warnings and errors. Errors block packaging; fix them and re-run. `--force` overrides, but don't use it to hide real problems.
3. **Before uploading, check by hand:**
   - Comments are stripped, but `\iffalse … \fi` blocks are **not**. Search for them and for hidden text.
   - The PDF metadata (`\hypersetup{pdfauthor=…}`) is correct.
   - The arXiv abstract field is plain text (≤ 1,920 characters, `$…$` maths allowed, no macros). Fill the comments field, e.g. "12 pages, 5 figures, accepted at X".
   - The licence choice is deliberate. The default arXiv licence is non-exclusive and can't be revoked.
4. **Upload** the `.tar.gz`, then read the PDF arXiv builds (fonts, figures, references) before submitting.

## What the script checks (and why)

| Problem | Why arXiv fails | Fix |
|---|---|---|
| Missing `main.bbl` | arXiv doesn't run biber, and may not run BibTeX | compile locally, ship the `.bbl` (done automatically) |
| biblatex `.bbl` version mismatch | arXiv's TeX Live may have a different biblatex | compile with a matching TeX Live year, or switch to BibTeX + natbib |
| `Figures/A.pdf` vs `figures/a.pdf` | macOS/Windows ignore case; arXiv's Linux doesn't | rename to match exactly |
| `../` or absolute paths | only the uploaded folder exists | move files inside the project |
| `minted`, `\tikzexternalize`, `\includesvg` | no `-shell-escape` on arXiv | minted `finalizecache`→`frozencache`; ship PDFs |
| EPS mixed with PDF/PNG | pdfLaTeX can't read EPS | `epstopdf` |
| No `\pdfoutput=1` in the first 5 lines | arXiv may pick the wrong engine | add it |
| > 50 MB | upload limit | compress: `gs -sDEVICE=pdfwrite -dPDFSETTINGS=/printer -o out.pdf in.pdf` |
| `\todo`, todonotes | notes become public | remove |

Unused files (old figures, notes, other `.tex` drafts, the compiled PDF) are never shipped. arXiv shows the *source* publicly, so this matters.

## Double-blind venues

If the paper is under double-blind review, check the venue's arXiv policy before posting (some forbid it during review, others allow it).
