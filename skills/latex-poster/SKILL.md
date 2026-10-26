---
name: latex-poster
description: "Turn a paper or project into a conference poster (tikzposter, A0 or the venue's size): portrait and landscape templates, #BetterPoster layout, QR codes, and the paper's own figures, notation and \\res{} numbers so the poster can't drift. Use for any poster."
---

# Conference Posters

A poster is read in 10 seconds from 2 metres, then for 2 minutes up close. It needs one headline result, few words (~500, never a pasted abstract) and figures you can read from a distance.

## Workflow

1. **Ask in one round** (Claude Code: `AskUserQuestion`; otherwise a numbered list), skipping what's known:
   - **Size:** A0 portrait (default) · A0 landscape · the venue's size. Venues change board sizes from year to year, so read the current poster instructions (search the web if you can) instead of trusting memory. Set it with `\geometry{paperwidth=…, paperheight=…}`.
   - **Layout:** traditional columns (default) · #BetterPoster (one key finding in large type in a central column, details in the side columns) · results-first (one large figure taking 40–50% of the area).
   - **Colour scheme:** five schemes are commented at the top of `poster.tex`. Don't let colour alone carry meaning.
2. **Copy the template:** `cp <skill>/templates/poster.tex poster/poster.tex` (portrait, 2 columns, BetterPoster variant commented at the end) or `templates/poster-landscape.tex` (3 columns, 30/40/30; a commented `\geometry{}` line for custom sizes).
3. **Write the storyline before LaTeX** and agree it with the user: title as a claim → problem (2 lines) → key idea (one figure) → method (one diagram) → main result (one plot or table, highlighted) → takeaways (3 bullets) → QR code.
4. **Reuse the paper; never re-type it** (see below).
5. **Build and look at it:** `python3 <skill>/../latex-debug/scripts/build.py poster/poster.tex --preview previews --dpi 25`. A 25-dpi preview of an A0 page is about the size of a poster seen across a room: if a figure label is unreadable there, enlarge it. Fix `Overfull \vbox` (content falling off a block) before anything else.
6. **Check it against the paper** (below), then hand over the PDF. For printing services that ask for PDF/X or PDF/A, or a smaller file, see `latex-pdf`.

## Reuse the paper: the poster as another build of the same sources

- **Notation:** `\input{../paper/macros.tex}` so symbols match the paper exactly.
- **Numbers:** `\input{../paper/results.tex}` in the preamble and write `\res{resnet.cifar10.acc}`, never 87.3 (`latex-results-sync`). A rerun then updates the paper and the poster together.
- **Figures:** `\includegraphics[width=\linewidth]{../paper/figures/loss.pdf}` inside `tikzfigure`, not `figure`. For TikZ sources, `\usepackage{../paper/figures/agentex-tikz}` and `\resizebox{\linewidth}{!}{\input{../paper/figures/overview.tex}}`. Paper figures are drawn for 9pt text, so check label size in the preview and raise TikZ `font=` sizes, or replot with larger fonts (`latex-tables-figures`).
- **Citations:** the templates list references by hand. Replace that with the paper's verified entries: `\usepackage[style=numeric,backend=biber]{biblatex}`, `\addbibresource{../paper/references.bib}`, `\cite` 3–6 key works and `\printbibliography[heading=none]` in the references block. The AgenTeX cite guard then checks them as in the paper.
- **QR code:** `\qrcode[height=3.5cm]{https://arxiv.org/abs/…}` to the paper, code or project page. Use only a URL the user gave you.

## Check before printing

```bash
python3 <skill>/../latex-results-sync/scripts/results.py audit poster/   # hand-typed or stale numbers
python3 <skill>/../latex-references/scripts/check_refs.py poster/ --bib paper/references.bib   # undefined refs and citations
```

Then read the poster against the paper's abstract and conclusion (`latex-consistency`): a poster's headline claim often outgrows the paper ("state of the art" vs "competitive on two of three benchmarks").

## tikzposter rules

- Blocks: `\block{Title}{content}` inside `\column{0.5}`; `\coloredbox` for highlights; figures in `\begin{tikzfigure}[caption]`.
- Name colour tints once with `\colorlet{amberlight}{amber!15}` and use the name: tikzposter's `\coloredbox[bgcolor=amber!15]` fails with "Undefined color".
- tikzposter replaces pgf's layer list, so figures drawing `on background layer` fail with "layer 'background' is not part of the layer list". The templates already declare `\pgfsetlayers{backgroundlayer,background,main,notelayer}`; keep that line when you rewrite the preamble.
- `\tikzposterlatexaffectionproofoff` removes the class's footer credit.
- Sizes are relative: `width=0.9\linewidth`, never fixed cm, so a column-width change doesn't break the figures.
- Body text ≥ 24pt at A0 (the template's `25pt` option); titles 72–100pt. For a 24×36 in workshop poster, use the `20pt` option.
- Budget: ~400–500 words and 3–6 figures at A0; 200–300 words on a workshop poster. At most 2–3 equations and 3–6 references.

## Hand-offs

New diagrams → `latex-tikz` · result plots and tables → `latex-tables-figures` · the paper itself → `latex-project` · talk to go with it → `latex-beamer` · compile errors → `latex-debug`.
