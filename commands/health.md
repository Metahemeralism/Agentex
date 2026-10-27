---
description: Summarise AgenTeX's latest check results for this paper and say what to fix or run next
---
Summarise the health of the LaTeX paper in this project from AgenTeX's result files. Do not re-run any check.

1. Read every `.agentex/status/*.json` (`{tool, status: ok|warn|fail, summary, counts, items: [{where, message}], updated}`) and `.agentex/build-state.json` (the compile loop: `blocks` > 0 means the last build broke, `problems` lists unresolved references per main file, `stamp` is when the LaTeX sources last changed, in epoch seconds).
2. One line per check, worst first: `✗`, `!` or `✓`, the tool, its summary and the result's age. Call a result older than `stamp` stale. Under each failing check, give up to three of its items as `file:line message`.
3. Name the checks with no result yet (of: build, preflight, citations, cite-claims, numbers, provenance, repro, smoke, settings, consistency, figures, arxiv-html, review).
4. End with the one most useful next step: the fix to make first, or the check to run (`/agentex:check` for the cheap offline ones, `/agentex:preflight <venue>` before submitting).

If there is no `.agentex/` folder, say that no AgenTeX check has run here yet and suggest `/agentex:check`. `/agentex` shows the same results live in a pane.
