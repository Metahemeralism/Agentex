---
description: Check this paper against a venue's submission rules before you submit (page limit, anonymity, required sections, disclosures)
argument-hint: <venue, e.g. neurips; "list" shows them>
---
Run AgenTeX's submission gate on the LaTeX paper in this project: `preflight.py <main.tex> --venue <venue>` from the latex-submit skill (its SKILL.md gives the other options). Venue: $ARGUMENTS

If no venue is given, infer it from the document class or style file and say which you picked; `--venue list` shows the known ones. Change nothing in the paper.

Report each failing rule with `file:line`, then say plainly whether anything blocks submission and what to fix first. If it flags a missing LLM-use disclosure, offer to draft one with `disclosure.py`. The result is written to `.agentex/status/preflight.json`, which the `/agentex` pane shows.
