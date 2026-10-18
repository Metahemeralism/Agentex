---
name: latex-project
description: "Scaffold and organise a LaTeX paper, thesis or report next to a code repo: templates, package set, layout, latexmk/Overleaf, venue classes, plus a compact project map so agents read only the files they need. Use when starting or restructuring a LaTeX project."
---

# LaTeX Project Setup & Structure

Goal: a project that compiles first time, is easy to split across collaborators, and keeps the paper in sync with the code it describes.

## Workflow

1. **Ask (or infer) the target.** Journal/conference template? Thesis? arXiv preprint? Report? If a venue is named, use its official class (`IEEEtran`, `acmart`, `elsarticle`, `llncs`, `neurips_20XX.sty`, …) and do not fight its defaults (fonts, margins, bibliography style).
2. **Scaffold** from `templates/` in this skill unless a venue template applies:
   - `templates/main.tex`: article skeleton with sane package set
   - `templates/macros.tex`: notation macros (pairs with the `latex-math` skill)
   - `templates/references.bib`: example entries
   - `templates/latexmkrc`: one-command build
3. **Outline from the code.** Read the repo (README, entry points, configs, experiment scripts) and propose a section skeleton: Introduction → Background/Related Work → Method → Experimental Setup → Results → Discussion/Limitations → Conclusion. Put `% TODO:` comments with pointers to the source files each section should draw from.
4. **Build** with `latexmk -pdf main.tex` (or `-lualatex` when fonts/Unicode require it). On failure, hand over to the `latex-debug` skill.
5. **Existing project? Map it before reading anything:** `python3 scripts/texmap.py paper/` prints the input tree, the outline with `file:line`, labels, macros, TikZ styles, bibliography usage, missing figures and TODOs in ≤ 3,000 characters. Then open only the files the task touches.

## Recommended layout

```
paper/
├── main.tex          % preamble + \input of sections, nothing else
├── macros.tex        % ALL notation and custom commands live here
├── references.bib
├── sections/         % one file per section: intro.tex, method.tex, ...
├── figures/          % generated PDFs/PGFs + TikZ sources
├── tables/           % generated .tex tables (never hand-edit generated ones)
└── latexmkrc
```

- Use `\input{sections/method}` (not `\include`) unless you need `\includeonly` for a long thesis.
- Generated artefacts (tables, plots) are written by scripts in the code repo straight into `paper/figures` and `paper/tables`, so re-running experiments updates the paper with no copy-paste. Document the command that regenerates each one in a comment at the top of the file.

## Package defaults (article-class projects)

| Need | Package | Note |
|---|---|---|
| Encoding/fonts | `fontenc[T1]`, `lmodern` (pdfLaTeX) or `fontspec` (LuaLaTeX) | never load `fontspec` under pdfLaTeX |
| Maths | `amsmath`, `amssymb`, `mathtools`, `bm` | `mathtools` extends and fixes `amsmath` |
| Units/numbers | `siunitx` | `\num{1e-3}`, `\SI{3.2}{\milli\second}` (v3: `\qty`) |
| Tables | `booktabs` | no vertical rules |
| Figures | `graphicx`, `subcaption` | not `subfigure`/`subfig` (obsolete) |
| Algorithms | `algorithm` + `algpseudocode` | see `latex-algorithms` |
| Links | `hyperref` | load **late**, then `cleveref` **after** it |
| Refs | `cleveref` | `\cref{fig:x}` → "Fig. 1" automatically |
| Drafting | `todonotes` or `\newcommand{\todo}[1]{...}` | remove before submission |

Load order matters: `hyperref` near the end, `cleveref` after `hyperref`, `algorithm` before `hyperref` is fine.

## Conventions to enforce

- One sentence per line in source files → clean git diffs and easy review.
- Labels are typed: `sec:`, `fig:`, `tab:`, `eq:`, `alg:`, `app:`, `thm:`, `lst:`.
- No hard-coded numbers that come from experiments: they live in a generated file (e.g. `results.tex` defining `\newcommand{\accBest}{94.2}`), so the text can never disagree with the code.
- Non-breaking space before references and citations: `Figure~\ref{...}`, `as shown by~\cite{...}` (or just use `\cref`).
- Keep the preamble in `main.tex`; never redefine standard commands in section files.

## Overleaf

The same layout works on Overleaf. Upload the `paper/` folder as a zip, set the main document to `main.tex`, and pick the compiler (pdfLaTeX vs LuaLaTeX) under Menu → Settings. Overleaf honours `latexmkrc`.

## Token discipline (applies to every AgenTeX skill)

- **Map, then read:** `texmap.py` first; open one section file, not the whole paper.
- **Edit in place:** targeted edits on the lines that change. One sentence per line keeps edits small and unique.
- **Copy, don't retype:** `cp` templates and patterns, then edit the differences.
- **Never read a `.log` whole:** use `latex-debug`'s `scripts/texlog.py`.
- **Files, not chat:** write results to files; reply with the path and ≤ 3 lines. Never re-paste a file you just wrote.

## Hand-offs

- Equations and notation → `latex-math`
- Diagrams → `latex-tikz`
- Pseudocode/listings → `latex-algorithms`
- Tables/plots from results → `latex-tables-figures`
- Numbers/figures in sync with code (registry, stale audit, provenance) → `latex-results-sync`
- Bibliography/cross-references → `latex-references`
- Check paper against code → `latex-consistency`
- Slides → `latex-beamer`
- Errors → `latex-debug`
- Closest prior work / novelty → `latex-research-check`
- Text overlap → `latex-plagiarism-check`
- Mock peer review → `latex-review`
- arXiv upload → `latex-arxiv`
