#!/usr/bin/env python3
"""Word count and element statistics for a LaTeX document, following its \\input tree.

Usage: texstats.py main.tex
Prints body words (prose only: no maths, commands, labels, citations, code or TikZ), abstract words,
and counts of sections, figures, tables, display equations, unique citations and footnotes; plus the
page count when main.pdf exists and pdfinfo is installed. For venue word limits that need an exact
count, cross-check with `texcount -inc -total main.tex`. Stdlib only.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from texmap import INPUT, resolve, strip_comments  # noqa: E402

DISPLAY_MATH_ENVS = r'(?:equation|align|gather|multline|eqnarray|flalign|alignat)\*?'
NON_PROSE_ENVS = r'(?:tikzpicture|tabular[x*]?|verbatim|lstlisting|minted|algorithmic|thebibliography|filecontents)\*?'
NO_TEXT_ARGS = re.compile(r'\\(?:label|[cC]?ref|eqref|autoref|pageref|[a-zA-Z]*cite[a-zA-Z]*|nocite|includegraphics|input|include|'
                          r'url|href|bibliography|bibliographystyle|addbibresource|vspace|hspace|begin|end|setlength|'
                          r'newcommand|renewcommand|usepackage|res|respct)\*?(?:\s*\[[^\]]*\])*\s*\{[^{}]*\}')
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")


def prose_words(tex):
    t = re.sub(r'\\begin\{(' + NON_PROSE_ENVS + r')\}.*?\\end\{\1\}', ' ', tex, flags=re.S)
    t = re.sub(r'\\begin\{(' + DISPLAY_MATH_ENVS + r')\}.*?\\end\{\1\}', ' ', t, flags=re.S)
    t = re.sub(r'\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\\)\$.*?(?<!\\)\$', ' ', t, flags=re.S)
    href = re.compile(r'\\href\s*\{[^{}]*\}')  # keep the link text, drop the URL
    t = NO_TEXT_ARGS.sub(' ', href.sub(' ', t))
    t = re.sub(r'\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?', ' ', t)  # remaining command names; their {text} stays
    t = re.sub(r'\\.', ' ', t).replace('~', ' ')
    return len(WORD.findall(t.replace('{', ' ').replace('}', ' ')))


def inline(path, base, seen=()):
    """The document with every \\input/\\include/\\import replaced by the file's text, in place."""
    text = strip_comments(path.read_text(encoding='utf-8', errors='replace'))
    if seen:  # an \\input standalone figure: keep only its body, as the standalone package does
        m = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', text, re.S)
        text = m[1] if m else text

    def expand(m):
        p = resolve(base, m[1]) if m[1] else resolve(path.parent / m[2], m[3])
        return inline(p, base, seen + (path,)) if p.exists() and p not in seen else ' '
    return INPUT.sub(expand, text)


def stats(main):
    tex = inline(main, main.parent)
    m = re.search(r'\\begin\{document\}(.*?)(?:\\end\{document\}|$)', tex, re.S)
    body = m[1] if m else tex
    abstract = re.search(r'\\begin\{abstract\}(.*?)\\end\{abstract\}', body, re.S)
    cites = {k.strip() for g in re.findall(r'\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}', body)
             for k in g.split(',') if k.strip()}
    out = {
        'words': prose_words(body),
        'abstract words': prose_words(abstract[1]) if abstract else None,
        'sections': len(re.findall(r'\\(?:chapter|section)\*?\s*[\[{]', body)),
        'figures': len(re.findall(r'\\begin\{figure\*?\}|\\begin\{tikzfigure\}', body)),
        'tables': len(re.findall(r'\\begin\{table\*?\}', body)),
        'equations': len(re.findall(r'\\begin\{' + DISPLAY_MATH_ENVS + r'\}|\\\[', body)),
        'citations': len(cites),
        'footnotes': len(re.findall(r'\\footnote\s*[\[{]', body)),
    }
    pdf = main.with_suffix('.pdf')
    if pdf.exists() and shutil.which('pdfinfo'):
        pages = re.search(r'^Pages:\s+(\d+)', subprocess.run(['pdfinfo', str(pdf)], capture_output=True, text=True).stdout, re.M)
        out['pages'] = int(pages[1]) if pages else None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tex', type=Path)
    args = ap.parse_args(argv)
    if not args.tex.exists():
        print(f'not found: {args.tex}')
        return 2
    s = stats(args.tex.resolve())
    print(f"~{s.pop('words'):,} words" + (f" (abstract {s.pop('abstract words')})" if s.get('abstract words') is not None else '')
          + ' · ' + ' · '.join(f'{v} {k}' for k, v in s.items() if v is not None and k != 'abstract words'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
