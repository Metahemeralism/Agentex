#!/usr/bin/env python3
"""Screen a LaTeX manuscript for text copied from given sources (word n-gram shingling).

Usage: overlap.py MANUSCRIPT SOURCE [SOURCE ...] [--n 8] [--threshold 0.5] [--min-run 12]
  MANUSCRIPT  a .tex file or a folder of .tex files (standalone figures are skipped)
  SOURCE      .txt/.md/.tex/.pdf files or folders (PDF needs `pdftotext` from poppler)

For each manuscript sentence: the share of its 8-word sequences found in a source, the longest
verbatim run, the source passage, and whether the sentence is cited and/or quoted.
This finds verbatim and near-verbatim reuse only; it is a screening aid, not a verdict.
Exit code 1 if any uncited, unquoted overlap is found.
"""
import argparse
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

CITE = re.compile(r'\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\s*\[[^\]]*\]){0,2}\s*\{[^}]*\}')
QUOTED = re.compile(r"``.+?''|\\enquote\{|\\textquote|\\begin\{quot")
MATH = re.compile(r'\$\$.*?\$\$|\$[^$]*\$|\\\[.*?\\\]|\\\(.*?\\\)', re.S)
DROP_ENVS = re.compile(r'\\begin\{(equation|align|gather|multline|figure|table|tikzpicture|algorithm|lstlisting|'
                       r'minted|verbatim)\*?\}.*?\\end\{\1\*?\}', re.S)
KEEP_ARG = re.compile(r'\\(?:emph|textbf|textit|textsc|texttt|underline|mbox|text)\s*\{([^{}]*)\}')
COMMAND = re.compile(r'\\[a-zA-Z@]+\*?(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})?')


def words(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())


def read_source(path):
    if path.suffix.lower() == '.pdf':
        if not shutil.which('pdftotext'):
            print(f'skip {path}: install poppler (pdftotext) to read PDFs', file=sys.stderr)
            return ''
        return subprocess.run(['pdftotext', '-q', str(path), '-'], capture_output=True, text=True).stdout
    text = path.read_text(encoding='utf-8', errors='replace')
    return latex_to_text(text) if path.suffix == '.tex' else text


def latex_to_text(text):
    """Rough LaTeX -> prose, preserving newlines so line numbers survive."""
    keep_lines = lambda m: '\n' * m.group(0).count('\n')
    text = re.sub(r'(?<!\\)%.*', '', text)
    text = DROP_ENVS.sub(keep_lines, text)
    text = MATH.sub(lambda m: ' ' + '\n' * m.group(0).count('\n'), text)
    for _ in range(3):
        text = KEEP_ARG.sub(r'\1', text)
    text = CITE.sub(' ', text)
    text = COMMAND.sub(' ', text)
    return re.sub(r'[{}~]', ' ', text)


def sentences(path):
    """Yield (line, sentence_text, cited, quoted) from a .tex file."""
    raw = re.sub(r'(?<!\\)%.*', '', path.read_text(encoding='utf-8', errors='replace'))
    plain = latex_to_text(raw)
    # Split both raw and plain at the same sentence boundaries by walking plain text with offsets.
    for m in re.finditer(r'[^.!?]+(?:[.!?]+|$)', plain):
        s = m.group(0)
        if len(words(s)) < 6:
            continue
        line = plain.count('\n', 0, m.start() + len(s) - len(s.lstrip())) + 1
        # shortcut: cite/quote detection is per source line, exact with one sentence per line;
        # sentences sharing a line with a cited one inherit its citation.
        raw_text = '\n'.join(raw.splitlines()[line - 1:line + s.strip().count('\n')])
        yield line, ' '.join(s.split()), bool(CITE.search(raw_text)), bool(QUOTED.search(raw_text))


def shingles(ws, n):
    return [' '.join(ws[i:i + n]) for i in range(len(ws) - n + 1)]


def build_index(sources, n):
    index = defaultdict(set)
    texts = {}
    for src in sources:
        ws = words(read_source(src))
        texts[src] = ws
        for i, sh in enumerate(shingles(ws, n)):
            index[sh].add((src, i))
    return index, texts


def manuscript_files(path):
    if path.is_file():
        return [path]
    return [p for p in sorted(path.rglob('*.tex'))
            if not re.search(r'\\documentclass\s*(\[[^\]]*\])?\s*\{standalone\}', p.read_text(errors='replace'))]


def check(manuscript, sources, n=8, threshold=0.5, min_run=12):
    index, texts = build_index(sources, n)
    findings, total = [], 0
    for f in manuscript_files(manuscript):
        for line, sent, cited, quoted in sentences(f):
            sh = shingles(words(sent), n)
            if not sh:
                continue
            total += 1
            hits = [index.get(s, set()) for s in sh]
            matched = [bool(h) for h in hits]
            share = sum(matched) / len(sh)
            run = best = 0
            for m in matched:
                run = run + 1 if m else 0
                best = max(best, run)
            run_words = best + n - 1 if best else 0
            if share < threshold and run_words < min_run:
                continue
            per_src = defaultdict(list)
            for h in hits:
                for src, i in h:
                    per_src[src].append(i)
            src, pos = max(per_src.items(), key=lambda kv: len(kv[1]))
            start = min(pos)
            snippet = ' '.join(texts[src][max(0, start - 3):start + len(sh) + n + 2])
            findings.append({'file': f, 'line': line, 'share': share, 'run': run_words, 'sentence': sent,
                             'source': src, 'snippet': snippet, 'cited': cited, 'quoted': quoted})
    return findings, total


def verdict(f):
    if f['quoted'] and f['cited']:
        return 'quoted + cited (ok if the quote is short and intended)'
    if f['cited']:
        return 'CITED BUT VERBATIM: quote it or paraphrase'
    return 'UNCITED OVERLAP: rewrite and/or cite'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('manuscript', type=Path)
    ap.add_argument('sources', nargs='+', type=Path)
    ap.add_argument('--n', type=int, default=8, help='shingle length in words (default 8)')
    ap.add_argument('--threshold', type=float, default=0.5, help='flag if this share of shingles match (default 0.5)')
    ap.add_argument('--min-run', type=int, default=12, help='or if this many consecutive words match (default 12)')
    args = ap.parse_args(argv)
    srcs = [p for s in args.sources for p in ([s] if s.is_file() else sorted(
        q for q in s.rglob('*') if q.suffix.lower() in ('.txt', '.md', '.tex', '.pdf')))]
    if not srcs:
        ap.error('no readable sources (.txt .md .tex .pdf)')

    findings, total = check(args.manuscript, srcs, args.n, args.threshold, args.min_run)
    root = args.manuscript if args.manuscript.is_dir() else args.manuscript.parent
    for f in findings:
        print(f"{f['file'].relative_to(root) if root in f['file'].parents else f['file'].name}:{f['line']}  "
              f"{f['share']:.0%} match, {f['run']}-word run  [{verdict(f)}]\n"
              f"  yours : {f['sentence'][:160]}\n  source: {f['source'].name}: ...{f['snippet'][:160]}...")
    uncited = sum(1 for f in findings if not f['cited'])
    print(f"\n{len(findings)} of {total} sentences overlap a source ({uncited} uncited); "
          f"checked against {len(srcs)} source file(s).")
    return 1 if uncited else 0


if __name__ == '__main__':
    sys.exit(main())
