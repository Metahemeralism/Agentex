#!/usr/bin/env python3
"""Maintainer tool: rewrite reference/latexml-packages.txt from latexml-oxide's BINDINGS tables.

Usage: refresh_bindings.py [--ref main]

arXiv's HTML logs name latexml-oxide (a Rust port of LaTeXML) as the converter since 2026-08; its
tables cover every brucemiller/LaTeXML lib/LaTeXML/Package/*.ltxml binding plus arXiv-specific ones.
Needs network. Stdlib only.
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

REPO = 'dginev/latexml-oxide'
TABLES = ('latexml_package/src/lib.rs', 'latexml_contrib/src/lib.rs')
ENTRY = re.compile(r'\(\s*"([^"]+)",\s*"(sty|cls)"')  # ("tikz-cd", "sty", package::tikz_cd_sty::load_definitions)
OUT = Path(__file__).resolve().parent.parent / 'reference' / 'latexml-packages.txt'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'agentex-refresh-bindings'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8')


def snapshot(ref='main', fetch=get):
    commit = json.loads(fetch(f'https://api.github.com/repos/{REPO}/commits/{ref}'))
    sha, when = commit['sha'], commit['commit']['committer']['date'][:10]
    names = {f'{n}.{e}' for t in TABLES for n, e in ENTRY.findall(fetch(f'https://raw.githubusercontent.com/{REPO}/{sha}/{t}'))}
    if len(names) < 100:
        raise ValueError(f'only {len(names)} bindings parsed: the BINDINGS table format changed')
    head = ["# LaTeXML bindings (.sty/.cls) in arXiv's HTML converter, latexml-oxide. One per line; matching is case-insensitive.",
            f'# Source: https://github.com/{REPO}/blob/{sha}/{TABLES[0]} and {TABLES[1]} (BINDINGS tables);'
            f' commit {sha[:12]} of {when}, fetched {date.today()}.',
            '# Refresh: python3 refresh_bindings.py (latex-arxiv/scripts)']
    return '\n'.join(head + sorted(names, key=str.lower)) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ref', default='main', help='branch, tag or commit of latexml-oxide')
    args = ap.parse_args(argv)
    text = snapshot(args.ref)
    OUT.write_text(text, encoding='utf-8')
    print(f'wrote {OUT.name}: {text.count(chr(10)) - 3} bindings')
    return 0


if __name__ == '__main__':
    sys.exit(main())
