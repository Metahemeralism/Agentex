---
name: latex-references
description: "Citations and cross-references: verified BibTeX from DOIs/arXiv (never invented), natbib vs biblatex, cleveref, label conventions, and a linter for undefined or unused labels and citations. Use when adding or fixing references or seeing '??'."
---

# Citations, Bibliography & Cross-References

## Golden rule: never invent a citation

Every bib entry must come from a verifiable source. Do **not** write BibTeX from memory for real papers: authors, years, venues and page numbers are easy to hallucinate. Instead:

1. **DOI** → `curl -sLH "Accept: application/x-bibtex" https://doi.org/<DOI>`
2. **arXiv** → `https://arxiv.org/bibtex/<arXiv-id>` (and prefer the published version if one exists)
3. **Search** (if tools are available): Crossref (`https://api.crossref.org/works?query=...`), Semantic Scholar, DBLP (`https://dblp.org/search?q=...`), Google Scholar export.
4. If none can be verified, insert a placeholder `\cite{TODO-verify-<topic>}` and tell the user; never fabricate.

When the user asks "find a citation for X", return candidates *with links* and let them choose.

## Lint the project

```bash
python3 <this-skill>/scripts/check_refs.py path/to/paper
```

Reports: undefined references, duplicate labels, citations missing from `.bib`, duplicate bib keys (errors), and unreferenced labels / uncited bib entries (warnings). Run it after every non-trivial edit; it's fast and needs only Python.

## Choosing a system

| | BibTeX + `natbib` | BibLaTeX + `biber` |
|---|---|---|
| Use when | venue template requires it (most journals, IEEE, ACM, NeurIPS/ICML) | thesis, preprint, own template |
| Cite commands | `\citet{}` (Author (Year)), `\citep{}` ((Author, Year)) | `\textcite{}`, `\parencite{}`, `\autocite{}` |
| Style | `\bibliographystyle{plainnat}` + `\bibliography{refs}` | `\usepackage[style=authoryear]{biblatex}` + `\addbibresource{refs.bib}` + `\printbibliography` |
| Unicode in .bib | fragile | fine |

**Always follow the venue template.** Never mix natbib and biblatex.

## .bib hygiene

- Keys: `lastnameYEARfirstword` (e.g. `vaswani2017attention`), stable and greppable.
- Protect capitalisation that must survive styles: `title = {Learning {B}ayesian Networks with {LSTM}s}`.
- Use `--` for page ranges, full journal names (or consistent abbreviations), include DOI.
- Remove junk fields from exports (`abstract`, `file`, `keywords`, `mendeley-*`) when the venue's style prints them.
- Deduplicate: same paper as arXiv + published → keep the published one.
- Cite **software and datasets**: use `@software` (biblatex) or `@misc` with `version`, `url`, `doi` (Zenodo), and `howpublished`. If the repo has a `CITATION.cff`, derive the entry from it. Also cite the libraries the results depend on when the venue expects it (e.g. PyTorch, scikit-learn, NumPy).

## Cross-references

- Prefixes: `sec:`, `subsec:`, `fig:`, `tab:`, `eq:`, `alg:`, `lst:`, `app:`, `thm:`, `lem:`, `def:`.
- `\label` immediately **after** `\caption` (floats) or inside the environment (equations, sections).
- Prefer `cleveref`: `\cref{fig:a,fig:b}` → "Figures 1 and 2"; `\Cref` at sentence start. Load after `hyperref`.
- Without cleveref: `Figure~\ref{fig:a}`, `Eq.~\eqref{eq:loss}` (always the non-breaking `~`).
- `??` in the PDF = undefined label *or* not enough compile passes. Run `latexmk` (it reruns as needed) before concluding the label is missing.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `Citation 'x' undefined` | key missing/typo, or bib tool not run | `check_refs.py`; run `latexmk` |
| Empty bibliography | `\bibliography{}`/`\addbibresource{}` path wrong, or nothing cited | check path (`.bib` extension needed for `\addbibresource`) |
| `I found no \bibdata command` | BibTeX run on a biblatex document | use `biber` (or set `backend=bibtex`) |
| Refs point to section numbers | `\label` before `\caption` | move label after caption |
| `Package natbib Error: Bibliography not compatible with author-year citations` | numeric bst + natbib authoryear | use `plainnat`/venue bst, or `\usepackage[numbers]{natbib}` |
