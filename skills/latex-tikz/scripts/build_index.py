#!/usr/bin/env python3
"""Rebuild reference/tikz-manual.jsonl from the HTML PGF/TikZ manual at https://tikz.dev.

Maintainer tool, not needed at runtime. Usage: python3 build_index.py [--cache DIR]
Each output line is one record: {"p": page, "s": section, "c": example code} or
{"p": page, "s": section, "k": key/command signature}. Content is LPPL 1.3c, see reference/NOTICE.md.
"""
import argparse
import html
import json
import re
import time
import urllib.request
from pathlib import Path

PAGES = """library-3d library-angle library-automata library-backgrounds library-chains library-circuits
library-decorations library-er library-external library-fit library-fpu library-math library-matrix
library-mindmaps library-patterns library-perspective library-petri library-plot-handlers library-plot-marks
library-shapes library-spy library-edges library-through library-trees library-views tikz-graphs
tikz-matrices tikz-shapes tikz-pics tikz-trees tikz-paths tikz-actions tikz-arrows tikz-scopes
tikz-transformations tikz-coordinates tikz-design""".split()

ITEM = re.compile(r'<h[2-5][^>]*>(?P<h>.*?)</h[2-5]>|<div class="example-code">(?P<c>.*?)</div>'
                  r'|<(?:dt|div) class="entryheadline">(?P<k>.*?)</(?:dt|div)>', re.S)


def plain(fragment):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', fragment))).replace('¶', '').strip()


def code(fragment):
    s = re.sub(r'<button[^>]*>.*?</button>|<!--.*?-->', '', fragment, flags=re.S)
    s = re.sub(r'<br\s*/?>\s*', '\x00', s)       # the only real line breaks
    s = re.sub(r'\s*\n\s*', ' ', s)               # prettier-wrapped HTML: newline == one space
    s = re.sub(r'<[^>]+>', '', s).replace('\x00', '\n')
    return html.unescape(s).replace('\xa0', ' ').strip()


def records(page, text):
    section = ''
    for m in ITEM.finditer(text):
        if m['h'] is not None:
            section = plain(m['h'])
        elif m['c'] is not None:
            yield {'p': page, 's': section, 'c': code(m['c'])}
        else:
            yield {'p': page, 's': section, 'k': plain(m['k'])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', type=Path, default=Path('.tikzdev-cache'))
    args = ap.parse_args()
    args.cache.mkdir(exist_ok=True)
    out = Path(__file__).resolve().parent.parent / 'reference' / 'tikz-manual.jsonl'
    seen, n = set(), 0
    with out.open('w', encoding='utf-8') as fh:
        for page in PAGES:
            f = args.cache / f'{page}.html'
            if not f.exists():
                f.write_bytes(urllib.request.urlopen(f'https://tikz.dev/{page}', timeout=30).read())
                time.sleep(0.5)  # be polite to a volunteer-run site
            for r in records(page, f.read_text(encoding='utf-8', errors='replace')):
                key = r.get('c') or r['p'] + r['k']
                if key in seen:
                    continue
                seen.add(key)
                fh.write(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n')
                n += 1
    print(f'{n} records -> {out}')


if __name__ == '__main__':
    main()
