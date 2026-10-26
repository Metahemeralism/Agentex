# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AgenTeX: a Claude Code plugin (18 Agent Skills + 2 hooks + a UI band) that keeps LaTeX papers honest to the code behind them. The folder is named `algo-trade` for historical reasons; the project is AgenTeX (`github.com/Metahemeralism/AgenTeX`). There is no build step. Skills are Markdown plus Python scripts, hooks are Python, and the band is TypeScript run by Claude Code's hooks-module API.

## Commands

```bash
# All Python tests (each directory is its own suite; scripts are stdlib-only, Python 3.8+)
for d in hooks skills/*/scripts tests; do python3 -m unittest discover -s "$d" -q || exit 1; done

# One suite / one test file
python3 -m unittest discover -s skills/latex-references/scripts -q
python3 -m unittest discover -s skills/latex-debug/scripts -p test_texlog.py -q

# Plugin manifest check + the band's TypeScript tests (hooks/ui.test.ts)
claude plugin validate . && claude plugin test .

# Load the plugin from disk for one session, without installing
claude --plugin-dir .
```

Some tests print stray lines (e.g. "arxiv_submission exists…", "MODIFIED fig.txt…"). Those are expected output from negative cases; only the final `OK`/`FAILED` matters.

TikZ patterns: `skills/latex-tikz/scripts/tikzcheck.sh <fig.tex>` compiles a figure and writes a 100 dpi PNG preview (needs `latexmk` or `tectonic`; previews need poppler).

## Architecture

**Plugin wiring.** `.claude-plugin/plugin.json` (version, `userConfig.animations`, `types`) and `marketplace.json` (source `./`). `hooks/hooks.json` registers:
- `SessionStart` → `compile_loop.py --init` (records a timestamp so builds only follow real edits)
- `PreToolUse` on `Edit|Write|MultiEdit` → `cite_guard.py`
- `Stop` → `compile_loop.py`
- `modules: ["./ui.tsx"]` → the band above the prompt

**Hooks reuse skill scripts, so the two are coupled.** Moving or renaming these functions breaks a hook:
- `hooks/cite_guard.py` imports `CITE_RE, fingerprint, load_cache, parse_bib, project_files, strip_comments` from `skills/latex-references/scripts/cite_verify.py`. It blocks an edit to a `.tex` file that *adds* a `\cite` key unless that key's cache status is in `{verified, published, mismatch, unverifiable}` **and** the entry's fingerprint hasn't changed since verification.
- `hooks/compile_loop.py` imports `digest` from `skills/latex-debug/scripts/texlog.py` and `compile_cmd` from `skills/latex-debug/scripts/build.py` (engine choice: xelatex/lualatex from the source, a latexmkrc otherwise). When LaTeX sources are newer than the last build, it compiles every main document (`\documentclass` plus `\begin{document}`, not `standalone`) and blocks the Stop with a digest when there are errors or *new* undefined refs or citations. It gives up after 3 blocks in a row.

**The band (`hooks/ui.tsx`, `hooks/frames.ts`, `types/index.d.ts`).** It is cosmetic only: nothing else depends on it. `frames.ts` has a `LABELS` regex table that maps Bash commands (script names like `cite_verify.py`, `results.py audit`, `latexmk`) to activity labels. Renaming a script means updating this table and `ui.test.ts`. The state shape is declared in `types/index.d.ts` (`PluginState.agentex`).

**Runtime state.** Everything goes in `.agentex/` inside the *user's* project: `cite-cache.json`, `build-state.json`, `suggested.bib`, and the provenance lock. That directory ignores itself in git. Corrections to references and numbers are written as suggestions and never applied silently.

**Skills (`skills/<name>/`).** Each skill is a `SKILL.md` with `name`/`description` frontmatter, plus optional `scripts/`, `templates/`, `assets/` and `reference/`. A `SKILL.md` refers to its own files as `<skill>/scripts/...` and to another skill's as `<skill>/../latex-x/scripts/...`. The `description` is always loaded and decides when the skill triggers: keep it under 300 characters and phrase it as *when to use it*. Bodies load only on use.

**Lean by rule.** `tests/test_plugin.py` enforces it: frontmatter name = folder, descriptions ≤ 300 characters, bodies ≤ 500 lines, every path a `SKILL.md` mentions exists, every `reference/*.md` is linked from its `SKILL.md`, and the skill count matches the README badge and table, `plugin.json` and `install.sh`. A reference file is only worth shipping if it holds what the model doesn't know or gets wrong (venue-specific facts, template-specific macros, measured budgets). General LaTeX manuals don't qualify.

**latex-tikz specifics.** `assets/agentex-tikz.sty` is the shared style sheet. Every `assets/pattern-*.tex` must compile standalone against it, and `docs/gallery/*.png` are renders of those patterns. `reference/tikz-manual.jsonl` is extracted from the PGF/TikZ manual (LPPL 1.3c, not MIT; see `reference/NOTICE.md`). Only maintainers regenerate it, with `scripts/build_index.py`. `tikzref.py` searches it offline.

## Conventions

- Scripts use the **standard library only** (no third-party imports) and each has a `test_*.py` next to it.
- Prefer a deterministic script to written instructions wherever a check can be computed. The LLM organises the work; the scripts make the final call.
- Keep token cost low: script output should be short digests, not raw logs.
- Hooks must be safe to fail: the cite guard checks only `.tex` edits, the compile loop does nothing without `latexmk`/`tectonic`, and they can be turned off with `AGENTEX_CITE_GUARD=0` / `AGENTEX_COMPILE_HOOK=0`.
- When the skill count, hook count or skill list changes, update the README badges and tables, the `plugin.json` description and the `install.sh` tagline (all say "18 skills"; `tests/test_plugin.py` checks).
- Every `.tex` under `skills/*/templates/` must compile with pdfLaTeX and with tectonic (XeTeX): `python3 skills/latex-debug/scripts/build.py <file>` on a scratch copy. The compile-loop hook also builds templates in place in this repo when you edit them; their PDFs and logs are gitignored.
- Material from latex-document-skill (MIT): the `latex-documents` and `latex-poster` templates, `latex-convert`'s conversion guide and profiles and `check_fragments.py`, `latex-debug/chktexrc`. Keep each skill's `NOTICE.md` in step when you change them.
