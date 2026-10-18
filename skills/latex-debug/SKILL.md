---
name: latex-debug
description: "Fix LaTeX compile errors and warnings: a log digest script, an error lookup table and a bisection workflow for undefined commands, missing packages, Unicode, floats, TikZ and bibliography failures. Use whenever compilation fails or shows '??'."
---

# LaTeX Compile Debugging

## Workflow

With the AgenTeX plugin installed, a Stop hook already compiles after LaTeX edits and hands you this digest automatically; fix what it reports before finishing.

1. **Compile non-interactively** so errors don't hang:
   `latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error main.tex`
   (no toolchain? read the user's `.log`, or ask them to paste it from Overleaf → Logs → Raw logs).
2. **Fix the first error only**, then recompile. Later errors are usually cascades.
3. **Digest the log; don't read it.** `python3 scripts/texlog.py main.log` prints the first errors with `file:line` and source context, and groups the warnings (~20 lines instead of thousands). The `l.NN` line shows where TeX *noticed* the problem, which is often just after the real cause, so open only a few lines around it.
4. **Bisect** if the message is unhelpful: comment out half the body (or `\end{document}` early) until the error disappears; for preamble issues, comment out packages one at a time.
5. After errors are gone, triage warnings (below). Rerun until "Label(s) may have changed" disappears; `latexmk` does this automatically.

## Error lookup

| Message | Usual cause | Fix |
|---|---|---|
| `Undefined control sequence` | typo, or package not loaded | check spelling at `l.NN`; load package (e.g. `\mathbb` → `amssymb`, `\SI` → `siunitx`, `\cref` → `cleveref`) |
| `File 'x.sty' not found` | package not installed | `tlmgr install x` / MiKTeX auto-install / Overleaf has all |
| `Missing $ inserted` | maths outside math mode (`_`, `^`, `\alpha`) or text `_` | wrap in `$…$`; escape `\_` in text |
| `Missing } inserted` / `Extra }` | unbalanced braces | check the lines just *before* `l.NN` |
| `Runaway argument? Paragraph ended before X was complete` | missing `}` or blank line inside an argument | close the brace; no blank lines in macro args |
| `Environment X undefined` | package missing or typo | load package / fix name |
| `\begin{X} ended by \end{Y}` | mismatched environments | match nesting |
| `Option clash for package X` | loaded twice with different options | load once with all options, or `\PassOptionsToPackage` before `\documentclass` |
| `Command \X already defined` | two packages/macro definitions collide | use `\renewcommand` or remove one package (e.g. `algorithm2e` vs `algpseudocode`) |
| `Package inputenc Error: Unicode character` | non-ASCII under pdfLaTeX (`θ`, `–`, `’`, `μ`) | replace with LaTeX (`$\theta$`, `--`), `\DeclareUnicodeCharacter`, or compile with LuaLaTeX |
| `Too many unprocessed floats` | many figures without text between | `\clearpage`, fewer floats, or `[tbp]` placement |
| `Dimension too large` | TikZ/pgfplots with huge coordinates | rescale data, `\pgfplotsset{compat=…}`, or `fpu` library |
| `I can't find file` for `\input`/`\includegraphics` | wrong relative path / case sensitivity (Overleaf is Linux) | fix path; match case exactly |
| `Not in outer par mode` | float inside a box/minipage/another float | use `subfigure`, or `[H]` from `float` sparingly |
| `Package tikz Error: Giving up on this path` | missing `;` or unknown library/key | add `;`, load library |
| `You must invoke LaTeX with the -shell-escape flag` | `minted`/`svg`/`externalize` | add `-shell-escape` (or `\usepackage[frozencache]{minted}`) |
| biber: `data source not found` | `\addbibresource` path wrong / missing `.bib` extension | fix path |
| BibTeX: `I found no \citation commands` | nothing cited or wrong aux | cite something / clean build (`latexmk -C`) |
| Overleaf timeout | huge TikZ/pgfplots, large images | `tikz externalize`, compress images, draft mode while writing |

## Warning triage

- `Reference/Citation ... undefined`: rerun; if persistent, `latex-references/scripts/check_refs.py`.
- `Overfull \hbox (Xpt too wide)`: > ~2pt is visible. Fix: rephrase, allow hyphenation (`\-`), break long URLs (`\url` + `xurl`), shrink tables properly. `microtype` removes many.
- `Underfull \hbox/\vbox`: usually from manual `\\` or `\newline` in paragraphs; remove them.
- `Font shape … undefined, using … instead`: missing bold/italic of a font; load `lmodern` or a complete font package.
- `Float too large for page`: resize to `\textheight`/`\linewidth`.
- `There were multiply-defined labels`: duplicate `\label`; the checker script finds them.

## Hygiene

- Clean stale aux files when errors seem impossible: `latexmk -C`.
- Use `-file-line-error` always; it makes logs greppable: `grep -nE '^(.*\.tex:[0-9]+:|!)' main.log`.
- When asking for help, provide a minimal working example: `\documentclass{article}` + the needed packages + the failing snippet.
