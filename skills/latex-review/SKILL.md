---
name: latex-review
description: "Review a LaTeX paper as a conference or journal referee would (NeurIPS, ICML, ICLR, ACL, CVPR, IEEE, journals): scored review, reviewer panel with meta-review, line-level writing feedback, anonymity checklist and rebuttal prep."
---

# Conference Reviewer Mode

Modes: **full review** (default) · **panel** (3 reviewers + area-chair meta-review) · **writing review** (line-level) · **rebuttal prep**. Ask which, or infer it from the request.

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
9. **Rebuttal prep.** List the 5 most likely criticisms, each with an evidence-backed response and any extra experiment it needs. For the revised version, attach a change-tracked PDF: `latexdiff-vc --git --flatten -r v1-submitted main.tex` (`latex-convert`, section D).

## Output

Write the review to `review/<venue>-review.md`. In chat, give only the scores, the recommendation and the top 3 issues; don't paste the whole review.

Related skills: `latex-consistency` (paper vs code), `latex-research-check` (novelty), `latex-references` (`check_refs.py`), `latex-plagiarism-check`.
