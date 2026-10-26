---
name: latex-beamer
description: "Turn a paper or project into a timed Beamer talk: storyline, claim-style slide titles, reused figures and notation, overlays, speaker notes and Beamer error fixes. Use for slides, conference talks, seminars or defences."
---

# Beamer Presentations

A talk is not a paper read aloud. Slides carry **one idea each**, the speaker carries the detail.

## Workflow: paper/code → talk

1. **Ask**: talk length, audience (specialists, general CS, examiners), venue format (16:9 vs 4:3), and any institutional theme.
2. **Budget**: roughly 1 slide per minute. A 15-minute talk ≈ 12–15 content slides.
3. **Storyline first** (bullet outline, agree with user before writing LaTeX):
   Title → Problem & why it matters → Key idea (one picture) → Method (2–4 slides) → Main result (1–2 slides) → Ablation/insight → Limitations → Take-home message → Backup slides.
4. **Reuse assets** from the paper: `\input` the same `macros.tex` so notation is identical; include the same figure PDFs/TikZ (scaled up: fonts in slides need to be ~2× paper size); never screenshot equations.
5. **Write:** `cp templates/talk.tex talk.tex`, then edit frame by frame. Don't regenerate the whole deck to change one slide.
6. **Compile** (`latexmk -pdf talk.tex`) and check for overflow: `Overfull \vbox` means content falls off a slide. Use `python3 <skill>/../latex-debug/scripts/texlog.py talk.log` to list them instead of reading the log.

## Slide rules

- Slide titles are **claims**, not topics: "Clipping halves divergence rate", not "Results".
- ≤ 6 lines of text; no full sentences in bullets; no paragraphs.
- One equation per slide, only if you'll talk through it; highlight the important term (`\alert{}` or a coloured box).
- Big figures: `\includegraphics[width=\textwidth]` with large, readable axis labels (re-export plots at slide size).
- Code on slides: ≤ 10 lines, `[fragile]` frame, large font.
- Use overlays (`\pause`, `\onslide<2->`, `\only<2>`, `\item<+->`) to build up complex diagrams or arguments, not for every bullet.
- Backup slides after `\appendix` (they don't count in the frame total with `appendixnumberbeamer`).
- Speaker notes: `\note{...}`; render with `\setbeameroption{show notes on second screen=right}` for presenter view (e.g. pdfpc).

## Common errors

| Error | Fix |
|---|---|
| `Paragraph ended before \lst@next was complete` / verbatim errors | add `[fragile]` to the frame |
| Content cut off at bottom | split the frame, or `[shrink]` as a last resort |
| `\section` in TOC but no headline | theme doesn't show navigation; fine, or use `\AtBeginSection` agenda slide |
| Figures blurry | use PDF/vector, not PNG screenshots |
| Overlay numbering off | `\item<+->` counts per frame; check `\pause` mixed with explicit `<n->` |
| `hyperref` option clash | Beamer loads hyperref itself: use `\hypersetup{}`, don't `\usepackage{hyperref}` |

## Themes

Default to a clean minimal setup (`metropolis` if installed, else `default` with `\usecolortheme{seahorse}` or `beaver`). Remove navigation symbols. Respect institutional themes when provided; don't restyle them.

Poster for the same paper → `latex-poster` (same macros, figures and `\res{}` numbers).
