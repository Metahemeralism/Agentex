---
name: latex-project
description: "Scaffold a LaTeX paper or thesis next to a code repo: asks venue, layout, length and review mode, then builds a compiling skeleton (abstract, sections, tables, TikZ figures, references, one or two columns). Maps and word-counts existing projects. Use when starting or restructuring a paper."
---

# LaTeX Project Setup & Structure

Goal: a project that compiles first time, is easy to split across collaborators, and keeps the paper in sync with the code it describes.

## Workflow

1. **Intake: ask before scaffolding a new paper.** Ask all four in one round: with `AskUserQuestion` in Claude Code, otherwise as a numbered list. Skip any question the user or repo already answered. A named venue settles layout, length and review mode: state those values instead of asking.

   | Question (header) | Options | Sets |
   |---|---|---|
   | Where is this going? (Venue) | Conference paper · Journal article · Thesis or report · arXiv preprint. "Other" takes a named venue, e.g. "ICML 2027" | class, citation style, page limit (venue table below) |
   | Which layout? (Layout) | Venue default (Recommended) · One column · Two column | the `\documentclass` line |
   | Estimated length? (Length) | ~4 pages (short/workshop) · ~8 pages (full paper) · ~15 pages (journal) · 40+ pages (thesis) | `\fillerscale` (length table below) |
   | Anonymous review? (Review) | Double-blind (anonymous) · Named authors | `\author` block, acknowledgements |

   Infer the rest instead of asking: title and topic from the README, authors from `git config user.name`, and the section content from the code (step 4).
2. **Scaffold** the whole paper with one copy. It compiles as-is:
   ```bash
   cp -R <skill>/templates paper
   ```
   You get a title block (title, authors, abstract, keywords), Introduction → Related Work → Method → Experimental Setup → Results → Discussion/Limitations → Conclusion, then acknowledgements, references and an appendix. It also contains:
   - `sections/*.tex`: one file per section. A grey `\guide{…}` says what each part must contain, and `\filler{…}` provides lorem-ipsum body text
   - `tables/*.tex`: booktabs/siunitx table bodies (dataset stats, a wide main-results table with bold best scores, an ablation, hyperparameters). Captions and labels stay in the section files, so generated tables can replace these files directly
   - `figures/overview.tex` (a full-width TikZ teaser) and `figures/training-curves.tex` (a column-width pgfplots plot with an error band). These are standalone files embedded with `\input`, and each can be checked alone with `latex-tikz`'s `tikzcheck.sh`
   - an equation, a definition, an algorithm, `\cref` cross-references, and `references.bib` with five `placeholder-*` entries
3. **Apply the intake answers** (edit `paper/main.tex` in place):
   - **Layout:** keep exactly one `\documentclass` line (one column `[11pt]`, two column `[10pt,twocolumn]`). Wide floats are already `figure*`/`table*`, so nothing else changes.
   - **Length:** set `\fillerscale` from the length table. At `0`, the paper is only headings, guides, tables and figures.
   - **Review:** for double-blind, set `\author{Anonymous Authors}` and delete the acknowledgements.
   - **Venue class:** when the venue has an official class or style (venue table), swap `main.tex`'s `\documentclass`, title block and bibliography setup for the venue's own. Keep `sections/`, `tables/`, `figures/`, `macros.tex` and the placeholder block. Don't fight the venue's defaults (fonts, margins, bibliography style).
   - **Thesis:** for full front matter (declaration, acknowledgements, roman page numbers) copy the preamble and front matter of `latex-documents/templates/thesis.tex`; otherwise use `\documentclass[11pt,titlepage]{report}`. Then run `sed -i.bak 's/\\section{/\\chapter{/; s/\\subsection{/\\section{/' paper/sections/*.tex && rm paper/sections/*.bak`, and add `\tableofcontents` after the abstract.
4. **Outline from the code.** Read the repo (README, entry points, configs, experiment scripts). Rewrite each `\guide` to say what *this* paper puts there, with a `% TODO:` pointing at the source files it draws from. Rename, add or drop sections to fit the work (theory paper: Theory instead of Experimental Setup; survey: a taxonomy).
5. **Build** with `python3 <skill>/../latex-debug/scripts/build.py paper/main.tex --preview previews`, which picks pdfLaTeX, XeLaTeX or LuaLaTeX from the preamble. On failure, hand over to the `latex-debug` skill.
6. **Existing project? Map it before reading anything:** `python3 <skill>/scripts/texmap.py paper/` prints the input tree, the outline with `file:line`, labels, macros, TikZ styles, bibliography usage, missing figures and TODOs in ≤ 3,000 characters. Then open only the files the task touches. For word and page limits: `python3 <skill>/scripts/texstats.py paper/main.tex` (approximate; `texcount -inc -total` for an exact venue count).

### Length table

Main-body pages (up to the references, US letter) of the default template, measured with tectonic. The scale is roughly linear: one column ≈ 5 + 3 × scale, two column ≈ 3 + 2.5 × scale.

| Target body pages | One column `\fillerscale` | Two column `\fillerscale` |
|---|---|---|
| 4 (short/workshop) | `0` and drop a table | `0.5` |
| 8 (full conference paper) | `1` | `2` |
| 9–10 | `1.5` | `2.5` |
| 15 (journal) | `3.5` | `5` |
| 40+ (thesis) | `12` (prefer more chapters to more filler) | n/a |

### Venue table

Page limits change every year, so check the current call for papers before quoting one.

| Venue | Class / style | Columns | Keywords | Typical limit |
|---|---|---|---|---|
| arXiv preprint, tech report | this template (`article`) | 1 | `\keywords` (template) | none |
| Journal (generic) | this template, or the journal's class (`elsarticle`, `svjour3`, …) | 1 | template or the class's `keyword` env | varies |
| IEEE conference / journal | `IEEEtran` (`conference` / `journal`) | 2 | `IEEEkeywords` env | 6–8 / 10–14 |
| ACM | `acmart` (`sigconf` / `acmsmall`) | 2 / 1 | `\keywords{}` + CCS concepts | varies |
| NeurIPS, ICLR | `article` + the year's `.sty` | 1 | none | 9–10 + refs + appendix |
| ICML | `article` + `icmlYYYY.sty` | 2 | `\icmlkeywords{}` | 8 + refs + appendix |
| CVPR, ICCV | the year's author kit | 2 | none | 8 + refs |
| ACL, EMNLP | `acl.sty` | 2 | none | 8 long / 4 short + refs |
| Springer LNCS | `llncs` | 1 | `\keywords{}` | 12–16 incl. refs |
| Thesis | `report`/`book` or the university class | 1 | per university | per university |

### Placeholders are loud on purpose

Each kind of placeholder is easy to spot and has an owner skill: `\guide`/`\filler` text (the writer), `placeholder-*` citations (`latex-references`, whose `cite_verify.py` reports them as not found until replaced), placeholder tables and plots (`latex-tables-figures`, `latex-results-sync`) and the teaser figure (`latex-tikz`). Before submission, this must print nothing:
```bash
grep -rnE '\\guide|\\filler|placeholder' paper/ --include='*.tex' --include='*.bib'
```
Then delete the placeholder block in `main.tex` (`lipsum`, `xfp`, `\fillerscale`, `\filler`, `\guide`).

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
- No hard-coded numbers that come from experiments: they come from the results registry as `\res{exp.acc}` (`latex-results-sync`), so the text can never disagree with the code.
- Non-breaking space before references and citations: `Figure~\ref{...}`, `as shown by~\cite{...}` (or just use `\cref`).
- Keep the preamble in `main.tex`; never redefine standard commands in section files.

## Overleaf

The same layout works on Overleaf. Upload the `paper/` folder as a zip, set the main document to `main.tex`, and pick the compiler (pdfLaTeX vs LuaLaTeX) under Menu → Settings. Overleaf honours `latexmkrc`.

## Token discipline (applies to every AgenTeX skill)

- **Map, then read:** `texmap.py` first; open one section file, not the whole paper.
- **Edit in place:** targeted edits on the lines that change. One sentence per line keeps edits small and unique.
- **Copy, don't retype:** `cp` templates and patterns, then edit the differences.
- **Never read a `.log` whole:** use `<skill>/../latex-debug/scripts/texlog.py`.
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
- Poster → `latex-poster`
- Non-paper documents (CV, letters, exams, book, thesis front matter) → `latex-documents`
- Markdown/Word/PDF → LaTeX, latexdiff between versions → `latex-convert`
- Errors, and builds needing XeLaTeX/LuaLaTeX → `latex-debug`
- PDF/A, submission checks (embedded fonts, page size), compression → `latex-pdf`
- Closest prior work / novelty → `latex-research-check`
- Text overlap → `latex-plagiarism-check`
- Mock peer review → `latex-review`
- arXiv upload → `latex-arxiv`
