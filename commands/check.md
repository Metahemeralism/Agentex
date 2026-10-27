---
description: Run AgenTeX's cheap offline checks on this paper (numbers, stale figures, references, settings, claims, figures, open issues)
---
Run AgenTeX's deterministic checks that are quick and need no network on the LaTeX paper in this project. Each script is in the named AgenTeX skill's `scripts/` folder; read that skill's SKILL.md for its arguments, and skip any that is not installed. They write `.agentex/status/<tool>.json`, which the `/agentex` pane shows.

- numbers and stale figures: `results.py audit` and `results.py stale` (latex-results-sync)
- labels and citation keys: `check_refs.py` (latex-references)
- settings the paper never discloses: `settings_audit.py <code_dir> <paper>` (latex-consistency)
- the claim ledger: `claims.py report` (latex-consistency), if `.agentex/claims.json` exists
- figures: `figcheck.py main.tex` (latex-tables-figures; add `--no-compile` when no TeX engine is installed)
- open review issues: `issues.py list --open` (latex-review), if `.agentex/issues.json` exists

Change nothing in the paper. Leave out the slow or online checks (citation verification, cited-claim checks, the repro smoke test, arXiv HTML, prior-work and overlap searches) and name them at the end as optional next steps.

Finish with a short table (check, status, the top finding as `file:line`) and the one fix to make first.
