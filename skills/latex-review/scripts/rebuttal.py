#!/usr/bin/env python3
"""Draft a rebuttal skeleton from the issue ledger: every reviewer point quoted, with the changes made since a
revision linked to it. The author writes every argument; this never invents one.

  rebuttal.py draft --since v1-submitted [--out rebuttal.md] [--limit-chars 5000] [--main paper/main.tex] [--force]
  rebuttal.py count rebuttal.md [--limit-chars 5000]      per-reviewer characters once the responses are written
Global --project DIR (default .), as for issues.py.
Links per point: `git diff <rev>` hunks in the point's section (anchor -> section via the \\input tree), commits
recorded with `issues.py fix --commit`, and \\res{} keys those hunks use that are new or changed in the results
registry since <rev>. Characters counted are what gets posted: quotes and responses, not Changes lists or
<!-- comments -->. Stdlib only.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issues  # noqa: E402

LEVELS = {'part': 0, 'chapter': 1, 'section': 2, 'subsection': 3, 'subsubsection': 4}
SECTION = re.compile(r'\\(part|chapter|section|subsection|subsubsection)\*?\s*(?:\[[^\]]*\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}')
INPUT = re.compile(r'\\(?:input|include|subfile)\s*\{([^}]+)\}')
HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')
REG_DEF = re.compile(r'\\@namedef\{agx@res@([^}]*)\}\{([^}]*)\}')  # registry format of latex-results-sync
RES_USE = re.compile(r'\\res(?:pct)?\{([^}]*)\}')
MAX_LINKS = 8
BUILD = issues.SKILLS / 'latex-debug' / 'scripts' / 'build.py'


def git(args, cwd):
    """stdout of a git command, or None if it fails."""
    try:
        p = subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


# ------------------------------------------------------------------ where a line sits in the document

def section_index(main):
    """{file: [(line, title)]}: the heading in effect from each line on, carried across \\input like LaTeX does."""
    index = {}

    def title(heads):
        return ' › '.join(h for h in heads if h) or 'front matter'

    def visit(path, heads):
        if path in index or not path.is_file():
            return heads
        marks = index[path] = [(0, title(heads))]
        for n, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
            line = re.sub(r'(?<!\\)%.*', '', line)
            for m in SECTION.finditer(line):
                k = LEVELS[m[1]]
                heads = heads[:k] + [None] * (k - len(heads)) + [' '.join(m[2].split())]
                marks.append((n, title(heads)))
            for m in INPUT.finditer(line):
                child = main.parent / m[1].strip()
                heads = visit((child if child.suffix else child.with_suffix('.tex')).resolve(), heads)
                marks.append((n, title(heads)))
        return heads

    visit(main.resolve(), [])
    return index


def section_at(index, path, line):
    marks = index.get(path)
    if not marks or line is None:
        return None
    current = marks[0][1]
    for n, t in marks:
        if n > line:
            break
        current = t
    return current


# ------------------------------------------------------------------ what changed since <rev>

def hunks(repo, rev):
    """[{path, start, end, added}] for .tex changes between rev and the working tree (new-file line numbers)."""
    out = git(['diff', '--unified=0', '--no-color', '--no-ext-diff', rev, '--', '*.tex'], repo) or ''
    res, path, in_header = [], None, False
    for line in out.splitlines():
        if line.startswith('diff --git'):
            in_header, path = True, None
        elif in_header and line.startswith('+++ '):
            name = line[4:].rstrip('\t').strip('"')
            path = None if name == '/dev/null' else (repo / name[2:]).resolve()
        elif line.startswith('@@'):
            in_header = False
            m = HUNK.match(line)
            if m and path:
                start, n = int(m[1]), int(m[2] if m[2] is not None else 1)
                res.append({'path': path, 'start': start, 'end': start + max(n, 1) - 1, 'added': []})
        elif line.startswith('+') and not in_header and res and path:
            res[-1]['added'].append(line[1:])
    return res


def registry_changes(project, repo, rev):
    """(registry file, current \\res values, {key: (old or None, new)}), compared with rev."""
    reg = None
    for p in sorted(project.rglob('*.tex')):
        if '.git' not in p.parts and 'agx@res@' in p.read_text(encoding='utf-8', errors='replace')[:4000]:
            reg = p
            break
    if not reg:
        return None, {}, {}
    current = dict(REG_DEF.findall(reg.read_text(encoding='utf-8', errors='replace')))
    old = dict(REG_DEF.findall(git(['show', f'{rev}:{reg.resolve().relative_to(repo).as_posix()}'], repo) or ''))
    return reg.resolve(), current, {k: (old.get(k), v) for k, v in current.items() if old.get(k) != v}


# ------------------------------------------------------------------ the draft

def posted_chars(block):
    """Characters a reviewer would see: drops headings, <!-- comments --> and Changes lists."""
    block = re.sub(r'<!--.*?-->', '', block, flags=re.S)
    keep, in_changes = [], False
    for line in block.splitlines():
        if line.startswith('Changes:'):
            in_changes = True
        elif in_changes and line.startswith(('- ', '  ')):
            pass
        else:
            in_changes = False
            if not line.startswith('#'):
                keep.append(line)
    return len('\n'.join(keep).strip())


def reviewer_blocks(text):
    """[(reviewer, block)] split on '## Reviewer <name>' headings."""
    parts = re.split(r'^## Reviewer (\S+).*$', text, flags=re.M)
    return list(zip(parts[1::2], parts[2::2]))


def budget(n, limit):
    if not limit:
        return f'{n} chars'
    return f'{n}/{limit} chars' + (f' OVER by {n - limit}' if n > limit else '')


def draft(project, rev, main=None, limit=None):
    """-> (markdown, digest lines). ValueError when there is nothing to draft from."""
    ledger = issues.load(project)
    points = [i for i in ledger['issues'].values() if i['source'].startswith('reviewer:')]
    if not points:
        raise ValueError('no reviewer points in the ledger; run `issues.py import-reviews <file>` first')
    top = git(['rev-parse', '--show-toplevel'], project)
    if not top:
        raise ValueError(f'{project} is not in a git repository')
    repo = Path(top.strip()).resolve()
    if git(['rev-parse', '--verify', '--quiet', rev + '^{commit}'], repo) is None:
        raise ValueError(f'unknown revision {rev!r} (tag the submitted version: git tag v1-submitted <sha>)')
    main = main or issues.find_main(project)
    index = section_index(main) if main else {}
    reg, reg_now, reg_changed = registry_changes(project, repo, rev)
    changed = [h for h in hunks(repo, rev) if h['path'] != reg]  # registry edits are reported as results instead
    for h in changed:
        h['section'] = section_at(index, h['path'], h['start'])
    rel = lambda p: os.path.relpath(Path(p).resolve(), project.resolve())

    md = [f'# Rebuttal draft: changes since `{rev}`', '',
          '<!-- Skeleton from the AgenTeX issue ledger. Write every Response yourself and cite only results that '
          'are in the paper or the results registry. Changes lists are for you; reword what you post. -->', '']
    if main:
        m = rel(main)
        md += ['Change-tracked PDF (latex-convert, section D; run in the project folder):', '',
               f'    latexdiff-vc --git --flatten -r {rev} {m}',
               f'    python3 {BUILD} {Path(m).with_suffix("")}-diff{rev}.tex', '']
    if reg_changed:
        md += [f'Results new or changed since {rev}: ' + '; '.join(
            f'`{k}` {old} → {new}' if old is not None else f'`{k}` = {new} (new)'
            for k, (old, new) in sorted(reg_changed.items())), '']

    by_reviewer = {}
    for i in points:
        by_reviewer.setdefault(i['source'].split(':', 1)[1], []).append(i)
    digest = []
    for name, pts in by_reviewer.items():
        block, linked_n = [], 0
        for i in pts:
            m = issues.ANCHOR.match(i['anchor'] or '')
            path = (project / m['file']).resolve() if i['anchor'] and m else None
            sec = section_at(index, path, int(m['line'])) if path and m['line'] else None
            linked = [h for h in changed if (h['section'] == sec if sec else path and h['path'] == path)]
            state = (i['verdict'] or 'no verdict') + (', fixed' if i['fixed'] else '')
            block += [f"### {i['id']} [{i['severity']}, {state}]", '', '> ' + i['text'], '',
                      'Response: <!-- AUTHOR: your argument here -->', '', 'Changes:']
            lines = [f"- {h['section'] or rel(h['path'])}: {rel(h['path'])}:{h['start']}-{h['end']}" for h in linked]
            if len(lines) > MAX_LINKS:
                lines = lines[:MAX_LINKS] + [f'- … and {len(lines) - MAX_LINKS} more hunks']
            for sha in i['commits']:
                log = git(['log', '-1', '--format=%h %s', sha], repo)
                lines.append(f"- commit {log.strip() if log else sha}")
            for k in dict.fromkeys(k for h in linked for line in h['added'] for k in RES_USE.findall(line)):
                if k in reg_changed:
                    old, new = reg_changed[k]
                    lines.append(f'- result `\\res{{{k}}}` = {new}' + (f' (was {old})' if old is not None else ' (new)'))
                else:
                    lines.append(f'- result `\\res{{{k}}}` = {reg_now.get(k, "?? not in the registry")}')
            linked_n += bool(lines)
            block += (lines or [f'- none since {rev}']) + ['']
            if i['notes']:
                block += ['<!-- ledger notes: ' + ' | '.join(i['notes']).replace('--', '-') + ' -->', '']
        n = posted_chars('\n'.join(block))
        count = f"{len(pts)} point{'s' * (len(pts) != 1)}"
        md += [f'## Reviewer {name} ({count}; {budget(n, limit)} before responses)', ''] + block
        digest.append(f'{name}: {count}, {linked_n} with linked changes; {budget(n, limit)} of quotes')
    return '\n'.join(md).rstrip() + '\n', digest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, default=Path('.'))
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('draft')
    d.add_argument('--since', required=True, help='git revision of the submitted version, e.g. a tag')
    d.add_argument('--out', type=Path, default=Path('rebuttal.md'))
    d.add_argument('--limit-chars', type=int, help='per-reviewer character limit of the venue (e.g. 5000)')
    d.add_argument('--main', type=Path, help='main .tex (default: found under --project)')
    d.add_argument('--force', action='store_true', help='overwrite --out (it may hold responses you wrote)')
    c = sub.add_parser('count')
    c.add_argument('file', type=Path)
    c.add_argument('--limit-chars', type=int)
    args = ap.parse_args(argv)

    if args.cmd == 'count':
        rows = [(name, posted_chars(block)) for name, block in reviewer_blocks(args.file.read_text(encoding='utf-8'))]
        for name, n in rows:
            print(f'{name}: {budget(n, args.limit_chars)}')
        return 1 if args.limit_chars and any(n > args.limit_chars for _, n in rows) else 0
    if args.out.exists() and not args.force:
        print(f'{args.out} exists and may hold your responses; use --force or another --out')
        return 2
    try:
        text, digest = draft(args.project, args.since, args.main, args.limit_chars)
    except ValueError as e:
        print(e)
        return 2
    args.out.write_text(text, encoding='utf-8')
    print(f'wrote {args.out}')
    print('\n'.join(digest))
    print('next: write each Response (no invented results), then `rebuttal.py count` against the venue limit')
    return 0


if __name__ == '__main__':
    sys.exit(main())
