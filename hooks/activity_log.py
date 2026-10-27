#!/usr/bin/env python3
"""AgenTeX activity log (PostToolUse on Edit/Write/MultiEdit of .tex/.bib files).

Appends one JSON line per agent edit to <project>/.agentex/activity.jsonl:
  {"time", "file" (relative to the project), "tool", "added_lines", "removed_lines", "section"?}
skills/latex-submit/scripts/disclosure.py turns this log into a draft LLM-use disclosure, and
preflight.py uses it to decide whether a venue's disclosure rule applies. Never blocks: always exits 0.
Disable with AGENTEX_ACTIVITY_LOG=0.
"""
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TRACKED = {'.tex', '.bib'}
SECTION = re.compile(r'\\(?:chapter|section|subsection)\*?\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}')


def line_counts(tool, ti, tr):
    """-> (added, removed) lines. Claude Code's structuredPatch is exact; the inputs are the fallback."""
    patch = tr.get('structuredPatch') if isinstance(tr, dict) else None
    if patch:
        lines = [l for hunk in patch for l in hunk.get('lines', [])]
        return sum(l.startswith('+') for l in lines), sum(l.startswith('-') for l in lines)
    if tool == 'Write':  # shortcut: an overwrite without a patch counts every line as added
        return len((ti.get('content') or '').splitlines()), 0
    added = removed = 0
    for e in ti.get('edits') or [ti]:
        for l in difflib.ndiff((e.get('old_string') or '').splitlines(), (e.get('new_string') or '').splitlines()):
            added += l.startswith('+ ')
            removed += l.startswith('- ')
    return added, removed


def section_of(path, ti):
    """Title of the \\section the edited text now sits in, if it can be found."""
    probe = (ti.get('new_string') or ((ti.get('edits') or [{}])[-1]).get('new_string') or '').strip()
    if not probe or not path.exists():
        return None
    text = path.read_text(encoding='utf-8', errors='replace')
    i = text.find(probe[:200])
    heads = SECTION.findall(text, 0, i + len(probe[:200])) if i >= 0 else []
    return heads[-1].strip() if heads else None


def entry(data, now=None):
    """The log record for one hook call, or None if the edit is not to a .tex/.bib file."""
    tool, ti = data.get('tool_name'), data.get('tool_input') or {}
    path = Path(ti.get('file_path') or '')
    if tool not in ('Edit', 'Write', 'MultiEdit') or path.suffix not in TRACKED:
        return None
    root = Path(data.get('cwd') or os.getcwd())
    added, removed = line_counts(tool, ti, data.get('tool_response'))
    rec = {'time': (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'file': os.path.relpath(path, root) if path.is_absolute() else str(path),
           'tool': tool, 'added_lines': added, 'removed_lines': removed}
    section = section_of(path if path.is_absolute() else root / path, ti) if tool != 'Write' else None
    if section:
        rec['section'] = section
    return root, rec


def append(root, rec):
    d = root / '.agentex'
    d.mkdir(parents=True, exist_ok=True)
    if not (d / '.gitignore').exists():
        (d / '.gitignore').write_text('*\n')
    with open(d / 'activity.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec) + '\n')


def main():
    if os.environ.get('AGENTEX_ACTIVITY_LOG') == '0':
        return 0
    try:
        got = entry(json.load(sys.stdin))
        if got:
            append(*got)
    except Exception as e:  # logging must never get in the user's way
        print(f'AgenTeX activity log skipped: {e}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
