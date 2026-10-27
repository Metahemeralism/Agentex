---
name: latex-pdf
description: "Finish and process PDFs: previews, merge, split or extract pages, compress, encrypt, PDF/A, submission checks (embedded fonts, page size, count), watermarks, and filling fillable or flat forms. Use after compiling or on an existing PDF; PDF-to-LaTeX is latex-convert."
---

# PDF Finishing and Processing

One script, `scripts/pdftool.py` (stdlib), uses whatever is installed (qpdf, Ghostscript, pdftk, poppler) and falls back to LaTeX's `pdfpages` when they're missing. It refuses to overwrite its input, and it writes nothing when a check fails.

| Task | Command |
|---|---|
| What is this PDF? | `pdftool.py info paper.pdf` (pages, page size, PDF version, encryption, form, fonts **not embedded**) |
| Look at pages | `pdftool.py preview paper.pdf --pages 1-3 --dpi 80 -o previews` (`--max-px 2000` for vision-model input) |
| Merge | `pdftool.py merge out.pdf a.pdf b.pdf c.pdf` |
| Extract / reorder pages | `pdftool.py pages in.pdf '1-3,7,last:2' -o out.pdf` (also `odd`, `even`, `5-`) |
| Compress for email/web | `pdftool.py compress in.pdf -o small.pdf --quality ebook` (`screen` < `ebook` < `printer` < `prepress`) |
| Password-protect | `pdftool.py encrypt in.pdf -o locked.pdf --password '…' [--no-print] [--no-modify]` |
| Watermark | `pdftool.py watermark in.pdf 'DRAFT' -o draft.pdf` |
| Fill a form | see "Forms" below |
| PDF/A (archival, thesis) | `python3 <skill>/../latex-debug/scripts/build.py thesis.tex --pdfa` → `thesis-pdfa.pdf` |
| Tagged, accessible PDF (PDF/UA-2) | `python3 <skill>/../latex-debug/scripts/build.py thesis.tex --tagged en` → `thesis-tagged.pdf` (LuaLaTeX via latexmk) |

`<skill>` is this skill's folder; run as `python3 <skill>/scripts/pdftool.py …`.

## Rules

- **Passwords come from the user.** Ask for it, never invent or "suggest" one, don't write it into files or commit it, and remind the user that nobody can recover it.
- **Look before you hand over.** After overlay, watermark, page surgery or compression, preview the result (`preview --pages all`). Ghostscript compression can blur figures; if the saving is small, keep the original.
- **Fallback limits:** the LaTeX fallback (`pdfpages`) produces a flattened copy, so links, bookmarks and form fields are lost. `info` and `preview` need poppler (`brew install poppler`, `apt install poppler-utils`). Encryption, field reading and lossless compression need qpdf; filling fillable forms needs pdftk.

## Submission checks (before uploading to a venue, arXiv or a print shop)

`pdftool.py info paper.pdf` and check:
- **Fonts: all embedded.** IEEE PDF eXpress, ACM and most print shops reject non-embedded fonts. A Type 3 or missing font usually comes from a matplotlib figure: replot with `pdf.fonttype: 42` or save as PGF (`latex-tables-figures`).
- **Page size** matches the venue (US letter vs A4; set it in `geometry` or the class option).
- **Page count** is within the limit, counting only the pages the venue counts (main text, not references or appendix).
- **Not encrypted** and no form fields, unless intended: submission systems reject protected PDFs.

## PDF/A and accessibility

`build.py --pdfa` compiles with `\DocumentMetadata{pdfstandard=A-2b}` (LaTeX 2022-06 or newer, via latexmk) into a separate `<name>-pdfa.pdf`, so the normal build is untouched. University repositories often require PDF/A. Validate with veraPDF when it's available. On TeX installations older than 2022, `\usepackage[a-2b]{pdfx}` (with a `\jobname.xmpdata` file) is the alternative.

For a tagged, screen-reader-accessible PDF, run `build.py thesis.tex --tagged [LANG]`. It writes `thesis-tagged.pdf` with `\DocumentMetadata{lang=en, pdfstandard=ua-2, tagging=on}`, which gives PDF 2.0 and PDF/UA-2. You can't combine it with `--pdfa`, because PDF/A-2b is PDF 1.7. Per the LaTeX Tagging Project (latex3.github.io/tagging-project, checked 2026-10), it needs LaTeX 2025-11-01 or newer; the 2025-02 prototype used `testphase=latest` instead. The engine is LuaLaTeX by default, which also embeds MathML for equations. pdfLaTeX works with `--engine pdflatex`, but XeLaTeX and tectonic don't support tagging. The author still has to supply:
- `\includegraphics[alt={…}]` for every figure (draft it as in `latex-arxiv`), or `artifact` for decoration;
- `\tagpdfsetup{table/header-rows={1}}` for data tables.

Check the result with `pdfinfo` (`Tagged: yes`) and `verapdf --flavour ua2`. Packages that aren't tagging-compatible yet are listed at latex3.github.io/tagging-project/tagging-status.

## Forms

**Fillable** (`pdftool.py fields form.pdf` lists fields):
1. Write `values.json`: `{"Full name": "Ada Lovelace", "Agree": "Yes"}`. Use exactly the listed names; checkbox, radio and choice values must be one of the listed options.
2. `pdftool.py fill form.pdf values.json -o filled.pdf`, or add `--flatten` to make the values permanent.

**Flat** (scanned or no fields):
1. `pdftool.py preview form.pdf --pages all --dpi 100 -o tmp/pages` and look at the pages.
2. Measure each entry box on the PNG in pixels, then write `spec.json`: `{"dpi": 100, "items": [{"page": 1, "box": [left, top, right, bottom], "text": "Ada", "size": 11}]}`.
3. `pdftool.py overlay form.pdf spec.json -o filled.pdf`. It checks that each page exists, that the text fits its box and that boxes don't overlap, then writes the text with LaTeX at those positions.
4. Preview `filled.pdf` and fix any box that is off.

Fill only with data the user provided. Leave unknown fields empty and list them; never guess an ID number, date or signature.

To *create* a fillable form, use `latex-documents/templates/fillable-form.tex`.

## Beyond the script

Plain text: `pdftotext -layout in.pdf -`. Images: `pdfimages -png in.pdf out/img`. Rotation: `qpdf in.pdf --rotate=+90:1-3 -- out.pdf`. Tables, OCR or building PDFs in code need Python libraries (pdfplumber, pytesseract, pypdf, reportlab), which are the user's to install. To turn a PDF into editable LaTeX, use `latex-convert`.
