# Cheat sheets and reference cards

Condensed from latex-document-skill's cheat-sheet guide (MIT; see ../NOTICE.md).

## Ask first (one round)

Type (general reference card · exam formula sheet · programming card), source material (their PDFs/notes, or a topic), length (1 page or front+back), and printer (colour, or black and white).

| Type | Template | Layout | LaTeX-source budget per page |
|---|---|---|---|
| General reference card | `cheatsheet.tex` | landscape, 3 columns, 7pt | ~8,000 characters |
| Exam formula sheet | `cheatsheet-exam.tex` | portrait, 2 columns, 6pt, B&W-safe | ~4,500 characters |
| Programming card | `cheatsheet-code.tex` | landscape, 4 columns, 7pt, monospace code boxes | ~9,000 characters |

## Fill to the budget, not past it

Agents write 1.5–2.5× too much for a cheat sheet. Write page 1 within budget, build (`build.py` prints the page count), then page 2. If it's over the limit, cut the lowest-priority items. Don't shrink the font below the template's size.

## Layout rules that save the most space

- **One `multicols*` for the whole sheet.** Content flows p1c1 → p1c2 → … → p2c3. Never close it, `\newpage` and reopen: that leaves empty columns.
- **Plain `\section*` with `\titlerule`, not a `tcolorbox` per section.** Each box costs ~10 mm. Keep boxes for 2–3 critical callouts.
- **Inline formulas** separated by `\quad`; **`tabular` for pairs** (`\int x^n` & `\frac{x^{n+1}}{n+1}`), not `itemize`.
- Tight spacing: `\setlist{nosep}`, `\setlength{\parskip}{0pt}`, `\setlength{\abovedisplayskip}{0.5pt}`, `\linespread{0.92}`. Below 0.9, fractions and superscripts collide.
- For 4 columns, add `\sloppy` inside `multicols*`.

## Content

- Remind, don't teach: definitions, formulas with their conditions, edge cases, syntax. No derivations, no prose. Telegraph style is fine.
- From course material: 5–20 source pages → keep most key results; 20–50 → definitions, key theorems, formulas; 50+ → only what is examinable. Use past papers to rank topics if the user has them. Convert PDFs first with `latex-convert`.
- **Every formula comes from the source, never from memory.** Check each one against the page it came from; a wrong sign on an exam sheet costs marks. Mark anything unverified `\textbf{[check]}`.
- Black-and-white printing: never encode meaning only in colour. Print a test page: 6pt is the floor for most eyes.
