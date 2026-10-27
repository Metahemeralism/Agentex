---
name: latex-consistency
description: "Audit a paper against its code and itself: hyperparameters the paper omits or misstates, a claim-by-claim evidence ledger, equations vs implementation, notation drift, overclaims and leakage. Freezes claims so edits can't change them silently. Use before submission or after code changes."
---

# Code ↔ Paper Consistency Audit

Goal: find every place where the manuscript and the code disagree, or where the manuscript disagrees with itself, **before a reviewer does**. This skill reports. Verdicts are flags for the authors and are never applied as edits, because only the author knows which side is right.

Why it works in small pieces: on real paper–code discrepancies (SciCoQA, arXiv:2601.12910), the best LLMs catch fewer than half. They are precise but miss a lot, and they miss more as the paper and code they are given get longer. The hardest cases are *paper omissions*: the code does something the paper never mentions. So scripts do the extraction and find the omissions deterministically, and the LLM judges **one claim at a time with a few candidate code lines**. It never reads the whole paper and repo at once.

## Workflow

### 1. Settings audit (deterministic, catches omissions)

```bash
python3 <skill>/scripts/settings_audit.py src/ paper/            # or paper/main.tex; --limit 0 lists everything
```

It reads settings from YAML/JSON/INI/TOML configs, argparse defaults, dataclass/config-class fields, module constants and literal arguments of ML calls (`AdamW(lr=3e-4)`, `DataLoader(batch_size=64)`, `clip_grad_norm_(p, 1.0)`) using `ast`, so code is never run. Then it reads the paper's `\input` tree (comments ignored, `\res{}` values filled in from a `results.py` registry) and ranks:

- **MISMATCH**: the paper names the setting with another value (`paper: 6 (setup.tex:3)`). This is always worth raising.
- **UNDISCLOSED**: the code sets something the paper never mentions, such as gradient clipping, warmup, label smoothing, seeds or data filters. Ask whether it matters for reproducing the results. If it does, it belongs in the setup or appendix.
- **NO-VALUE**: the paper names the setting ("we clip gradients") but never gives its value.
- `· also X at file:line`: the code holds two values for one setting, e.g. an argparse default and a config. Find out which one actually ran.

Numbers match across forms (`1e-3` = `0.001` = `$10^{-3}$` = `\num{1e-3}`, `0.1` = `10\%`, `50k`), and so do names (lr/η/learning rate, weight decay/ℓ2, β1/β2, warmup, max_grad_norm/gradient clipping and so on). Paths, logging, devices and I/O workers are ignored. It's heuristic: a value given in the paper but far from its setting's name can show as NO-VALUE, so check before reporting.

### 2. Numbers

Run `<skill>/../latex-results-sync/scripts/results.py audit paper/` first. It finds stale and hand-typed results deterministically. Then recompute from raw result files where you can (mean/std over the stated seeds, rounding, bolded "best").

### 3. Claim ledger: one claim, narrow context, a recorded verdict

```bash
python3 <skill>/scripts/claims.py extract paper/        # -> .agentex/claims.json; verdicts of unchanged claims are kept
python3 <skill>/scripts/claims.py next --n 5 --code src/
python3 <skill>/scripts/claims.py record 3fa9c2e1 --verdict supported --evidence src/train.py:42 --note "AdamW, lr from config"
python3 <skill>/scripts/claims.py report               # counts + UNSUPPORTED / PARTIAL / CHANGED with file:line
```

- `extract` keeps sentences with numbers or `\res{}`, comparatives/superlatives ("outperforms", "state-of-the-art", "significantly", "consistently"), "we show/prove/demonstrate", and method statements ("we train/use/apply…"). Each gets a stable id (a hash of its text). On re-extract, edited claims become **CHANGED** (verdict reset, the old one shown) and deleted ones **REMOVED**.
- `next` prints each unchecked claim with **≤3 candidate code locations** found by numbers, setting names and keywords. Open only those lines (±20) and grep for more only if they don't settle it. Judge that one claim:
  - **supported**: the code does what the sentence says (cite the line).
  - **partial**: part of it holds (e.g. Adam vs AdamW + weight decay; "5 seeds" but 3 result files).
  - **unsupported**: the code contradicts it, the method isn't implemented, or no result backs it (a hard-coded metric, a comparison with no baseline run).
  - **unclear**: it can't be decided from the repo (runtime overrides, external results).
- `record` refuses evidence that doesn't exist (file missing, line out of range) and needs evidence for supported/partial.
- Claims that belong elsewhere: equations go through the `latex-math` workflow (reductions, indices, constants, $\epsilon$, std vs. variance, log base, 0- vs. 1-indexing), and qualitative claims ("significantly" without a test, causal language for correlational results) get **unsupported** with a note.

### 4. Freeze the claim spine

After the authors sign off, run `claims.py freeze`. From then on `claims.py diff` (run from the project folder) exits **1** and prints every frozen claim whose text changed or vanished, exits **0** if all are intact, and exits **2** if nothing is frozen yet. Review loops use it as an edit guard, so a rewrite can't quietly weaken or inflate a claim. If a change is intended, re-run `freeze`.

### 5. Internal consistency and methodology (LLM, report only)

- The same quantity reported differently in the abstract, intro, results and conclusion; numbers in the text vs. tables vs. figures; contributions never evaluated; dataset sizes/splits that don't add up.
- The method described differently in the main text, the algorithm box and the appendix. Notation drift (`latex-math`). Cross-refs: `<skill>/../latex-references/scripts/check_refs.py`.
- Red flags even when code and paper agree: test data used for model selection or early stopping; normalisation or feature selection fitted before the split; duplicates across splits; temporal leakage; baselines tuned less or preprocessed differently; a single seed with small differences; accuracy on heavily imbalanced data.
- Large repo: map the paper with `<skill>/../latex-project/scripts/texmap.py` and grep rather than reading whole files.

### 6. Report

Lead with MISMATCH and unsupported claims, then UNDISCLOSED settings and partial claims, then internal inconsistencies, then red flags. For each one give the quote, both locations (`paper:line` ↔ `code:line`), why it matters, and a fix *for each side* (update the text **or** the code). End with the `report` counts. Ask before editing anything. Once the author decides, replace hand-typed numbers with `\res{}` macros (`latex-results-sync`) so they can't drift again.

Status for the dashboard: `.agentex/status/settings.json` and `.agentex/status/consistency.json`.
