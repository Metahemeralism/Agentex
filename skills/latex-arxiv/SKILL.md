---
name: latex-arxiv
description: "Package a LaTeX project for arXiv: ships only used files, strips comments, ships the .bbl or .bib, catches arXiv failures (path case, biblatex, minted, EPS, size), test-compiles, and checks the HTML (LaTeXML) version and alt text. Use when submitting to arXiv or cleaning a source folder to share."
---

# arXiv Packaging

## Workflow

1. **Compile locally first** so the `.bbl` is fresh: `latexmk -pdf main.tex`. Run `latex-references`'s `cite_verify.py` too, because a fabricated reference on arXiv is public and permanent.
2. **Package and test:**
   ```bash
   python3 scripts/arxiv_pack.py paper/main.tex --compile
   ```
   This writes `paper/arxiv_submission/` and `arxiv_submission.tar.gz`. It prints the included files, the excluded files (so nothing private ships by accident), then warnings and errors. Errors block packaging; fix them and re-run. `--force` overrides, but don't use it to hide real problems.
3. **Check the HTML version:** `python3 <skill>/scripts/html_check.py paper/main.tex` (see "Check HTML readiness" below).
4. **Before uploading, check by hand:**
   - Comments are stripped, but `\iffalse … \fi` blocks are **not**. Search for them and for hidden text.
   - The PDF metadata (`\hypersetup{pdfauthor=…}`) is correct.
   - The arXiv abstract field is plain text (≤ 1,920 characters, `$…$` maths allowed, no macros). Fill the comments field, e.g. "12 pages, 5 figures, accepted at X".
   - The licence choice is deliberate. The default arXiv licence is non-exclusive and can't be revoked.
5. **Upload** the `.tar.gz`, then read the PDF and the HTML preview arXiv builds (fonts, figures, references, red error boxes) before submitting.

## What the script checks (and why)

arXiv rules checked against info.arxiv.org/help/submit_tex.html (October 2026): TeX Live 2025 is the default (2023 is also available).


| Problem | Why arXiv fails | Fix |
|---|---|---|
| No bibliography source | since 2025 arXiv runs BibTeX/biber on shipped `.bib` files, and uses a `.bbl` if one is present | the script ships the `.bbl` if it exists, otherwise the `.bib` files |
| biblatex `.bbl` format ≠ 3.3 | arXiv's default TeX Live 2025 only reads `.bbl` format 3.3 (it is written on line 2 of the `.bbl`) | `--prefer-bib`: ship the `.bib` and let arXiv run biber |
| `Figures/A.pdf` vs `figures/a.pdf` | macOS/Windows ignore case; arXiv's Linux doesn't | rename to match exactly |
| `../` or absolute paths | only the uploaded folder exists | move files inside the project |
| `minted`, `\tikzexternalize`, `\includesvg` | no `-shell-escape` on arXiv | minted `finalizecache`→`frozencache`; ship PDFs |
| EPS mixed with PDF/PNG | pdfLaTeX can't read EPS | `epstopdf` |
| No `\pdfoutput=1` in the first 5 lines | arXiv may pick the wrong engine | add it |
| > 50 MB | upload limit | compress: `gs -sDEVICE=pdfwrite -dPDFSETTINGS=/printer -o out.pdf in.pdf` |
| `\todo`, todonotes | notes become public | remove |

Unused files (old figures, notes, other `.tex` drafts, the compiled PDF) are never shipped. arXiv shows the *source* publicly, so this matters.

## Check HTML readiness before submitting

arXiv converts every TeX submission to HTML with LaTeXML (since 2026-08 its Rust port, latexml-oxide, per arXiv's conversion logs). Whatever it can't translate shows up as red error boxes for readers and screen-reader users.

```bash
python3 <skill>/scripts/html_check.py paper/main.tex
```

It prints findings with `file:line` and a fix, grouped by kind, and writes `.agentex/status/arxiv-html.json`:
- **Packages/classes with no LaTeXML binding.** It checks them against `reference/latexml-packages.txt`, a snapshot of the converter's binding table, including LaTeXML's versioned-name fallback (`neurips_2025` → `neurips`). A missing binding isn't always fatal, so let the preview decide before dropping a package.
- **`\includegraphics` without `alt=`**, plus visual-only markup: `{\it …}`/`{\bf …}`, a bold line used as a heading, and size + bold "headings".
- **Missing standard front matter:** `\title`, `\author` or the `abstract` environment.
- **Info only:** local style files (read as raw TeX), TikZ outside a captioned figure, and macros built from `\kern`, `\raisebox`, `@` internals and similar.

If `latexml_oxide` or `latexmlc` is on PATH, the script also converts a scratch copy and lists the converter's errors. Otherwise use the HTML preview arXiv shows during submission (local install: `brew install dginev/tap/latexml-oxide`). Fixes follow arXiv's best practices (info.arxiv.org/help/submit_latex_best_practices.html, checked 2026-10): standard `\title`/`\author`/`abstract`, `\emph` rather than `{\it}`, real `\section`s, and macros named for what they mean, not how they look. Propose fixes as a diff; never rewrite the author's preamble silently.

### Alt text: draft it from the code, not the pixels

1. Find what produced the figure. If `agentex-artifacts.json` exists (from `latex-results-sync`), look up the figure's path and read its `cmd` script and `inputs` data. Otherwise search the repo for the figure's file name.
2. From the script, take what is plotted against what (axes, units, series, scales). From the data, take the key numbers (ranges, which series wins, where a peak or crossover falls). For a TikZ diagram, read the nodes and arrows from its source.
3. Write 1–2 plain sentences: what the figure shows, then its takeaway. Example: `alt={Validation loss over 100 epochs for three optimisers; Adam converges fastest, reaching 0.21 by epoch 40.}` Don't repeat the caption or open with "Image of"; keep it plain text, with no macros.
4. Propose every alt text as one diff for the author to approve. Use `artifact` instead of `alt` only for purely decorative images. graphicx has accepted `alt` since 2021, and it does nothing unless tagging is on, so it is safe in any build. The same text feeds a tagged PDF (`latex-debug`'s `build.py --tagged`).

## Double-blind venues

If the paper is under double-blind review, check the venue's arXiv policy before posting (some forbid it during review, others allow it).
