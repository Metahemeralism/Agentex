<div align="center">

<img src="docs/logo/agentex-logo.svg" alt="AgenTeX" width="440">

**Keep your LaTeX paper honest to the code behind it.**

Submission gate · verified citations · numbers that can't go stale · paper ↔ code checks · a build that fixes itself

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Skills](https://img.shields.io/badge/skills-19-informational)
![Hooks](https://img.shields.io/badge/hooks-3-informational)
![Dependencies](https://img.shields.io/badge/scripts-stdlib%20only-success)

</div>

---

AgenTeX is a Claude Code plugin for researchers and students whose results live in code and whose papers live in LaTeX. It works where editor-based assistants can't: next to your code, data and git history, with a shell. Deterministic scripts make the final calls, so the paper can't drift from the code, can't cite work that doesn't exist or was retracted, and can't get desk-rejected for a problem that could have been fixed.

The same checks also work for posters, theses, CVs and exams. Prose polishing and in-editor drafting are deliberately out of scope, because editor tools such as Overleaf's AI features and OpenAI Prism already cover them.

## Why

- **Fabricated references survive peer review.** In 2025, "roughly one in twenty NeurIPS and USENIX Security papers contains at least two likely hallucinated" references (*Phantom References*, [arXiv:2607.00738](https://arxiv.org/abs/2607.00738)). 100 fabricated citations reached 53 accepted NeurIPS 2025 papers despite "review by 3-5 expert researchers per paper" ([arXiv:2602.05930](https://arxiv.org/abs/2602.05930)).
- **Venues now desk-reject for them.** ICLR 2026 treats hallucinated references as a Code of Ethics violation, and "papers that make extensive usage of LLMs and do not disclose this usage will be desk rejected" ([ICLR blog, 2025-11-19](https://blog.iclr.cc/2025/11/19/iclr-2026-response-to-llm-generated-papers-and-reviews/)).
- **Retractions can be checked by a script.** Crossref acquired the Retraction Watch database in 2023, made it publicly available through its REST API, and Retraction Watch updates it every working day ([Crossref docs](https://crossref.org/documentation/retrieve-metadata/retraction-watch/)).
- **Papers and code disagree, and LLMs miss it.** On real paper–code discrepancies, the best of 22 models "detect only 46.7%". They struggle most with details the paper omits and with long inputs (*SciCoQA*, [arXiv:2601.12910](https://arxiv.org/abs/2601.12910), ACL 2026). So AgenTeX finds omissions with a script and has the model judge one claim at a time, with only a few lines of code in view.
- **Numbers drift.** A rerun changes 87.3 to 86.9, but the abstract still says 87.3, and nobody remembers which script made `fig3.pdf`.
- **Compiling isn't correctness.** The vTikZ benchmark finds that current LLMs "struggle to reliably modify code in alignment with visual intent" ([arXiv:2505.04670](https://arxiv.org/abs/2505.04670)). Agents need to check the log *and* look at the result.

*(Each paper was checked with AgenTeX's own `cite_verify.py`, and each quote against its abstract or the cited page.)*

**How it works.** Every check that can be computed is a standard-library Python script. It prints a short digest with `file:line` locations, returns a meaningful exit code and writes `.agentex/status/<tool>.json`. The LLM organises the work and explains the results. Corrections to references, numbers, claims and alt text arrive as suggestions or diffs, and nothing is applied silently.

## Use it: workflows

Type the prompts in Claude Code. The **Underneath** notes say which skill and script do the work. Every script path is relative to `skills/`.

### Starting a paper from a repo

```text
> Start a NeurIPS paper for this repo, double-blind.
> Suggest diagrams for this repo.
> Draw the model in src/model.py as a TikZ figure with tensor shapes.
> Write the loss in src/train.py as an equation and add it to the notation table.
> Make results/main.csv into a table with the best numbers in bold.
```

**Underneath:**
- `latex-project` asks for the venue, layout, length and review mode, then copies in a skeleton that compiles as-is.
- `latex-tikz/scripts/diagram_ideas.py` reads the code and offers high-level and component figures with `file:line` evidence. The agent starts from one of 12 tested patterns and looks at a rendered preview before handing it over.
- `latex-math` builds a symbol map and checks shapes and indices against the implementation.
- `latex-results-sync/scripts/results.py table` writes the booktabs table, and `latex-tables-figures/scripts/mplstyle.py` writes a matplotlib style sized to the paper's measured `\columnwidth`.

### While you write (automatic)

Three hooks run without being asked:

| Hook | When | What it does | Off switch |
|---|---|---|---|
| **Cite guard** (`hooks/cite_guard.py`) | before an edit to a `.tex` file | Blocks the edit if it adds a `\cite` whose entry is unverified, fabricated, retracted or changed since it was verified. The block message gives the verify command. | `AGENTEX_CITE_GUARD=0` |
| **Compile loop** (`hooks/compile_loop.py`) | at the end of a turn that edited LaTeX | Builds every main document. On errors or *new* undefined references or citations, it hands the agent a short digest to fix before you see the broken PDF. It gives up after 3 blocks in a row. | `AGENTEX_COMPILE_HOOK=0` |
| **Activity log** (`hooks/activity_log.py`) | after an edit to a `.tex` or `.bib` file | Appends the file, section and lines changed to `.agentex/activity.jsonl`, which the LLM-use disclosure draft is built from. It never blocks. | `AGENTEX_ACTIVITY_LOG=0` |

### Citing

```text
> Cite the Adam paper in the optimisation paragraph.
> Check every citation in paper/ and show me what's wrong.
> Do the papers I cite actually say what my sentences claim?
```

**Underneath:**
- `latex-references/scripts/cite_verify.py` resolves every cited entry against Crossref, arXiv, dblp, Semantic Scholar and OpenAlex. It labels each one *verified*, *published* (the preprint has a published version), *mismatch* (title, authors or year wrong, so-called "Frankenstein" metadata), *bad-doi*, *not-found* (treated as fabricated until the author shows the source), *retracted* or *unverifiable*. Corrections and expressions of concern are printed as `NOTICE` lines. The retraction check was tested live on a retracted 1998 *Lancet* paper.
- `--suggest` writes corrected entries to `.agentex/suggested.bib`. Your `.bib` is never edited.
- `cite_claims.py extract|next|record|report` checks each citing sentence against the cited paper's abstract, one sentence at a time. It flags; it never rewrites.

### After you rerun experiments

```text
> I reran the experiments. What in the paper is now stale?
> Rebuild the figures whose scripts or data changed.
> Does the paper mention every setting the code actually uses?
```

**Underneath:**
- `latex-results-sync/scripts/results.py build` turns results JSON into `\res{}` macros.
- `results.py audit` finds three kinds of number: **STALE** (it equals a *previous* value of a result), **HARD-CODED** (it equals a current value) and **UNDEFINED** (`\res{key}` for a key that doesn't exist).
- `results.py stale` and `results.py make` rerun the producers of outdated figures, recording input hashes, the commit, the runtime and the hardware.
- `latex-consistency/scripts/settings_audit.py src/ paper/` reads configs, argparse defaults, dataclasses and optimizer calls without running the code. It reports **MISMATCH** (the paper gives another value), **UNDISCLOSED** (the paper never mentions the setting) and **NO-VALUE** (the paper names it but gives no value).
- `claims.py diff` exits 1 if a frozen claim's text changed.

### Before you submit

```text
/agentex:preflight neurips-2026
> Will this get desk-rejected at ICLR?
> Check every claim in the paper against the code.
> Do my figures print at a readable size?
> Review my paper as a NeurIPS reviewer, then fix what you can.
> Has anyone done this before? Check for text overlap with the papers I cite.
```

**Underneath:**
- `latex-submit/scripts/preflight.py main.tex --venue <id>` is one deterministic gate, grouped FORMAT / ANONYMITY / POLICY / INTEGRITY. It checks:
  - main-body pages up to the references;
  - the style file's sha256 against the official one;
  - anonymity: PDF metadata, `\author`, acknowledgements, revealing links and phrases;
  - required checklists and sections, and the LLM-use disclosure;
  - embedded and Type 3 fonts;
  - unverified or retracted citations, stale numbers and leftover placeholders.

  Rule files cover `neurips-2026`, `iclr-2026`, `icml-2026`, `arr-2026`, `cvpr-2026`, `ieee-conference`, `acm-sigconf`, `arxiv` and `default`. Each lists its sources and the date it was checked. It exits 1 on any FAIL.
- `latex-submit/scripts/disclosure.py paper/` drafts an LLM-use disclosure from the activity log and `git log`. The draft has `[AUTHORS: ...]` gaps for the authors to fill.
- `latex-consistency/scripts/claims.py extract|next|record|report|freeze` builds a claim ledger. Each claim is judged against at most 3 candidate code locations, and a verdict that cites missing evidence is refused.
- `latex-tables-figures/scripts/figcheck.py main.tex` finds the printed size of the text inside each figure, Type 3 or unembedded fonts, rasters under 300 dpi and missing alt text. In a 10pt two-column article, matplotlib's default figure placed at `\columnwidth` prints its 10pt tick labels at 5.0pt. The same plot made with the `mplstyle.py` style prints at 9.2pt (measured with tectonic).
- `latex-review` writes a venue-style review or a 3-reviewer panel. Its self-review loop keeps an issue ledger (`issues.py`), runs a guard after each edit (build, refs, results audit, frozen claims) and stops by a computed rule, at most 3 rounds. The design follows *PaperJury* ([arXiv:2606.16322](https://arxiv.org/abs/2606.16322)), which argues that stopping and safety logic belong in deterministic orchestration rather than in a model's judgement.
- `latex-research-check/scripts/related.py` finds the closest prior work, and `latex-plagiarism-check/scripts/overlap.py` screens for overlapping text.

### Reviews came back

```text
> The reviews are in reviews/. Triage them and fix what's fixable.
> Draft the rebuttal against the v1-submitted tag.
```

**Underneath:**
- `latex-review/scripts/issues.py import-reviews reviews/R2.txt` turns each weakness or question into an issue.
- `issues.py verdict <id> invalid|fixable|author` sorts them. The agent edits only `fixable` items, then `issues.py guard` re-runs the build, refs, results audit and frozen claims.
- `rebuttal.py draft --since v1-submitted --limit-chars 5000` writes one block per point: the quote, an empty `Response:`, and the changes since the tag (diff hunks with `file:line`, fix commits and changed `\res{}` values). It never overwrites a file you have started.
- The authors write the arguments, and `latex-convert` makes the latexdiff PDF.

### Reproducibility and artifact evaluation

```text
> Add a reproduction table for every figure and table to the README.
> Does the loss figure still reproduce from a clean checkout?
> Draft the evidence for the reproducibility checklist.
```

**Underneath:**
- `latex-results-sync/scripts/repro.py table --paper paper/` gives one row per figure or table: label, caption, command, inputs, commit, runtime and hardware, and FRESH / STALE / MISSING / NO-SOURCE. `--write README.md` shows a diff of the block between `agentex:repro` markers, and `--apply` writes it.
- `repro.py smoke` reruns the producers in a throwaway `git worktree` of HEAD and reports REPRODUCED, DIFFERS or FAILED.
- `repro.py checklist` gives `file:line` evidence, or "not found", for each compute, code, seed and data question. It never answers a question for you.

### Camera-ready and arXiv

```text
> Check the camera-ready for ACM: rights block, figure descriptions, allowed packages.
> Package paper/ for arXiv and check how the HTML version will look.
> Draft alt text for every figure from the code that made it.
> Build a tagged, accessible PDF.
```

**Underneath:**
- `preflight.py --mode camera-ready` checks that authors are shown, ACM `\Description` and the packages on ACM's TAPS list, and IEEE's PDF version and no-links rules.
- `latex-arxiv/scripts/arxiv_pack.py main.tex --compile` ships only the files the document uses, with comments stripped, and test-compiles the package.
- `html_check.py main.tex` checks readiness for arXiv's HTML version against a snapshot of the 720 package and class bindings of arXiv's converter (latexml-oxide). It also flags missing alt text and visual-only markup.
- `latex-debug/scripts/build.py main.tex --tagged en` builds a PDF/UA-2 tagged PDF with LuaLaTeX, and `--pdfa` builds a PDF/A-2b copy.

### Beyond the paper: talks, posters, CVs, theses, exams

```text
> Turn the paper into a 15-minute talk.
> Turn the paper into an A0 portrait poster.
> Make an ATS-friendly one-page resume from cv-notes.md.
> Write an exam with an answer key.
> Convert my handwritten notes in notes.pdf to LaTeX.
> Make a PDF/A copy of my thesis, then fill in this PDF form with my details.
```

**Underneath:**
- `latex-beamer` and `latex-poster` reuse the paper's `macros.tex`, figures and `\res{}` numbers, so a rerun updates the talk and the poster too.
- `latex-documents` has 22 test-compiled templates (resumes, academic CV, letters, exams, cheat sheets, thesis, book and more) and `mail_merge.py` for batches from CSV or JSON.
- `latex-convert` converts Markdown, Word, PDFs and scans into LaTeX, and `latex-pdf/scripts/pdftool.py` finishes PDFs.
- The paper checks still apply here. Run `cite_verify.py` on CV publications and `results.py audit` on lab reports and posters, and use `texstats.py` for thesis word limits.

## Paper health in Claude Code

| | |
|---|---|
| `/agentex` | Opens the **Paper health** pane. Each check gets one row, worst first, with its age, and results older than your last LaTeX edit are marked stale. Press Enter on a row to see its `file:line` items. `c` runs the cheap checks, `h` asks what to fix next, and checks that have never run are listed. |
| `/agentex:check` | Runs the quick offline checks (numbers, stale figures, refs, settings, claims, figures, open issues) and changes nothing. |
| `/agentex:health` | Summarises the latest results and names the one thing to fix or run next. It re-runs nothing. |
| `/agentex:preflight <venue>` | Runs the submission gate (`list` shows the venues). |

While a check fails, a status line says so, and a toast appears when a check starts failing (at most one a minute). A small band above the prompt shows what AgenTeX is doing while its checks run. TeX's lowered E bobs as it works:

```
AgenT X  ⠹ verifying citations  4s
     E
```

The *Animations* option (`/config`) turns off the band, the status line and the toasts. The pane still opens on request. The UI uses Claude Code's hooks-module API, which is early access and may change between releases. It is cosmetic: the skills, hooks and scripts don't depend on it. In sessions with no pane, such as `claude -p`, `/agentex` prints the same summary as text.

## Skills

| | Skill | What it does |
|---|---|---|
| **Verify** | [`latex-submit`](skills/latex-submit/SKILL.md) | Desk-rejection gate per venue: pages, style-file hash, anonymity, checklists, LLM-use disclosure, fonts, citations, stale numbers, placeholders. Camera-ready rules for ACM TAPS and IEEE. `disclosure.py` drafts the LLM-use statement |
| | [`latex-references`](skills/latex-references/SKILL.md) | Citations checked against five databases (fabricated, Frankenstein, retracted), cited-claim checks against abstracts, BibTeX from DOIs, natbib/biblatex setup, label linter |
| | [`latex-results-sync`](skills/latex-results-sync/SKILL.md) | Results JSON → `\res{}` macros, audit for stale and hand-typed numbers, generated tables, figure provenance and rebuilds, a per-figure reproduction table, clean-checkout smoke test, reproducibility-checklist evidence |
| | [`latex-consistency`](skills/latex-consistency/SKILL.md) | Paper ↔ code: settings the paper omits or misstates, a claim ledger judged one claim at a time and then frozen, equations vs. implementation, notation drift, overclaims, leakage red flags |
| | [`latex-debug`](skills/latex-debug/SKILL.md) | `build.py` picks pdfLaTeX, XeLaTeX or LuaLaTeX, flags missing packages before compiling, and makes previews, PDF/A copies and tagged PDFs. Log digest, error lookup table, bisection workflow |
| **Write** | [`latex-project`](skills/latex-project/SKILL.md) | Asks venue, layout, length and review mode, then scaffolds a full compiling paper. `texmap.py` gives a project map so agents read only what they need; `texstats.py` counts words and elements |
| | [`latex-math`](skills/latex-math/SKILL.md) | Code → equations via a symbol map, with shape and index checks against the implementation, plus notation audits |
| | [`latex-tikz`](skills/latex-tikz/SKILL.md) | Reads your code and suggests figures to pick from. 12 tested patterns, a shared style sheet, offline search of 1,229 TikZ manual examples, render-and-look loop |
| | [`latex-algorithms`](skills/latex-algorithms/SKILL.md) | Functions → `algorithmicx` pseudocode, or `minted`/`listings` pulled from source files |
| | [`latex-tables-figures`](skills/latex-tables-figures/SKILL.md) | booktabs/siunitx tables and matplotlib/pgfplots figures. `mplstyle.py` sizes plots to the column; `figcheck.py` checks printed text size, fonts, DPI and alt text |
| **Review** | [`latex-review`](skills/latex-review/SKILL.md) | Venue-style mock review, 3-reviewer panel with meta-review, a self-review fix loop with an issue ledger, guard and stopping rule, and a rebuttal skeleton mapped to the actual changes |
| | [`latex-research-check`](skills/latex-research-check/SKILL.md) | Closest prior work across OpenAlex, arXiv and Semantic Scholar, ranked by similarity to *your* abstract |
| | [`latex-plagiarism-check`](skills/latex-plagiarism-check/SKILL.md) | Sentence-level overlap with sources, with cited/quoted status, and honest about what it can't do |
| **Ship** | [`latex-arxiv`](skills/latex-arxiv/SKILL.md) | Only the files the document uses, comments stripped, arXiv's bibliography rules, test-compiled. `html_check.py` checks readiness for arXiv's HTML version and alt text |
| | [`latex-pdf`](skills/latex-pdf/SKILL.md) | `pdftool.py`: previews, merge, page extraction, compression, encryption, watermarks, submission checks, form filling. PDF/A and tagged PDFs via `build.py` |
| **Beyond the paper** | [`latex-beamer`](skills/latex-beamer/SKILL.md) | Paper → timed talk with claim-style titles and the paper's own figures and notation |
| | [`latex-poster`](skills/latex-poster/SKILL.md) | Paper → A0 or venue-size tikzposter (portrait, landscape, #BetterPoster) that reuses the paper's figures, notation and `\res{}` numbers |
| | [`latex-documents`](skills/latex-documents/SKILL.md) | 22 tested templates: 5 ATS-safe resumes, academic CV, letters, invoice, homework, lab report, lecture notes, exam + answer key, cheat sheets, book, thesis, fillable forms. `mail_merge.py` for CSV/JSON batches |
| | [`latex-convert`](skills/latex-convert/SKILL.md) | Markdown/Word/HTML ↔ LaTeX (Pandoc), PDF/scan/handwriting → LaTeX in checked page batches, Mermaid/Graphviz/PlantUML, latexdiff against a git tag |

### TikZ gallery

Tested patterns from `latex-tikz`, each about 20 lines on one shared style sheet. The agent copies the closest one, edits only what differs, then renders the result and *looks* at it.

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

## Install

**Claude Code plugin (skills, hooks, commands and UI), recommended.** One command in your terminal:

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

Restart Claude Code afterwards. To update, run `/plugin marketplace update agentex`.

**Skills only** (no hooks, commands or UI): `cp -r AgenTeX/skills/* ~/.claude/skills/`. To add the hooks without the plugin, copy the `hooks` block from [`hooks/hooks.json`](hooks/hooks.json) into your `settings.json` and replace `${CLAUDE_PLUGIN_ROOT}` with your clone's path. The UI only loads as part of the plugin.

**Claude apps and other agents:** each skill is a folder with a `SKILL.md` in the open [Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) format. Zip one and upload it under *Settings → Capabilities → Skills*, or point any agent at it.

**Requirements:**
- Python 3.8+. Every script uses the standard library only.
- TeX Live / MacTeX or [`tectonic`](https://tectonic-typesetting.github.io) for compiling.
- poppler (`pdftotext`, `pdffonts`, `pdfinfo`, `pdftoppm`) for page counts, font checks and previews.
- git for provenance, smoke tests and rebuttal diffs.

Optional: `S2_API_KEY` (free) for reliable preprint→published detection, and `latexml-oxide` for a local check of arXiv's HTML version. The document tools can also use Pandoc, latexdiff, qpdf, Ghostscript, pdftk and the Graphviz/PlantUML/Mermaid CLIs. Each script says what's missing and falls back where it can.

| Setting | Effect |
|---|---|
| `AGENTEX_CITE_GUARD=0` | turn off the cite guard |
| `AGENTEX_COMPILE_HOOK=0` | turn off the compile loop |
| `AGENTEX_ACTIVITY_LOG=0` | turn off the activity log (the disclosure draft then has no edit history) |
| `S2_API_KEY=…` | Semantic Scholar key (anonymous use is rate-limited) |
| `AGENTEX_MAILTO=you@uni.edu` | joins Crossref's polite pool |
| `/config` → *Animations* | band, status line and toasts on or off |

State lives in `.agentex/` in your project (some checks keep it next to the paper, e.g. `paper/.agentex/`; the health pane reads both), which ignores itself in git. It holds the citation cache, the build state, suggestions, the activity log, the claim and issue ledgers, and `status/*.json`.

## Scripts you can run yourself (or in CI)

Paths are relative to `skills/`. Exit codes are meaningful, so the scripts can gate a CI job.

| Script | Does |
|---|---|
| `latex-submit/scripts/preflight.py main.tex --venue neurips-2026 [--mode camera-ready]` | Submission gate; `--venue list` shows rule files and checked dates. Exits 1 on any FAIL |
| `latex-submit/scripts/disclosure.py paper/` | Draft LLM-use disclosure from the activity log and git history |
| `latex-references/scripts/cite_verify.py paper/ [--suggest]` | Verify cited entries. Exits 1 on fabricated, mismatched, retracted or duplicate entries |
| `latex-references/scripts/cite_claims.py extract\|next\|record\|report` | Does each cited abstract support its sentence? |
| `latex-references/scripts/check_refs.py paper/` | Undefined/duplicate labels, missing/uncited bib entries |
| `latex-results-sync/scripts/results.py build\|audit\|table\|stale\|make` | Registry, stale-number audit, tables, provenance |
| `latex-results-sync/scripts/repro.py table\|smoke\|checklist` | Reproduction table, clean-checkout rerun, checklist evidence |
| `latex-consistency/scripts/settings_audit.py src/ paper/` | Settings the paper omits or misstates. Exits 1 on MISMATCH or UNDISCLOSED |
| `latex-consistency/scripts/claims.py extract\|next\|record\|report\|freeze\|diff` | Claim ledger; `diff` exits 1 when a frozen claim changed |
| `latex-tables-figures/scripts/figcheck.py main.tex` | Figures as printed. Exits 1 on a missing figure or non-embedded fonts |
| `latex-tables-figures/scripts/mplstyle.py main.tex -o paper.mplstyle` | matplotlib style sized to the paper (`--text` for `figure*`) |
| `latex-review/scripts/issues.py add\|list\|verdict\|fix\|round\|import-reviews\|guard\|stop` | Issue ledger, guard, stopping rule (`stop` exits 0 when done) |
| `latex-review/scripts/rebuttal.py draft --since v1-submitted` | Rebuttal skeleton mapped to the changes since a tag |
| `latex-debug/scripts/build.py main.tex --preview previews` | Build with the right engine; digest + PNG previews (`--pdfa`, `--tagged [LANG]`, `--clean`) |
| `latex-debug/scripts/texlog.py main.log` | Log digest |
| `latex-arxiv/scripts/arxiv_pack.py main.tex --compile` | arXiv package, test-compiled |
| `latex-arxiv/scripts/html_check.py main.tex` | Readiness for arXiv's HTML version |
| `latex-project/scripts/texmap.py paper/` | Compact project map |
| `latex-project/scripts/texstats.py main.tex` | Word count and section/figure/table/equation/citation counts |
| `latex-tikz/scripts/diagram_ideas.py .` | Diagram ideas from your code, each with its pattern and `file:line` |
| `latex-tikz/scripts/tikzref.py brace decoration` | Offline TikZ manual search |
| `latex-tikz/scripts/tikzcheck.sh fig.tex` | Compile a figure; errors only + small PNG preview |
| `latex-research-check/scripts/related.py --from-tex main.tex` | Closest prior work |
| `latex-plagiarism-check/scripts/overlap.py paper/ sources/` | Overlap screening |
| `latex-documents/scripts/mail_merge.py letter.tex people.csv --check` | One `.tex` per record; checks every record before writing |
| `latex-pdf/scripts/pdftool.py info\|preview\|merge\|pages\|compress\|encrypt\|fields\|fill\|overlay\|watermark` | PDF chores with whatever is installed, LaTeX as fallback |
| `latex-convert/scripts/check_fragments.py tmp/batch_*.tex` | Check converted page batches before assembling |

## Cheap on tokens

The techniques come from auditing the [ponytail](https://github.com/DietrichGebert/ponytail) and [agent-skills](https://github.com/addyosmani/agent-skills) plugins.
- The 19 skill descriptions that are always loaded total about 5.1k characters. Each is at most 300 characters, which `tests/test_plugin.py` enforces. Skill bodies average 77 lines and load only when a skill is used.
- Scripts print digests, not logs, and caches such as `.agentex/cite-cache.json` make re-runs near-instant.
- Judgement calls get narrow context: one claim and at most 3 code locations, or one citing sentence and its abstract.
- The agent copies a pattern, template or style sheet and edits only what differs. `tikzref.py` searches the manual offline instead of fetching web pages, and visual checks use 100 dpi previews.

## Honest limits

- **Only tectonic was test-built.** The latexmk, pdfLaTeX and LuaLaTeX paths, and `build.py --tagged`, are unit-tested but were not test-built on the development machine. Tagged PDFs need LaTeX 2025-11-01 or newer, so validate them with veraPDF.
- **Hardware capture** (`nvidia-smi` in `results.py make`) was tested only with a mocked `nvidia-smi`.
- **Venue rules change every year.** Every rule file carries a `checked` date (all currently 2026-10-26) and its sources, and `preflight.py` warns after 180 days. Check the current call for papers before trusting a PASS. Some rules live in submission forms the script can't see (ARR's Responsible NLP Checklist, OpenReview profiles). The ACM rules were read through a fetch service, so that file lists them as `unverified`.
- **The claim, settings and cited-claim checks are heuristics that flag and never edit.**
  - `settings_audit.py` doesn't see values set at run time (CLI overrides, sweeps).
  - A claim verdict is the model's judgement, recorded with its evidence.
  - `cite_claims.py` only compares against abstracts, so *not-in-abstract* means "check the full text", not "wrong".
- **Citation checks** depend on public APIs. dblp currently puts scripted clients behind a bot check (AgenTeX skips it automatically), and Semantic Scholar rate-limits anonymous use. *not-found* means no database knows the entry, so check by hand before calling it fabricated. Retraction checks need a DOI registered with Crossref, so arXiv-only entries aren't checked for withdrawal.
- **The results audit** reads LaTeX structure rather than running a regex over raw text, but it is still heuristic. It refuses to guess when a number matches more than 3 results.
- **Reproduction:** `repro.py smoke` tests HEAD, not uncommitted edits. PDFs and PNGs often differ only by embedded timestamps. `make` and `smoke` run the manifest's commands in your shell, so only run manifests you wrote or reviewed.
- **The LLM-use disclosure** is a draft. The activity log only sees edits made after the plugin was installed.
- **Overlap screening** is not iThenticate: it only sees sources it can read. AgenTeX offers no "AI-text detection", because such detectors are unreliable.
- **The compile loop** needs `latexmk` or `tectonic` and adds a build at the end of turns that edited LaTeX.
- **PDF fallbacks:** without qpdf or poppler, `pdftool.py` rebuilds PDFs through LaTeX (`pdfpages`), which drops links, bookmarks and form fields. Filling fillable forms needs pdftk. Word counts from `texstats.py` are approximate; use `texcount` when a venue enforces a limit.

## Roadmap

- [ ] Venue conversion in one step: swap the class, bibliography style and anonymity mode between venues (`preflight.py` already names the right switch lines)
- [ ] Notation-guardian subagent: a symbol table across all files, catching symbols with two meanings and drifting macros and acronyms
- [ ] `paper-ci`: a pinned TeX build and GitHub Actions that run preflight, the citation and results audits and the repro smoke test, and attach a latexdiff. The scripts already exit non-zero and write `.agentex/status/*.json`
- [ ] Overleaf sync: run the checks on an Overleaf project through Overleaf's Git integration and return suggestions as a branch
- [ ] veraPDF validation of tagged and PDF/A builds inside `build.py`

## Repository layout

```
.claude-plugin/          plugin.json + marketplace.json
commands/                /agentex:check, /agentex:health, /agentex:preflight
hooks/                   hooks.json; cite_guard.py, compile_loop.py, activity_log.py;
                         ui.tsx + frames.ts + health.ts (band, health pane, status line, toasts) and tests
types/                   state contract for the UI (TypeScript)
install.sh               animated installer
tests/                   plugin hygiene: frontmatter, lean bodies, dead paths, counts in sync
skills/
  latex-submit/          preflight.py, disclosure.py, venues/*.json
  latex-references/      cite_verify.py, cite_claims.py, check_refs.py
  latex-results-sync/    results.py, repro.py
  latex-consistency/     settings_audit.py, claims.py
  latex-debug/           build.py, texlog.py, chktexrc
  latex-project/         paper template, texmap.py, texstats.py
  latex-math/            latex-algorithms/
  latex-tikz/            patterns + style sheet, diagram_ideas.py, tikzref.py, tikzcheck.sh, manual index
  latex-tables-figures/  figcheck.py, mplstyle.py
  latex-review/          issues.py, rebuttal.py, venue review forms
  latex-research-check/  related.py          latex-plagiarism-check/  overlap.py
  latex-arxiv/           arxiv_pack.py, html_check.py, LaTeXML binding snapshot
  latex-pdf/             pdftool.py
  latex-beamer/          talk template       latex-poster/            2 templates
  latex-documents/       22 templates, mail_merge.py
  latex-convert/         check_fragments.py, conversion profiles
docs/gallery/            rendered pattern previews
docs/logo/               wordmark source (.tex) + PDF/SVG/PNG, card and transparent variants
```

## Contributing

Issues and PRs are welcome, especially roadmap items, venue rule files, venue review forms, and error→fix pairs for `latex-debug`.

- One skill is one folder with a `SKILL.md`. Its `description` decides when the skill triggers, so say *when to use it* in under 300 characters. Add a `reference/` file only for knowledge the model lacks or gets wrong, and link it from `SKILL.md`.
- Prefer a deterministic script to written instructions wherever a check can be computed. Scripts use the standard library only, and each one has tests:
  ```bash
  for d in hooks skills/*/scripts tests; do python3 -m unittest discover -s "$d" -q || exit 1; done
  claude plugin validate . && claude plugin test .     # the UI module, in Claude Code's own test kit
  ```
- A venue rule file (`skills/latex-submit/venues/<id>.json`) states only what the official call or template says. It lists its source URLs and a `checked` date, and `test_preflight.py` validates it.
- New TikZ patterns must compile standalone with `agentex-tikz.sty`.
- To try your changes without installing, run `claude --plugin-dir path/to/AgenTeX`. It loads the plugin from disk for that session.

## License

[MIT](LICENSE). Templates, conversion guides and `chktexrc` adapted from [latex-document-skill](https://github.com/ndpvt-web/latex-document-skill) (MIT) are marked by a `NOTICE.md` in each skill that carries them. The exception is `skills/latex-tikz/reference/tikz-manual.jsonl`: it contains examples extracted from the [PGF/TikZ manual](https://tikz.dev) (© Till Tantau and the PGF/TikZ team) and is distributed under LPPL 1.3c. See [its notice](skills/latex-tikz/reference/NOTICE.md).
