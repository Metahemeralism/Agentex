---
name: latex-review
description: "Review a LaTeX paper as a NeurIPS/ICML/ICLR/ACL/CVPR/IEEE or journal referee would: scored review, reviewer panel, line-level writing feedback, anonymity checklist. Use before submission (a bounded self-review fix loop with an issue ledger) or after reviews arrive (rebuttal draft)."
---

# Conference Reviewer Mode

Modes: **full review** (default) · **panel** (3 reviewers + area-chair meta-review) · **writing review** (line-level) · **self-review loop** · **rebuttal prep** / **rebuttal**. Ask which, or infer it from the request.

## Workflow

1. **Venue.** Infer it from the class/style file (`neurips_*.sty`, `icml*.sty`, `iclr*.sty`, `acl.sty`, `cvpr.sty`, `IEEEtran`, …) or ask. Read only that venue's section of [forms.md](forms.md). Forms change yearly; if the current reviewer guidelines are available, follow them instead.
2. **Map, then read in reviewer order.** Run `<skill>/../latex-project/scripts/texmap.py` first. Then read: title/abstract → introduction (contributions) → figures and tables with captions → method → experiments → limitations → related work → appendix (only as needed).
3. **Claims ledger.** For every contribution claimed in the abstract or introduction, record the evidence (section, table or figure) and a verdict: supported / partly / unsupported. The ledger drives the soundness score.
4. **Assess** originality (closest work; run `latex-research-check` when novelty is in doubt), soundness (assumptions, proofs, baselines, ablations, seeds and variance, statistical tests, data leakage, compute fairness), significance, clarity, reproducibility (code, hyperparameters, data, compute), and limitations/ethics.
5. **Write the review** in the venue's form:
   - Every weakness gives a **location**, **why it matters** and **what would fix it**, tagged **[major]** or **[minor]**.
   - Separate fatal flaws from fixable ones. No generic comments: not "needs more experiments", but which experiment and why.
   - Questions must be answerable in a rebuttal and able to change the score.
   - Scores must match the text, and confidence must be honest. Be firm, fair and professional; review the paper, not the authors.
6. **Panel mode.** Write three independent reviews in sequence, each with its own focus and no repeated points:
   - R1, domain expert: method correctness and novelty against the closest work.
   - R2, empirical sceptic: baselines, statistics, ablations, leakage, reproducibility.
   - R3, adjacent-field reader: motivation, clarity, significance.
   Then an **AC meta-review**: points of agreement, the decisive issues, and a recommendation. (Use parallel subagents only if the user asks for them.)
7. **Writing review.** Produce a table of `file:line | issue | suggested rewrite`, covering:
   - undefined acronyms, or symbols used before their definition
   - overclaims ("significantly" without a test, "novel", unsupported "state of the art")
   - stacked hedges; sentences over ~35 words; vague passives ("it is shown")
   - inconsistent terms or tense
   - figures/tables never referenced; captions that aren't self-contained
   - "[12] shows" (use "Smith et al. [12] show")
8. **Submission checklist** (double-blind):
   - no author names, affiliations, acknowledgements or funding; self-citations written in the third person
   - no identifying URLs (use anonymous.4open.science); `\hypersetup{pdfauthor={}}`; anonymised supplement
   - page limit met; required sections present (limitations, broader impact, venue checklist); template margins and fonts unmodified
   - Quick scan: `grep -rniE "github\.com/|acknowledg|our (previous|prior) work|\\\\author\{" paper/`
9. **Rebuttal prep** (before reviews exist). List the 5 most likely criticisms, each with an evidence-backed response and any extra experiment it needs.

## Self-review loop (fix the paper until a computed stopping rule holds)

The scripts own state, routing and stopping; you review, judge and make minimal edits. `I` = `<skill>/scripts/issues.py` (ledger: `.agentex/issues.json`; `--project DIR` if the paper isn't the working folder).

1. **Review** (full review or panel) and record each weakness: `I add --source self --anchor sec/exp.tex:42 --severity major --text "…"`. Same text, same ID: re-raising a known point is a no-op, so dropped points stay dropped. At most 20 new self issues per round; keep the most important.
2. **Verdict every major** (minors when worth it): `I verdict <id> invalid|fixable|author --note "why"`. `invalid` = not a real problem (drop). `fixable` = a text/figure edit inside the anchor's section fixes it. `author` = needs new experiments, data, or a judgement call: report it, don't edit.
3. **Fix only `fixable` items**, smallest edit inside the anchored section. Never change claims in the abstract/introduction to make a problem go away; new numbers only through `\res{}`. Then `I fix <id> [--commit <sha>]`.
4. **Guard**: `I guard [main.tex]` runs build, `check_refs.py`, `results.py audit` and frozen-claim `claims.py diff` (when `latex-consistency` has one); one PASS/FAIL/SKIP line each. On FAIL, repair or revert your edit before going on.
5. **Stop?** `I stop` (exit 0 = stop). It requires no new valid major self issue in the latest round, a verdict on every major and every fixable fixed; it stops anyway at round 3 (`--max-rounds`). Otherwise `I round`, review the revised paper again (step 1), repeat.
6. Report: fixed items with file:line, then `author` items as a to-do list. `I list --open` shows what's left.

## Rebuttal (reviews have arrived)

1. Save each review as text, one file per reviewer (`reviews/R2.txt`), and `I import-reviews reviews/R2.txt`: numbered/bulleted points under Weaknesses/Questions/Comments each become an issue (summary, strengths and scores are skipped). Check the split; fix a severity with `I verdict <id> … --severity minor`.
2. Triage each point: `I verdict <id> … --anchor file:line`. Plan the edits and experiments with the author; `author` items need their input. Make `fixable` edits as in the loop (guard included) and record them with `I fix <id> --commit <sha>`.
3. `python3 <skill>/scripts/rebuttal.py draft --since v1-submitted --out rebuttal.md --limit-chars 5000` writes one block per point: the quote, an empty `Response:`, and `Changes:` (diff hunks since the tag in the point's section with file:line, fix commits, `\res{}` values new or changed since the tag), plus the latexdiff command for the change-tracked PDF (`latex-convert`, section D). It never overwrites an existing file.
4. The author writes every argument. Don't invent results or promise experiments that haven't run. Check length with `rebuttal.py count rebuttal.md --limit-chars 5000`.

## Output

Write the review to `review/<venue>-review.md`. In chat, give only the scores, the recommendation and the top 3 issues; don't paste the whole review.

Related skills: `latex-consistency` (paper vs code), `latex-research-check` (novelty), `latex-references` (`check_refs.py`), `latex-plagiarism-check`.
