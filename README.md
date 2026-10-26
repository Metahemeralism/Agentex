<div align="center">

<img src="docs/logo/agentex-logo.svg" alt="AgenTeX" width="440">

**Keep your LaTeX paper honest to the code behind it.**

Verified citations · numbers that can't go stale · a build that fixes itself · publication-grade TikZ · arXiv-ready packages

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Skills](https://img.shields.io/badge/skills-18-informational)
![Hooks](https://img.shields.io/badge/hooks-2-informational)
![Dependencies](https://img.shields.io/badge/scripts-stdlib%20only-success)

</div>

---

AgenTeX is a Claude Code plugin ([Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) plus hooks) for researchers whose results live in code and whose papers live in LaTeX.

Beyond the paper, the same checks carry over to posters, theses, CVs, exams, letters and mail merges (24 templates, each test-compiled). AgenTeX also converts Markdown, Word, PDFs and handwritten notes into LaTeX, and finishes PDFs: PDF/A, form filling, compression, encryption.

Prose polishing is already well served by many tools. AgenTeX targets the problems where an agent with a shell, logs and APIs beats both chat assistants and editors, and it solves them with **deterministic tools that make the final call**, with the LLM organising the work and explaining the results.

## Why

- **Fabricated references survive peer review.** In 2025, "roughly one in twenty NeurIPS and USENIX Security papers contains at least two likely hallucinated" references (*Phantom References*, [arXiv:2607.00738](https://arxiv.org/abs/2607.00738)). 100 fabricated citations reached 53 accepted NeurIPS 2025 papers despite "review by 3-5 expert researchers per paper" ([arXiv:2602.05930](https://arxiv.org/abs/2602.05930)).
- **Numbers drift.** A rerun changes 87.3 to 86.9, but the abstract still says 87.3, and nobody remembers which script made `fig3.pdf`.
- **Compiling isn't correctness.** The vTikZ benchmark finds that current LLMs "struggle to reliably modify code in alignment with visual intent" ([arXiv:2505.04670](https://arxiv.org/abs/2505.04670)). Agents need to check the log *and* look at the result.

*(Each source was checked with AgenTeX's own `cite_verify.py`, and each quote against its abstract.)*

## Three guarantees

| | What you get | How |
|---|---|---|
| **1 · Citations are real** | Every cited entry is resolved against Crossref, arXiv, Semantic Scholar, OpenAlex and dblp, then classified as *verified*, *mismatch* ("Frankenstein" metadata), *bad-doi*, *not-found* (likely fabricated) or *published* (preprint has a published version). A **cite-guard hook** blocks the agent from adding any `\cite` whose entry isn't verified. | [`cite_verify.py`](skills/latex-references/scripts/cite_verify.py) + [`hooks/cite_guard.py`](hooks/cite_guard.py) |
| **2 · Numbers come from code** | Results JSON → `\res{exp.acc}` macros. An audit finds **stale** numbers (equal to a *previous* value of a result), hard-coded numbers and undefined keys. Generated booktabs tables. A provenance lock records the script, input hashes and commit behind every figure, and rebuilds stale ones. | [`results.py`](skills/latex-results-sync/scripts/results.py) |
| **3 · The build stays green** | After a turn that edited LaTeX, a **compile-loop hook** builds the paper. If there are errors or new undefined references or citations, it hands the agent a short digest to fix before you ever see the broken PDF (it gives up after 3 attempts). | [`hooks/compile_loop.py`](hooks/compile_loop.py) + [`texlog.py`](skills/latex-debug/scripts/texlog.py) |

Changes to references and numbers are never applied silently. Corrections are written as suggestions (`.agentex/suggested.bib`, audit replacements) for you to approve as a diff.

## Gallery

Tested TikZ patterns from [`latex-tikz`](skills/latex-tikz/SKILL.md), about 20 lines each on one shared style sheet. The agent copies the closest one, edits only what differs, then renders and *looks* at the result.

<table>
<tr>
<td align="center"><img src="docs/gallery/transformer.png" height="230"><br><sub>Transformer block</sub></td>
<td align="center"><img src="docs/gallery/pgm.png" height="150"><br><sub>Graphical model with plates</sub></td>
<td align="center"><img src="docs/gallery/plot.png" height="150"><br><sub>pgfplots with ±1 sd band</sub></td>
</tr>
<tr>
<td align="center"><img src="docs/gallery/cnn.png" width="300"><br><sub>Network with tensor shapes</sub></td>
<td align="center"><img src="docs/gallery/mlp.png" height="150"><br><sub>MLP from layer sizes</sub></td>
<td align="center"><img src="docs/gallery/geometry.png" height="140"><br><sub>Exact geometric construction</sub></td>
</tr>
<tr>
<td align="center"><img src="docs/gallery/pipeline.png" width="300"><br><sub>Pipeline with feedback loop</sub></td>
<td align="center"><img src="docs/gallery/fsm.png" height="100"><br><sub>State machine</sub></td>
<td align="center"><img src="docs/gallery/matrix.png" height="130"><br><sub>Matrix with dimension braces</sub></td>
</tr>
</table>

## Skills

| | Skill | What it does |
|---|---|---|
| **Verify** | [`latex-references`](skills/latex-references/SKILL.md) | Citation verification against five databases, BibTeX from DOIs, natbib/biblatex setup, label/citation linter |
| | [`latex-results-sync`](skills/latex-results-sync/SKILL.md) | Results registry → macros, stale/hard-coded number audit, generated tables, figure provenance and rebuilds |
| | [`latex-consistency`](skills/latex-consistency/SKILL.md) | Paper ↔ code audit: equations vs implementation, hyperparameters vs configs, overclaims, leakage red flags |
| | [`latex-debug`](skills/latex-debug/SKILL.md) | `build.py` picks the engine (XeLaTeX for `fontspec`/CJK), flags missing packages before compiling, makes PDF/A copies and previews; log digest (a 1,150-line log → 1 line), error lookup table, bisection workflow |
| **Write** | [`latex-project`](skills/latex-project/SKILL.md) | Asks venue, layout, length and review mode, then scaffolds a full compiling paper (abstract, keywords, all sections, tables, TikZ figures, references, one or two columns); `texmap.py` project map so agents read only what they need; `texstats.py` word and element counts |
| | [`latex-math`](skills/latex-math/SKILL.md) | Code → equations via a symbol map, with shape/index checks against the implementation and notation audits |
| | [`latex-tikz`](skills/latex-tikz/SKILL.md) | Reads your code and **suggests figures to pick from**; 12 tested patterns, shared styles, offline search of **1,229 official TikZ manual examples**, render-and-look loop |
| | [`latex-algorithms`](skills/latex-algorithms/SKILL.md) | Functions → `algorithmicx` pseudocode, or `minted`/`listings` pulled from source files |
| | [`latex-tables-figures`](skills/latex-tables-figures/SKILL.md) | booktabs/siunitx tables, matplotlib/pgfplots figures sized to the column |
| | [`latex-beamer`](skills/latex-beamer/SKILL.md) | Paper → timed talk with claim-style titles and reused figures and notation |
| | [`latex-poster`](skills/latex-poster/SKILL.md) | Paper → A0/venue-size tikzposter (portrait, landscape, #BetterPoster) reusing the paper's figures, notation and `\res{}` numbers |
| | [`latex-documents`](skills/latex-documents/SKILL.md) | 22 tested templates beyond the paper: 5 ATS-safe resumes, academic CV, letters, invoice, homework, lab report, lecture notes, exam + answer key, cheat sheets, book, thesis, fillable forms; `mail_merge.py` for CSV/JSON batches |
| | [`latex-convert`](skills/latex-convert/SKILL.md) | Markdown/Word/HTML ↔ LaTeX (Pandoc), PDF/scan/handwriting → LaTeX with checked page batches, Mermaid/Graphviz/PlantUML, latexdiff against a git tag |
| **Review** | [`latex-research-check`](skills/latex-research-check/SKILL.md) | Closest prior work across OpenAlex/arXiv/Semantic Scholar, ranked by similarity to *your* abstract |
| | [`latex-plagiarism-check`](skills/latex-plagiarism-check/SKILL.md) | Sentence-level overlap with sources, with cited/quoted status (honest about what it can't do) |
| | [`latex-review`](skills/latex-review/SKILL.md) | Venue-style mock review, 3-reviewer panel + meta-review, anonymity checklist, rebuttal prep |
| **Ship** | [`latex-arxiv`](skills/latex-arxiv/SKILL.md) | Only the files the document uses, comments stripped, arXiv's 2025 bibliography rules (`.bbl` format 3.3), test-compiled |
| | [`latex-pdf`](skills/latex-pdf/SKILL.md) | `pdftool.py`: previews, merge, page extraction, compression, encryption, watermarks, submission checks (embedded fonts, page size), fillable and flat form filling |

## Install

**Claude Code plugin (skills + hooks), recommended.** One command in your terminal:

```bash
claude plugin install agentex --marketplace Metahemeralism/AgenTeX
```

Or with the animated installer (it runs the same command):

```bash
curl -fsSL https://raw.githubusercontent.com/Metahemeralism/AgenTeX/main/install.sh | bash
```

Or from inside Claude Code:

```text
/plugin marketplace add Metahemeralism/AgenTeX
/plugin install agentex
```

Restart Claude Code afterwards. To update: `/plugin marketplace update agentex`.

**Skills only** (no hooks): `cp -r AgenTeX/skills/* ~/.claude/skills/`. To get the guarantees without the plugin, copy the `hooks` block from [`hooks/hooks.json`](hooks/hooks.json) into your `settings.json`, replacing `${CLAUDE_PLUGIN_ROOT}` with your clone's path.

**Claude apps / other agents:** each skill is a folder with a `SKILL.md` in the open Agent Skills format. Zip one and upload it under *Settings → Capabilities → Skills*, or point any agent at it.

**Requirements:** Python 3.8+ (all scripts are standard library only), and TeX Live / MacTeX or [`tectonic`](https://tectonic-typesetting.github.io) for compiling. Optional: poppler (`pdftoppm`, `pdftotext`) for previews and PDF sources, `S2_API_KEY` (free) for reliable preprint→published detection, and for the document tools: Pandoc, latexdiff, qpdf, Ghostscript, pdftk, and Graphviz/PlantUML/Mermaid CLIs. Each script says what's missing and falls back where it can.

| Setting | Effect |
|---|---|
| `AGENTEX_CITE_GUARD=0` | turn off the cite guard |
| `AGENTEX_COMPILE_HOOK=0` | turn off the compile loop |
| `S2_API_KEY=…` | Semantic Scholar key (anonymous use is rate-limited) |
| `AGENTEX_MAILTO=you@uni.edu` | joins Crossref's polite pool |

Caches and state live in `.agentex/` in your project, which ignores itself in git.

**The AgenTeX band.** A small band above the prompt shows what AgenTeX is doing while its checks run (verifying citations, typesetting, rendering a figure). TeX's lowered E bobs as it works:

```
AgenT X  ⠹ verifying citations  4s
     E
```

It also plays a one-time welcome after install. Turn it off under `/config` → *Animations*. The band uses Claude Code's hooks-module API, which is marked early access (it may change between releases). It is purely cosmetic: the skills, cite guard and compile loop do not depend on it.

## Use it

```text
> Check every citation in paper/ and show me what's wrong.
> I reran the experiments. What in the paper is now stale?
> Make results/main.csv into a table with the best numbers in bold.
> Suggest diagrams for this repo.          (reads the code, offers high-level and component figures to pick from)
> Draw the model in src/model.py as a TikZ figure with tensor shapes.
> Has anyone done this before? Find the closest work to my abstract.
> Review my paper as a NeurIPS reviewer.
> Package paper/ for arXiv.
> Turn the paper into an A0 portrait poster for NeurIPS.
> Make an ATS-friendly one-page resume from cv-notes.md.
> Convert my handwritten notes in notes.pdf to LaTeX.
> Write an exam with an answer key, then fill in this PDF form with my details.
```

### Scripts you can run yourself (or in CI)

| Script | Does |
|---|---|
| `latex-references/scripts/cite_verify.py paper/ [--suggest]` | Verify cited entries; exit 1 on fabricated, mismatched or duplicate entries |
| `latex-results-sync/scripts/results.py build\|audit\|table\|stale\|make` | Registry, stale-number audit, tables, provenance |
| `latex-references/scripts/check_refs.py paper/` | Undefined/duplicate labels, missing/uncited bib entries |
| `latex-debug/scripts/texlog.py main.log` | Log digest |
| `latex-debug/scripts/build.py main.tex --preview previews` | Build with the right engine; digest + PNG previews (`--pdfa`, `--clean`) |
| `latex-documents/scripts/mail_merge.py letter.tex people.csv --check` | One `.tex` per record; checks every record before writing |
| `latex-pdf/scripts/pdftool.py info\|preview\|merge\|pages\|compress\|encrypt\|fields\|fill\|overlay\|watermark` | PDF chores with whatever is installed, LaTeX as fallback |
| `latex-convert/scripts/check_fragments.py tmp/batch_*.tex` | Check converted page batches before assembling |
| `latex-project/scripts/texmap.py paper/` | Compact project map |
| `latex-project/scripts/texstats.py main.tex` | Word count (body, abstract) and section/figure/table/equation/citation counts |
| `latex-tikz/scripts/diagram_ideas.py .` | Diagram ideas from your code (pipelines, architectures, loops, models), each with its pattern and `file:line` |
| `latex-tikz/scripts/tikzref.py brace decoration` | Offline TikZ manual search |
| `latex-tikz/scripts/tikzcheck.sh fig.tex` | Compile a figure; errors only + small PNG preview |
| `latex-research-check/scripts/related.py --from-tex main.tex` | Closest prior work |
| `latex-plagiarism-check/scripts/overlap.py paper/ sources/` | Overlap screening |
| `latex-arxiv/scripts/arxiv_pack.py main.tex --compile` | arXiv package, test-compiled |

## Built to be token-efficient

Lessons from auditing the [ponytail](https://github.com/DietrichGebert/ponytail) and [agent-skills](https://github.com/addyosmani/agent-skills) plugins, applied here:

| Technique | In AgenTeX | Effect (measured on this repo) |
|---|---|---|
| Short always-loaded descriptions | 257 characters per skill on average (≤ 300, enforced by `tests/test_plugin.py`) | 18 skills cost ~4.6k characters until one is used |
| Lean bodies, no generic manuals | `SKILL.md` averages 71 lines; `reference/` files only for what the model lacks (conversion profiles, cheat-sheet budgets) | 760 reference lines in total, not 22,000 lines of LaTeX textbook |
| Deterministic scripts instead of reading | `texlog.py`, `cite_verify.py`, `results.py audit` | a 1,150-line compile log → 1 line |
| Compact project map | `texmap.py` | template project mapped in 663 characters |
| Local reference cache | `tikzref.py` over extracted manual examples | 248 characters returned vs a 624 KB manual page |
| Result caches | `.agentex/cite-cache.json` | re-verifying a bibliography goes from ~20 s to near-instant |
| Write styles once; copy and edit | `agentex-tikz.sty`, patterns, templates | output tokens spent only on what differs |
| Cheap visual checks | 100 dpi PNG previews | a few hundred image tokens per look |

## Honest limits

- **Citation checks** depend on public APIs. dblp currently puts scripted clients behind a bot check (AgenTeX skips it automatically), and Semantic Scholar rate-limits anonymous use. *not-found* means "no database knows it", so check by hand before calling it fabricated. Books, theses and software are reported as *unverifiable*, not *not-found*.
- **The results audit** reads LaTeX structure, not a regex over raw text, but it is still heuristic. It refuses to guess when a number matches more than 3 results.
- **Overlap screening** is not iThenticate: it only sees sources it can read, and AgenTeX offers no "AI-text detection", because such detectors are unreliable.
- **The compile loop** needs `latexmk` or `tectonic` and adds a build at the end of turns that edited LaTeX. Turn it off with `AGENTEX_COMPILE_HOOK=0`.
- **PDF fallbacks:** without qpdf or poppler, `pdftool.py` rebuilds PDFs through LaTeX (`pdfpages`), which drops links, bookmarks and form fields. Filling fillable forms needs pdftk.
- **Word counts** from `texstats.py` are approximate (prose only, no macro expansion); use `texcount` when a venue enforces a limit.

## Roadmap

From a ranked study of LaTeX bottlenecks for people who code:

- [ ] `/venue-convert` and `/camera-ready`: class/bibliography-style swaps, page-limit report, anonymous ↔ final mode
- [ ] Figure styling from `\columnwidth`: one matplotlib style file, detection of font-distorting `\includegraphics` rescales
- [ ] Notation-guardian subagent: a symbol table across all files, catching symbols with two meanings and drifting macros and acronyms
- [ ] `paper-ci`: pinned TeX build + GitHub Actions running cite/results audits and attaching a latexdiff (the latexdiff step is documented in `latex-convert`)
- [ ] `/rebuttal`: response letter mapped to the actual latexdiff/git changes
- [ ] Accessibility: tagged PDF, alt text drafted from the code and data behind each figure, veraPDF checks (PDF/A copies already come from `build.py --pdfa`)

## Repository layout

```
.claude-plugin/          plugin.json + marketplace.json
hooks/                   hooks.json, cite_guard.py, compile_loop.py, ui.tsx + frames.ts (the band) and tests
types/                   state contract for the band (TypeScript)
install.sh               animated installer
tests/                   plugin hygiene: frontmatter, lean bodies, dead paths, counts in sync
skills/
  latex-references/      cite_verify.py, check_refs.py
  latex-results-sync/    results.py
  latex-consistency/     latex-debug/ (build.py, texlog.py)   latex-project/ (templates, texmap.py, texstats.py)
  latex-math/            latex-tikz/ (assets, tikzref.py, tikzcheck.sh, manual index)
  latex-algorithms/      latex-tables-figures/       latex-beamer/ (talk template)
  latex-research-check/  latex-plagiarism-check/     latex-review/ (venue forms)
  latex-arxiv/           (arxiv_pack.py)          latex-pdf/ (pdftool.py)
  latex-documents/       (22 templates, mail_merge.py)   latex-poster/ (2 templates)
  latex-convert/         (check_fragments.py, conversion profiles)
docs/gallery/            rendered pattern previews
docs/logo/               wordmark source (.tex) + PDF/SVG/PNG, card and transparent variants
```

## Contributing

Issues and PRs are welcome, especially roadmap items, venue review forms, and error→fix pairs for `latex-debug`.

- One skill = one folder with a `SKILL.md`. Its `description` decides when it triggers, so say *when to use it*, in under 300 characters. Add a `reference/` file only for knowledge the model lacks or gets wrong, and link it from `SKILL.md`.
- Prefer a deterministic script to instructions wherever a check can be computed. Scripts are standard library only, each with tests:
  ```bash
  for d in hooks skills/*/scripts tests; do python3 -m unittest discover -s "$d" -q || exit 1; done
  claude plugin validate . && claude plugin test .     # the band's module, in Claude Code's own test kit
  ```
- New TikZ patterns must compile standalone with `agentex-tikz.sty`.
- Try your changes without installing: `claude --plugin-dir path/to/AgenTeX` loads the plugin straight from disk for that session.

## License

[MIT](LICENSE). Templates, conversion guides and `chktexrc` adapted from [latex-document-skill](https://github.com/ndpvt-web/latex-document-skill) (MIT) are marked by a `NOTICE.md` in each skill that carries them. The exception is `skills/latex-tikz/reference/tikz-manual.jsonl`: it contains examples extracted from the [PGF/TikZ manual](https://tikz.dev) (© Till Tantau and the PGF/TikZ team) and is distributed under LPPL 1.3c. See [its notice](skills/latex-tikz/reference/NOTICE.md).
