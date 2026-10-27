---
name: latex-submit
description: "Pre-submission gate: will this paper be desk-rejected? Checks the venue's page limit, style-file tampering, anonymity, required checklists, LLM-use disclosure, fonts, citations and stale numbers, plus camera-ready rules (ACM TAPS, IEEE). Use before submitting or uploading a camera-ready."
---

# Submission Gate

Desk rejections are mechanical: a page over the limit, a tweaked style file, a name in the PDF metadata, a missing checklist, an undisclosed LLM, a fabricated reference. ICLR 2026 desk-rejected papers for hallucinated references and for undisclosed LLM use. One deterministic command catches these before the deadline.

## Workflow

1. **Pick the venue file.** `python3 <skill>/scripts/preflight.py --venue list` shows the rules files in `<skill>/venues/` and the date each was checked. **Rules change every year**: if `checked` is older than the current call for papers, or the venue is missing, open the official call and update or add a file (below) before trusting a PASS. The script warns when rules are older than 180 days.
2. **Run the gate:**
   ```bash
   python3 <skill>/scripts/preflight.py paper/main.tex --venue neurips-2026                       # submission
   python3 <skill>/scripts/preflight.py paper/main.tex --venue acm-sigconf --mode camera-ready
   python3 <skill>/scripts/preflight.py paper/main.tex --venue arr-2026 --page-limit 4             # short paper / other track
   ```
   It uses `main.pdf` (or `--pdf`), and builds with `<skill>/../latex-debug/scripts/build.py` only when no PDF exists. Citations come from the `latex-references` cache; `--verify-citations` re-runs `<skill>/../latex-references/scripts/cite_verify.py` first (network). Output is grouped FORMAT / ANONYMITY / POLICY / INTEGRITY, each line PASS/WARN/FAIL with `file:line` and the fix. Exit 1 on any FAIL; the result also goes to `.agentex/status/preflight.json`.
3. **Fix, then re-run until there is no FAIL.** Fix FAILs in order; never silence one by deleting content or editing the venue file to match the paper. WARNs are heuristics (a GitHub link may be a baseline's, "our previous work" may be fine): read each and tell the user what you decided.
4. Report the remaining WARNs and the venue file's `notes` and `unverified` entries to the user. Some rules live in submission forms the script cannot see (ARR Responsible NLP Checklist, OpenReview profiles, reciprocal reviewing).

## What it checks

| Check | How (deterministic) |
|---|---|
| Main-body pages | `pdftotext` per page; body ends at the first References heading, or at a section the venue does not count (Acknowledgments, Impact Statement, Limitations...); text above the heading on that page counts as a page |
| Style file | sha256 of the venue `.sty` in the project vs the official file; FAIL if it differs or another year's file is loaded |
| Class mode | submission must be anonymous, camera-ready must show authors (option names below) |
| Anonymity (double-blind submissions) | PDF Author metadata, acknowledgements visible in the PDF, `\thanks`, GitHub/personal links, "our previous work"-style phrases |
| Required sections | NeurIPS Paper Checklist, ICML Impact Statement, ARR Limitations; ACM rights commands in camera-ready |
| LLM-use disclosure | when the venue requires it: a section heading or an acknowledgement naming the AI tool. FAIL if missing and the activity log shows agent edits |
| PDF | fonts embedded (FAIL), Type 3 fonts (WARN); IEEE: PDF 1.4-1.7, no links/bookmarks |
| Integrity | cited keys `not-found`/`bad-doi`/`missing`/`retracted` in the cite cache (FAIL), unverified or changed entries (WARN); undefined/duplicate labels; `??` in the PDF; `\guide`, `\filler`, `\todo`, TODO/FIXME, `placeholder-*`, `[AUTHORS:` gaps; missing figures/inputs (exact case); stale or undefined `\res` numbers via `<skill>/../latex-results-sync/scripts/results.py` audit |
| ACM camera-ready | `\Description` in every figure, packages on the TAPS accepted list (data in `acm-sigconf.json`), no `manuscript` option |

Comments and `verbatim` blocks are ignored, so template instructions do not trigger findings.

## Anonymous ↔ camera-ready switches (from the official 2026 templates)

| Venue | Submission | Camera-ready |
|---|---|---|
| NeurIPS 2026 | `\usepackage{neurips_2026}` | `\usepackage[main, final]{neurips_2026}` (track option + `final`; `preprint` for arXiv). Put acknowledgements in the `ack` environment: it hides them in the submission |
| ICLR 2026 | `\iclrfinalcopy` commented out | `\iclrfinalcopy` |
| ICML 2026 | `\usepackage{icml2026}` | `\usepackage[accepted]{icml2026}` (`preprint` for arXiv) |
| ACL / ARR | `\usepackage[review]{acl}` | `\usepackage[final]{acl}` (`preprint` for arXiv) |
| CVPR 2026 | `\usepackage[review]{cvpr}` | `\usepackage{cvpr}` (`pagenumbers` for arXiv) |
| ACM (acmart) | `\documentclass[manuscript,anonymous,review]{acmart}` + `\setcopyright{none}` (or what your call names) | drop `manuscript`/`anonymous`/`review`, set the format (e.g. `sigconf`), paste the rights-form block |
| IEEE | `\documentclass[conference]{IEEEtran}`; anonymity varies by conference | same; run the PDF through IEEE PDF eXpress if the conference uses it |

Never invent ACM rights values (`\setcopyright`, `\acmDOI`, `\acmConference`, ISBN): they come from the rights-form e-mail.

## LLM-use disclosure

`hooks/activity_log.py` (PostToolUse) appends every agent edit to a `.tex`/`.bib` file to `.agentex/activity.jsonl` (time, file, tool, lines added/removed, section). Disable with `AGENTEX_ACTIVITY_LOG=0`.

```bash
python3 <skill>/scripts/disclosure.py paper/
```
drafts a paragraph from that log, `git log` (commits with a Co-Authored-By: Claude trailer) and AgenTeX state (citations verified, numbers generated from result files, compile loop). It is a **draft**: it contains `[AUTHORS: ...]` gaps (model name, whether the agent shaped ideas or experiments) that preflight reports as placeholders until the authors fill them. Show it to the user; never paste it into the paper without their approval. Where it goes: ICLR, a separate LLM-usage section (appendix is fine); IEEE and ACM, the acknowledgements; ARR, the Responsible NLP Checklist plus the acknowledgements; NeurIPS, only when an LLM is a non-standard part of the method (experimental setup). Edits made before the hook was installed are not in the log, so ask the user about earlier use.

## Adding or updating a venue file

Copy the closest file in `<skill>/venues/` to `<id>.json` (or keep it in the user's project and pass its path to `--venue`). Fill only what the official call or template states, and list the URLs:

| Key | Meaning |
|---|---|
| `id`, `name`, `checked` (YYYY-MM-DD), `sources` (https URLs), `verified` | identity and provenance; `verified: false` when the rules could not be confirmed |
| `double_blind` | run the anonymity checks in submission mode |
| `pages` | `submission`, `camera-ready` (null = no limit), `uncounted` (headings that end the counted body) |
| `style` | `file`, `sha256` of the official file (`shasum -a 256`), `url`, `why` |
| `named_if`, `switch` | regex that matches when the class shows author names; the submission / camera-ready line to suggest |
| `no_acks_in_submission` | acknowledgements in a review PDF are a FAIL (else WARN) |
| `required`, `forbidden` | `[{what, pattern, modes, why, fix}]` regexes over the comment-free source |
| `llm_disclosure` | `required`, `modes` (where it must be in the paper), `where`, `why` |
| `figure_description`, `taps`, `pdf_version`, `no_links` | ACM and IEEE camera-ready rules |
| `notes`, `unverified` | shown to the user; anything not confirmed on an official page goes in `unverified` |

`test_preflight.py` validates every venue file, so run the tests after editing one.

Related skills: `latex-references` (verify citations), `latex-results-sync` (stale numbers), `latex-review` (referee-style review), `latex-arxiv` (packaging), `latex-pdf` (fonts, metadata).
