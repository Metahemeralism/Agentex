---
name: latex-documents
description: "Use for LaTeX documents that are not research papers, from tested templates: ATS-safe resumes, academic CV, cover and formal letters, invoices, homework, lab reports, lecture notes, exams with answer keys, cheat sheets, books, fillable PDF forms, CSV/JSON mail merge."
---

# LaTeX Documents (beyond the paper)

Goal: a document that compiles first time, looks right on the page, and contains nothing the user didn't give you. Every template is test-compiled.

## Workflow

1. **Pick the template** (table below). Papers and theses next to code → `latex-project`; posters → `latex-poster`; slides → `latex-beamer`.
2. **Ask only what you can't infer**, in one round (Claude Code: `AskUserQuestion`). Resumes: target role, page limit, applying through an ATS portal? Exams: answer key too? Letters/invoices: sender details.
3. **Copy, then edit in place:** `cp <skill>/templates/<name>.tex .`, then change only what differs.
4. **Use the user's facts only.** Never invent employers, degrees, dates, grades, publications, metrics, prices or signatures. Leave a visible `\textbf{[TODO: …]}` and list what's missing in your reply.
5. **Build and look:** `python3 <skill>/../latex-debug/scripts/build.py <name>.tex --preview previews --pages all`. It picks the engine, prints a short digest and the page count, and writes PNGs. Look for overflow, a CV spilling three lines onto page 2, and widowed headings.
6. **Finish the PDF** if asked (compress, encrypt, PDF/A, merge) → `latex-pdf`.

## Templates (`templates/`)

| Request | Template | Notes |
|---|---|---|
| Resume via an ATS portal | `resume-classic-ats.tex` | no graphics or icons: the safest parse |
| Resume: tech/corporate · senior · engineering · new graduate | `resume-modern-professional` · `-executive` · `-technical` · `-entry-level` | fontawesome5 contact icons (see ATS below) |
| Academic CV | `academic-cv.tex` | publications, grants, teaching, service, ORCID |
| Cover letter · formal letter · invoice | `cover-letter` · `letter` · `invoice` | letter has a TikZ letterhead and logo placeholder |
| Homework / problem set | `homework.tex` | `\showsolutionstrue/false`, code listings |
| Lab report | `lab-report.tex` | siunitx uncertainties, pgfplots, error analysis |
| Lecture notes | `lecture-notes.tex` (scrartcl) | tcolorbox theorem boxes, graph macros; `latex-convert` uses it for notes |
| Exam / quiz | `exam.tex` (exam class) | points table, question types, `\printanswers` |
| Cheat sheet: general · exam formula sheet · code card | `cheatsheet` · `cheatsheet-exam` · `cheatsheet-code` | read `reference/cheatsheets.md` first |
| Book · thesis front matter · business report | `book` · `thesis` · `report` | thesis: declaration, roman-numbered front matter |
| Fillable PDF form | `fillable-form.tex` | hyperref text fields, checkboxes, dropdowns |
| Configurable document | `conditional-document.tex` | etoolbox toggles, draft/confidential, 3 profiles |
| Mail-merge letter | `mail-merge-letter.tex` | for `scripts/mail_merge.py` |

## Two versions from one source

Never keep two copies of an exam or problem set. A one-line wrapper builds the other version with any engine:

```bash
printf '\\AtBeginDocument{\\printanswers}\\input{exam}\n' > exam-key.tex
printf '\\AtBeginDocument{\\showsolutionsfalse}\\input{homework}\n' > homework-student.tex
```

The same works for `conditional-document.tex` (`\AtBeginDocument{\toggletrue{isDraft}}`, `\def\doctitle{Q4}\input{…}`).

## Mail merge (one document per CSV/JSON record)

```bash
python3 <skill>/scripts/mail_merge.py letter.tex people.csv --check     # validate every record, write nothing
python3 <skill>/scripts/mail_merge.py letter.tex people.csv -o merged --name '{{last}}-{{first}}'
ls merged/*.tex | xargs -P 4 -n 1 python3 <skill>/../latex-debug/scripts/build.py
python3 <skill>/../latex-pdf/scripts/pdftool.py merge all.pdf merged/*.pdf
```

`{{key}}` is escaped for LaTeX; `{{{key}}}` inserts raw LaTeX; `{{a.b}}` reads nested JSON; `{{#list}}…{{/list}}` loops over a list, or shows the block if the value is truthy; `{{^key}}…{{/key}}` shows it if falsy. A record missing a key stops the merge before anything is written. Merged files sit one folder down, so use `\graphicspath{{../}}`. JSON (a list, or `{"records": […]}`) is for lists and nested fields; CSV for flat ones.

## Resumes: check what the ATS reads

- Single column, no tables or minipages for layout, nothing in headers/footers, standard headings (Experience, Education, Skills), dates as `Jan 2023 -- Present`.
- **Verify with `pdftotext -layout resume.pdf -`**: it shows roughly what a parser extracts. Name, email, phone and dates must come out intact and in reading order. Icons from `fontawesome5` come out as junk (`Ȱ Л ć`), so for portals use `resume-classic-ats.tex` or drop the icons. Ligatures come out as `ﬁ` under XeLaTeX. The resume templates load `glyphtounicode` for pdfLaTeX, which fixes that, so build resumes with pdfLaTeX.
- One page up to ~10 years of experience. Start every bullet with a verb and a result, using numbers only if the user supplied them.

## Long documents (5+ pages): what agents get wrong

- Walls of bullets: prose is the default in reports. A 40-page report needs fewer than ~15 lists; use tables for parallel items.
- `\newpage` before every section, `[H]` on every float and images at `0.95\textwidth` leave half-empty pages. Use `[htbp]`, widths of 0.75–0.85, and page breaks only between major parts.
- Compact lists globally: `\setlist{nosep, leftmargin=*}` (enumitem).
- Every section built the same way (intro sentence → bullets → bold line) reads as generated. Vary the format.

## What AgenTeX adds to these templates

- **CV publications are verified, not typed:** put the papers in a `.bib` from their DOIs/arXiv ids, run `latex-references`' `cite_verify.py --all`, then list them with biblatex. Never write a publication, venue or metric from memory.
- **Lab reports take numbers from code:** measurements and fits go into `\res{}` macros and `results.py table data.csv` tables (`latex-results-sync`), so `results.py audit` catches hand-typed values.
- **Theses and books** get the paper toolchain: `texmap.py` and `texstats.py` (word limits) from `latex-project`, cite verification, and a PDF/A copy from `build.py --pdfa`.

## LaTeX rules that bite in these documents

- Escape `% $ & # _ { }`. Without `\usepackage[T1]{fontenc}` (the default OT1 encoding), `<` and `>` in text print as ¡ and ¿: load T1 or write `\textless`/`$<$`.
- `\rowcolor` needs `colortbl` (or `xcolor[table]`); `\checkmark` needs `amssymb`; `[H]` needs `float`.
- CJK or other non-Latin scripts: `fontspec`/`xeCJK`; `build.py` switches to XeLaTeX on its own.
