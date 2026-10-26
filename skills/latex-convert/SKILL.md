---
name: latex-convert
description: "Convert into and out of LaTeX: Markdown, Word and HTML via Pandoc; PDFs, scans and handwritten notes page by page (maths, business, legal, general profiles); Mermaid, Graphviz and PlantUML diagrams; latexdiff change-tracked PDFs between versions or git tags."
---

# Conversion into and out of LaTeX

Conversion output is a draft. After any conversion *into* LaTeX: compile it, verify every citation, and turn numbers that come from code into `\res{}` macros. That is what AgenTeX adds over a plain converter.

## A. Markdown / Word / HTML ↔ LaTeX (Pandoc)

```bash
pandoc notes.md -s -o notes.tex                                   # Markdown -> standalone LaTeX
pandoc draft.docx -s --extract-media=figures -o draft.tex         # Word -> LaTeX, images saved
pandoc paper.tex -s --citeproc --bibliography=refs.bib -o paper.docx   # LaTeX -> Word for co-authors
pandoc paper.tex -s --mathjax -o paper.html                       # LaTeX -> HTML
```

Then, for a document that will be published:
1. Put the body into a real template (`latex-project` for papers, `latex-documents` otherwise) rather than shipping Pandoc's default preamble.
2. Citations: add `--natbib` (or `--biblatex`) so Markdown `[@key]` becomes `\citep{key}` (`\autocite`); Word reference lists arrive as plain text. Rebuild the `.bib` from DOIs and run `latex-references`' `cite_verify.py` before trusting a single entry.
3. Build: `python3 <skill>/../latex-debug/scripts/build.py out.tex --preview previews`.

Pandoc's LaTeX tables are `longtable`s and its figures may lack labels; move them into floats with `\label`s before writing the text that references them.

## B. PDF, scan or handwriting → LaTeX

1. **Pick a profile** from `reference/profiles/`: `math-notes.md` (equations, theorems; "beautiful mode" uses `latex-documents/templates/lecture-notes.tex`), `business-document.md`, `legal-document.md`, `general-notes.md`.
2. **Render pages** at a size vision models read well:
   `python3 <skill>/../latex-pdf/scripts/pdftool.py preview in.pdf --pages all --max-px 2000 -o tmp/pages`
   For a born-digital PDF, extract the text first (`pdftotext -layout in.pdf tmp/text.txt`) and use the images only for maths, tables and layout.
3. **Write one shared preamble** (`tmp/preamble.tex`) before any page, so every batch uses the same macros and environments.
4. **Convert in batches:** 1–10 pages in one pass; 11–20 in two halves; 21+ in batches of 7 pages (`tmp/batch_001_007.tex`, …), body only. Batches are independent, so when the user agrees to parallel agents, give each one a batch, the preamble and the profile, using the worker prompt in `reference/pdf-conversion.md`. Otherwise do them in order.
5. **Check every batch before assembling:**
   `python3 <skill>/scripts/check_fragments.py tmp/batch_*.tex --preamble tmp/preamble.tex`
   It reports unbalanced environments, undefined commands, floats inside tcolorbox, TikZ outside a picture and stray `&`.
6. **Assemble and build** (commands in `reference/pdf-conversion.md`, "Step 7"), then compare the page previews against the original side by side.

Transcribe; don't improve. Keep the author's wording, numbering and notation. Mark anything illegible `\textbf{[illegible]}` instead of guessing, especially numbers, names and citations.

## C. Diagram languages → figures

| Source | Command | Note |
|---|---|---|
| Graphviz `.dot` | `dot -Tpdf g.dot -o g.pdf` (`neato`, `circo`, … for other layouts) | `dot2tex` emits TikZ that matches the paper's fonts |
| PlantUML `.puml` | `plantuml -tpdf d.puml` (or `-tsvg`) | needs Java |
| Mermaid `.mmd` | `mmdc -i d.mmd -o d.pdf --pdfFit` | `npm i -g @mermaid-js/mermaid-cli` |

Include the PDF with `\includegraphics`. For a figure in a paper, redrawing it with `latex-tikz` gives matching fonts, greyscale safety and an editable source. Use these converters for internal documents, slides and drafts.

## D. Change-tracked PDF between versions (latexdiff)

For revisions, camera-ready changes and rebuttals ("changes are marked in blue"):

```bash
git tag v1-submitted                                            # once, when you submit
latexdiff-vc --git --flatten -r v1-submitted main.tex           # -> main-diffv1-submitted.tex (multi-file is fine)
python3 <skill>/../latex-debug/scripts/build.py main-diffv1-submitted.tex
latexdiff old.tex new.tex > diff.tex                            # two loose files
```

If the diff file won't compile: `--math-markup=coarse` (whole equations), `--exclude-safecmd="SI,qty,num"` (errors inside unit macros), `--append-safecmd=res` (show changed `\res{}` numbers), or `--config="PICTUREENV=(?:picture|tikzpicture|DIFnomarkup)[\w\d*@]*"` so TikZ is shown, not diffed. `--type=CULINECHBAR` adds change bars, which journals like. One sentence per line in the sources keeps the diff readable.

## Hand-offs

Templates for converted content → `latex-documents`, `latex-project` · citations → `latex-references` · numbers from code → `latex-results-sync` · TikZ redraws → `latex-tikz` · compile errors → `latex-debug` · rebuttal letters → `latex-review`.
