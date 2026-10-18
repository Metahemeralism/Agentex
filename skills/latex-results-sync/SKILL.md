---
name: latex-results-sync
description: "Keep a paper's numbers, tables and figures in sync with the code: results JSON to \\res{} macros, an audit for hand-typed and stale numbers, generated booktabs tables, and provenance tracking that flags and rebuilds figures older than their scripts or data. Use after reruns or before submission."
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

## Notes

- `make` runs the manifest's commands in the shell. Only run manifests the author wrote or reviewed.
- Hand-off: `latex-consistency` for claims that are not numbers (method descriptions, hyperparameters in prose); `latex-tables-figures` for figure styling.
