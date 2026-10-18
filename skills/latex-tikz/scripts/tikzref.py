#!/usr/bin/env python3
"""Search 1,200+ official PGF/TikZ manual examples offline; print only the best few.

Usage:
  tikzref.py fit plate label            # top 3 examples matching all/most terms
  tikzref.py "matrix of math nodes" -n 5
  tikzref.py brace -l decorations       # restrict to pages whose name contains "decorations"
  tikzref.py --keys chains              # option/command signatures for a library
  tikzref.py --list                     # pages and counts

Results are short on purpose: shorter examples win ties, so the agent reads less.
Source: https://tikz.dev (PGF/TikZ manual, LPPL 1.3c; see ../reference/NOTICE.md).
"""
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'reference' / 'tikz-manual.jsonl'


def load():
    with INDEX.open(encoding='utf-8') as fh:
        return [json.loads(line) for line in fh]


def terms_of(query):
    return [t for t in re.split(r'[\s,]+', query.lower()) if t]


def score(rec, terms):
    """Fraction-of-terms gate, then term frequency, a bonus for title hits and a small length penalty."""
    body = (rec.get('c') or rec.get('k')).lower()
    head = (rec['p'] + ' ' + rec['s']).lower()
    hits = [t for t in terms if t in body or t in head]
    if len(hits) < max(1, math.ceil(0.6 * len(terms))):
        return 0.0
    s = sum(1 + min(body.count(t), 3) * 0.5 + (2 if t in head else 0) for t in hits)
    return s - len(body) / 1500


def search(records, query, n=3, lib=None, keys=False):
    terms = terms_of(query)
    pool = [r for r in records if ('k' in r) == keys and (not lib or lib in r['p'])]
    ranked = sorted(((score(r, terms), r) for r in pool), key=lambda x: -x[0])
    return [r for s, r in ranked if s > 0][:n]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('query', nargs='*')
    ap.add_argument('-n', type=int, default=3, help='number of results (default 3)')
    ap.add_argument('-l', '--lib', help='only pages whose name contains this, e.g. trees, shapes, graphs')
    ap.add_argument('--keys', metavar='LIB', help='list option/command signatures for a library page')
    ap.add_argument('--list', action='store_true', help='list indexed pages')
    args = ap.parse_args(argv)
    records = load()

    if args.list:
        for page, cnt in sorted(Counter(r['p'] for r in records if 'c' in r).items()):
            print(f'{page:24s} {cnt:4d} examples')
        return 0
    if args.keys:
        rows = [r for r in records if 'k' in r and args.keys in r['p']]
        if args.query:
            rows = search(rows, ' '.join(args.query), n=args.n, keys=True)
        for r in rows:
            print(f"{r['k']}    [{r['s']}]")
        return 0 if rows else 1
    if not args.query:
        ap.print_help()
        return 2

    hits = search(records, ' '.join(args.query), n=args.n, lib=args.lib)
    for r in hits:
        print(f"% --- {r['s']}  (https://tikz.dev/{r['p']})\n{r['c']}\n")
    if not hits:
        print('no match; try fewer or different terms, or --list', file=sys.stderr)
    return 0 if hits else 1


if __name__ == '__main__':
    sys.exit(main())
