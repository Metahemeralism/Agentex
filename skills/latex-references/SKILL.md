---
name: latex-references
description: "Verify every citation against Crossref, arXiv, DBLP, Semantic Scholar and OpenAlex (catches fabricated and Frankenstein references), build BibTeX from DOIs, set up natbib/biblatex and cleveref, and lint labels and citations. Use when citing, fixing references or seeing '??'."
---

# Citations, Bibliography & Cross-References

## Golden rule: never invent a citation

Hallucinated references survive peer review: in 2025 roughly one in twenty NeurIPS and USENIX Security papers had at least two likely hallucinated references (Phantom References, arXiv:2607.00738). An LLM checking its own citations is not enough. **An authoritative database lookup makes the final call.**

### 1. Verify (deterministic)

```bash
python3 <skill>/scripts/cite_verify.py paper/              # every cited key
python3 <skill>/scripts/cite_verify.py paper/ --keys k1,k2 # just new keys (fast)
python3 <skill>/scripts/cite_verify.py paper/ --suggest    # corrected entries -> .agentex/suggested.bib
```

| Status | Meaning | Action |
|---|---|---|
| `verified` | found; title, authors and year agree | none |
| `published` | arXiv preprint with a published version | offer to cite the published version |
| `mismatch` | the work exists, but your entry's title/authors/year are wrong ("Frankenstein") | show the diff from `--suggest`; apply after approval |
| `bad-doi` | DOI/arXiv id dead or pointing to a different work | fix the identifier |
| `not-found` | no match anywhere | **treat as fabricated until the author shows the source** |
| `unverifiable` | book/thesis/software/web page not indexed | check by hand (URL, ISBN, Zenodo DOI) |

Rules: never edit the user's `.bib` silently. Present `--suggest` output as a diff and wait for approval. Results are cached in `.agentex/` (which ignores itself in git), so re-runs are instant. Set `S2_API_KEY` for reliable preprint→published detection (Semantic Scholar rate-limits anonymous use) and `AGENTEX_MAILTO` for Crossref's polite pool. dblp currently blocks scripted access behind a bot check, so the tool skips it automatically when that happens.

**Cite guard (plugin hook):** with the AgenTeX plugin installed, an edit that adds a `\cite{key}` whose entry isn't verified is blocked, and the block message gives the exact verify command. Don't work around it: verify, or tell the user the source can't be confirmed.

### 2. Get entries from sources, never from memory

1. **DOI** → `curl -sLH "Accept: application/x-bibtex" https://doi.org/<DOI>`
2. **arXiv** → `https://arxiv.org/bibtex/<arXiv-id>`, and prefer the published version if one exists
3. **Search** with `latex-research-check` or the APIs above, then run `cite_verify.py` on the result.
4. If nothing verifies, insert `\cite{TODO-verify-<topic>}` and tell the user. Never fabricate.

When the user asks "find a citation for X", return candidates *with links* and let them choose.

### 3. Lint labels and keys

```bash
python3 <skill>/scripts/check_refs.py paper/
```

Reports undefined references, duplicate labels, citations missing from `.bib` and duplicate bib keys (errors), plus unreferenced labels and uncited entries (warnings).

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
