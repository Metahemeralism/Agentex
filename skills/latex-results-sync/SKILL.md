---
name: latex-results-sync
description: "Keep a paper's numbers and figures in sync with the code: \\res{} macros from results JSON, an audit for hand-typed and stale numbers, generated tables, provenance that rebuilds stale figures and a per-figure reproduction table. Use after reruns, before submission or for reproducibility checklists."
---

# Results Sync: the paper as a build artefact of the code

Failure this prevents: a rerun changes accuracy from 87.3 to 86.9, but the abstract, a table and the discussion still say 87.3, and `fig3.pdf` came from last month's script.

Rule: **a result is never typed into the paper.** Scripts write it, a registry turns it into macros, and an audit proves nothing slipped through. Changes to numbers are proposed as diffs for the author to approve.

## Setup (once per project)

1. **Experiment code writes JSON**, one file per experiment (the file name becomes the key prefix):
   ```python
   json.dump({"cifar10": {"acc": acc, "loss": loss}, "params": n_params}, open("results/resnet.json", "w"))
   ```
2. **Build the registry:** `python3 scripts/results.py build results/ -o paper/results.tex`, then `\input{results}` **in the preamble**.
3. **Use macros in the text**, with display rounding in LaTeX, not in the data:
   ```latex
   \num[round-mode=places,round-precision=1]{\respct{resnet.cifar10.acc}}\,\%   % 0.87314 -> 87.3 %
   \num{\res{resnet.params}} parameters                                         % 11 173 962
   ```
   An unknown key prints a bold **??**, like a broken `\ref`.
4. **Generate tables:** `results.py table results/main.csv -o paper/tables/main.tex --pm --bold-max acc --bold-min loss --decimals 1`. This gives booktabs, `mean ± std` from `X`/`X_std` columns, best value in bold and consistent rounding. `\input` it inside your `table` float, so the caption and label stay yours.
5. **Record provenance** in `agentex-artifacts.json` at the repo root:
   ```json
   {"outputs": {
     "paper/figures/loss.pdf": {"cmd": "python scripts/plot_loss.py", "inputs": ["scripts/plot_loss.py", "results/*.json"]},
     "paper/results.tex": {"cmd": "python3 <skill>/scripts/results.py build results -o paper/results.tex", "inputs": ["results/*.json"]}
   }}
   ```

## Routine (after every rerun, and before submission)

```bash
python3 scripts/results.py stale --paper paper/   # MISSING / STALE / MODIFIED / NO-SOURCE per output
python3 scripts/results.py make                   # rerun producers of stale outputs; records input hashes + commit
python3 scripts/results.py audit paper/           # STALE / UNDEFINED / HARD-CODED numbers with file:line
```

- **STALE:** the number equals a *previous* value of a registry key (history is kept across rebuilds), which is exactly the leftover 87.3. Highest priority.
- **HARD-CODED:** the number equals a current value. The suggested `\res`/`\respct` replacement is given; show it to the author as a diff before applying.
- **UNDEFINED:** `\res{key}` with no such key, usually a renamed experiment.
- **`stale` statuses:** MODIFIED means an output was edited by hand after its script made it; NO-SOURCE means the paper includes a figure no manifest entry produces. Ask where it came from.

The audit ignores comments, labels, lengths (`0.45\linewidth`, `3.5cm`), optional arguments, tabular specs, TikZ/pgfplots coordinates, years, small integers, one-significant-digit values and generated files. It doesn't guess when more than 3 keys match a number. It reads LaTeX structure, not a regex over raw text, but it's still heuristic: review its suggestions.

## Reproduction table (artifact evaluation, reproducibility checklists)

One row per paper figure/table, as reviewers and artifact-evaluation committees ask for: where it is (`\label`, caption, file:line), the command, inputs with short hashes, commit, last runtime and hardware, and FRESH / STALE / MISSING / NO-SOURCE.

```bash
python3 <skill>/scripts/repro.py table --paper paper/                      # markdown table on stdout
python3 <skill>/scripts/repro.py table --paper paper/ --write README.md    # diff of the agentex:repro block; --apply writes it
python3 <skill>/scripts/repro.py smoke --outputs paper/figures/loss.pdf    # rerun in a clean checkout of HEAD, compare
python3 <skill>/scripts/repro.py checklist --paper paper/                  # DRAFT evidence for compute, code, seeds, error bars, data
```

- `make` records wall-clock seconds, platform, Python, CPU count and GPUs (from `nvidia-smi`) for each output; `table` and `checklist` read them from the lock.
- `table` follows the `\input` tree of each main document and maps every `\includegraphics`/`\input` of an output to its float. `--write` touches only the text between `<!-- agentex:repro:start -->` and `<!-- agentex:repro:end -->` (appended if absent). NO-SOURCE rows are figure/table floats no output feeds (hand-drawn TikZ is skipped): ask the author where they came from.
- `smoke` runs the selected producers (default all) in a throwaway `git worktree` and reports REPRODUCED (same sha256, or JSON numbers within `--tolerance`, relative, default 1e-6), DIFFERS (with the differing keys) or FAILED (first error lines, or inputs missing from the commit). PDFs and PNGs usually differ only by embedded timestamps, so compare those visually. It tests HEAD, not uncommitted edits, and runs the manifest's commands, so the safety note below applies.
- `checklist` gives file:line pointers or "not found" for each question and never answers one. Runtime covers only producers run through `make`; training jobs outside the manifest are not counted. The author writes the checklist.

## Notes

- `make` and `smoke` run the manifest's commands in the shell. Only run manifests the author wrote or reviewed.
- Hand-off: `latex-consistency` for claims that are not numbers (method descriptions, hyperparameters in prose); `latex-tables-figures` for figure styling.
