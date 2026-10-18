#!/usr/bin/env python3
"""Digest a LaTeX .log: first errors with context, then warnings grouped by kind.

Usage: texlog.py main.log [-n 5]
Logs are often thousands of lines; reading one whole wastes context. This prints ~20 lines.
Exit code 1 if the log contains errors.
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ERROR = re.compile(r'^(?:! (?P<bang>.+)|(?P<file>[^\s:]+\.(?:tex|sty|cls)):(?P<line>\d+): (?P<msg>.+))$')
CONTEXT_LINE = re.compile(r'^l\.(\d+) (.*)')
WARNINGS = [
    ('undefined reference', re.compile(r"Reference [`'](.+?)' on page")),
    ('undefined citation', re.compile(r"Citation [`'](.+?)' on page")),
    ('multiply-defined label', re.compile(r"Label [`'](.+?)' multiply defined")),
    ('overfull box', re.compile(r'^Overfull \\[hv]box \((\d+\.?\d*)pt too \w+\)(?:.*?lines? (\d+(?:--\d+)?))?')),
    ('missing character', re.compile(r'Missing character: There is no (.+?) in font')),
    ('font substitution', re.compile(r"Font shape [`'](.+?)' undefined")),
    ('rerun needed', re.compile(r'(Rerun to get|Label\(s\) may have changed)')),
    ('package warning', re.compile(r'^Package (\w+) Warning: (.+)')),
]
OVERFULL_MIN_PT = 1.0  # smaller overfulls are invisible in print


def digest(text, n=5):
    lines = text.splitlines()
    errors = []
    for i, line in enumerate(lines):
        m = ERROR.match(line)
        if not m:
            continue
        where = f"{m['file']}:{m['line']}" if m['file'] else ''
        msg = m['bang'] or m['msg']
        for nxt in lines[i + 1:i + 12]:  # TeX prints "l.<line> <source>" a few lines later
            c = CONTEXT_LINE.match(nxt)
            if c:
                where = where or f'line {c[1]}'
                msg += f'  <- near: {c[2].strip()[:60]}'
                break
        if (where, msg) not in errors:
            errors.append((where, msg))

    warns = defaultdict(list)
    for line in lines:
        for kind, rx in WARNINGS:
            m = rx.search(line)
            if not m:
                continue
            if kind == 'overfull box':
                if float(m[1]) < OVERFULL_MIN_PT:
                    break
                warns[kind].append(f'{m[1]}pt' + (f' @ lines {m[2]}' if m[2] else ''))
            elif kind == 'package warning':
                warns[kind].append(f'{m[1]}: {m[2][:70]}')
            else:
                warns[kind].append(m[1])
            break

    out = []
    if errors:
        out.append(f'ERRORS ({len(errors)}; fix the first, recompile, repeat):')
        out += [f'  {w or "?"}  {msg}' for w, msg in errors[:n]]
    for kind, items in warns.items():
        uniq = list(dict.fromkeys(items))
        shown = ', '.join(uniq[:n]) + (f', ... (+{len(uniq) - n})' if len(uniq) > n else '')
        out.append(f'{kind} ({len(items)}): {shown}')
    if not out:
        out.append('clean: no errors or notable warnings')
    return '\n'.join(out), bool(errors)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('log', type=Path)
    ap.add_argument('-n', type=int, default=5, help='max items per group')
    args = ap.parse_args(argv)
    report, has_errors = digest(args.log.read_text(encoding='utf-8', errors='replace'), args.n)
    print(report)
    return 1 if has_errors else 0


if __name__ == '__main__':
    sys.exit(main())
