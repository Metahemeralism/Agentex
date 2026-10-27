#!/usr/bin/env python3
"""AgenTeX cite guard (PreToolUse on Edit/Write/MultiEdit of .tex files).

Blocks an edit that ADDS a \\cite key whose .bib entry has not been verified by
skills/latex-references/scripts/cite_verify.py (verified, published, unverifiable-type or
metadata-mismatch entries pass; not-found, bad-doi, missing, retracted and never-checked keys are
blocked). Editing an entry after verification invalidates it. Disable with AGENTEX_CITE_GUARD=0.
"""
import json
import os
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN / 'skills' / 'latex-references' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from cite_verify import CITE_RE, fingerprint, load_cache, parse_bib, project_files, strip_comments  # noqa: E402

PASS = {'verified', 'published', 'mismatch', 'unverifiable'}


def keys_in(text):
    return {k.strip() for m in CITE_RE.finditer(strip_comments(text or ''))
            for k in m.group(1).split(',') if k.strip() and k.strip() != '*'}


def project_root(path):
    """Nearest ancestor holding .agentex/cite-cache.json, else the nearest git root, else the file's folder."""
    for d in [path.parent, *path.parent.parents]:
        if (d / '.agentex' / 'cite-cache.json').exists():
            return d
    for d in [path.parent, *path.parent.parents]:
        if (d / '.git').exists():
            return d
    return path.parent


def added_keys(tool, ti, path):
    if tool == 'Write':
        old = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
        return keys_in(ti.get('content')) - keys_in(old)
    if tool == 'MultiEdit':
        edits = ti.get('edits') or []
        return keys_in(''.join(e.get('new_string', '') for e in edits)) - keys_in(''.join(e.get('old_string', '') for e in edits))
    return keys_in(ti.get('new_string')) - keys_in(ti.get('old_string'))


def check(data):
    """-> message if the edit must be blocked, else None."""
    ti = data.get('tool_input') or {}
    path = Path(ti.get('file_path') or '')
    if path.suffix != '.tex':
        return None
    added = added_keys(data.get('tool_name'), ti, path)
    if not added:
        return None
    root = project_root(path.resolve())
    cache = load_cache(root)
    bibs = [root / b for b in cache.get('bibs', [])] or project_files(root)[1]
    entries = {e['key']: e for b in bibs if b.exists() for e in parse_bib(b.read_text(encoding='utf-8', errors='replace'))}
    problems = []
    for k in sorted(added):
        known = cache.get('keys', {}).get(k)
        if k not in entries:
            problems.append(f'{k}: no .bib entry (add one from an authoritative source first)')
        elif not known or known.get('fp') != fingerprint(entries[k]):
            problems.append(f'{k}: not verified yet' + (' (entry changed since last check)' if known else ''))
        elif known.get('status') not in PASS:
            reason = cache.get('entries', {}).get(known['fp'], {}).get('message', '')
            if known['status'] == 'retracted':
                problems.append(f'{k}: RETRACTED ({reason}). A retracted work cannot support a claim: remove the '
                                'citation, or if the retraction itself is your point, cite the retraction notice '
                                '(add its own .bib entry from that DOI) and say in the text that the work was retracted')
            else:
                problems.append(f'{k}: {known["status"]}' + (f' ({reason})' if reason else ''))
    if not problems:
        return None
    keys = ','.join(sorted(added))
    return ('AgenTeX cite guard blocked this edit: it adds citation keys that are not verified.\n  '
            + '\n  '.join(problems)
            + f'\nVerify them first:\n  python3 "{SCRIPTS / "cite_verify.py"}" "{root}" --keys {keys}\n'
            'Then cite only keys that come back verified/published. Never invent or guess a reference; '
            'if a source cannot be verified, tell the user instead of citing it. '
            '(The user can disable this guard with AGENTEX_CITE_GUARD=0.)')


def main():
    if os.environ.get('AGENTEX_CITE_GUARD') == '0':
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        msg = check(data)
    except Exception as e:  # a bug in the guard must never block the user's work
        print(f'AgenTeX cite guard skipped: {e}', file=sys.stderr)
        return 0
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
