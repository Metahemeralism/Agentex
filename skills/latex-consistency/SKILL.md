---
name: latex-consistency
description: "Audit a paper against the code that produced it and against itself: equations vs implementation, hyperparameters vs configs, tables vs result files, notation drift, overclaims and leakage red flags. Use before submission or after code changes."
---

# Code ↔ Paper Consistency Audit

Goal: find every place where the manuscript and the code disagree, or where the manuscript disagrees with itself, **before a reviewer does**. This skill reports; it does not silently "fix" either side, because only the author knows which one is right.

## Workflow

### 1. Inventory both sides

- **Paper**: all `.tex` files (resolve `\input`/`\include`), generated tables, figure captions, appendix, supplementary material.
- **Code**: model/algorithm implementation, configs (`yaml`, `json`, `toml`, argparse defaults, Hydra configs), training/eval scripts, result files (CSV/JSON/logs), README, `CITATION.cff`.
- Save tokens: map the paper with the `latex-project` skill's `scripts/texmap.py`, and on the code side `grep -rn` for each claimed value or name instead of reading whole files.
- Determine which code version the paper describes (git tag/commit, if stated). Audit against that.

### 2. Extract claims from the paper

Build a claims table: every concrete, checkable statement.

| # | Claim (quoted) | Location | Type |
|---|---|---|---|
| 1 | "learning rate of $3\times10^{-4}$" | `sections/setup.tex:14` | hyperparameter |
| 2 | Eq. (3): $\loss = \sum_i \ell_i$ | `method.tex:40` | equation |
| 3 | "trained for 100 epochs" | `setup.tex:16` | training |
| 4 | Table 2: Ours = 91.3 | `tables/results.tex:8` | result |
| 5 | "we use 5 random seeds" | `setup.tex:20` | protocol |

Types to hunt for: hyperparameters, architecture sizes (layers, widths, heads), dataset names/splits/sizes/preprocessing, number of runs/seeds, metrics and how they are computed, equations, algorithm steps, compute/hardware/runtime, software versions, and qualitative claims ("outperforms all baselines", "converges faster", "statistically significant").

### 3. Verify each claim against the code

For each claim, find the evidence (file:line) and classify:

- ✅ **Consistent**: matches.
- ❌ **Contradiction**: code does something different (e.g. paper says `lr=3e-4`, config says `1e-3`; paper says sum, code says mean; paper says Adam, code uses AdamW with weight decay 0.01).
- ⚠️ **Ambiguous / unverifiable**: can't be confirmed from the code (value overridden at runtime, result file missing, claim depends on unreported runs).
- 🕳️ **Omission**: code does something material the paper never mentions (gradient clipping, data augmentation, warm-up, early stopping on the test set, label smoothing, filtering of examples, a different preprocessing for baselines).

Equations: re-derive from code with the `latex-math` workflow (reductions, indices, constants, $\epsilon$ terms, std vs. variance, log base, 0- vs. 1-indexing).

Results: recompute from raw result files when possible (mean/std over the stated seeds, rounding). Check that bolded "best" values really are best and that ± means what the caption says.

### 4. Check internal consistency of the paper

- Same quantity reported differently in abstract, intro, results and conclusion (e.g. "12% improvement" vs. Table 2 implying 9%).
- Numbers in text vs. tables vs. figures.
- Contributions listed in the intro that are never delivered/evaluated.
- Notation drift (see `latex-math` notation audit).
- Dataset sizes/splits that don't add up; percentages that don't sum.
- Method described differently in the main text vs. algorithm box vs. appendix.
- Cross-references: run `latex-references/scripts/check_refs.py`.
- Overclaiming: "significantly" without a test; "state of the art" without comparison to it; causal language for correlational results.

### 5. Methodology red flags (report even if code and paper agree)

- Test data used for model selection, early stopping or hyperparameter tuning.
- Data leakage: normalisation/feature selection fitted on the full dataset before splitting; duplicates across splits; temporal leakage in time series.
- Baselines tuned less than the proposed method, or run with different preprocessing.
- Single seed with small differences; no variance reported.
- Metric mismatch (e.g. accuracy on heavily imbalanced data).

### 6. Report

Lead with contradictions, then omissions, then ambiguities, then internal inconsistencies, then red flags. For each: quote, both locations (`paper:line` ↔ `code:line`), why it matters, and a suggested fix *for each side* (update text **or** update code). End with the count of claims checked and how many are consistent.

Ask before editing. When the author confirms which side is correct, apply the fix, and where possible replace hard-coded numbers with generated macros (`\input{results.tex}`) so they cannot drift again.
