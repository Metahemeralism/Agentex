#!/usr/bin/env python3
"""Print a compact map of a LaTeX project so an agent reads only the files it needs.

Usage: texmap.py [project_dir] [--budget 3000]
Shows: main file(s) and their \\input tree with line counts, section outline with labels and
file:line, labels by prefix, notation macros, TikZ styles, packages, bibliography usage,
figures (flags missing ones) and TODOs. Stdlib only; regex, not a TeX parser.
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

INPUT = re.compile(r'\\(?:input|include|subfile)\s*\{([^}]+)\}|\\(?:sub)?import\s*\{([^}]*)\}\s*\{([^}]+)\}')
SECTION = re.compile(r'\\(part|chapter|section|subsection)\*?\s*(?:\[[^\]]*\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}')
LABEL = re.compile(r'\\label\s*\{([^}]+)\}')
MACRO = re.compile(r'\\(?:(?:re)?newcommand\*?|DeclareMathOperator\*?|DeclarePairedDelimiter|providecommand\*?)\s*\{?\s*(\\[A-Za-z@]+)|\\def\s*(\\[A-Za-z@]+)')
PACKAGE = re.compile(r'\\usepackage\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
STYLE = re.compile(r'([A-Za-z][\w ]*?)/\.style')
CITE = re.compile(r'\\(?:[a-zA-Z]*cite[a-zA-Z]*|nocite)\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]+)\}')
BIB = re.compile(r'\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
GRAPHIC = re.compile(r'\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
TODO = re.compile(r'%\s*(TODO|FIXME|XXX)\b|\\todo\b', re.I)
GRAPHIC_EXT = ('', '.pdf', '.png', '.jpg', '.jpeg', '.eps')


def strip_comments(text):
    return re.sub(r'(?<!\\)%.*', '', text)


def resolve(base_dir, name, ext='.tex'):
    p = (base_dir / name.strip())
    return p if p.suffix else p.with_suffix(ext)


def walk(main, root):
    """Depth-first \\input tree from main: [(path, depth)]. Paths resolve against the project root
    like LaTeX does (relative to the main file's directory)."""
    order, seen = [], set()

    def visit(path, depth):
        if path in seen or not path.exists():
            return
        seen.add(path)
        order.append((path, depth))
        for m in INPUT.finditer(strip_comments(path.read_text(encoding='utf-8', errors='replace'))):
            if m[1]:
                visit(resolve(main.parent, m[1]), depth + 1)
            else:  # \import{dir}{file} resolves relative to the importing file
                visit(resolve(path.parent / m[2], m[3]), depth + 1)
    visit(main, 0)
    return order


def build_map(root, budget=3000):
    root = root.resolve()
    tex_files = sorted(p for p in root.rglob('*.tex') if '.git' not in p.parts)
    mains = [p for p in tex_files if re.search(r'^\s*\\documentclass', p.read_text(errors='replace'), re.M)
             and '\\begin{document}' in p.read_text(errors='replace')]
    standalone = [p for p in mains if re.search(r'\\documentclass\s*(\[[^\]]*\])?\s*\{standalone\}', p.read_text(errors='replace'))]
    mains = [p for p in mains if p not in standalone]
    rel = lambda p: str(p.relative_to(root))
    out = []
    if not mains and not standalone:
        return 'no main .tex file (\\documentclass + \\begin{document}) found under ' + str(root)

    for main in mains:
        tree = walk(main, root)
        texts = {p: strip_comments(p.read_text(encoding='utf-8', errors='replace')) for p, _ in tree}
        all_text = '\n'.join(texts.values())
        cls = re.search(r'\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}', all_text)
        total = sum(t.count('\n') + 1 for t in texts.values())
        out.append(f'{rel(main)}  [{cls[1] if cls else "?"}; {len(tree)} files, {total} lines]')
        out.append('  files: ' + '  '.join(f'{rel(p)}({texts[p].count(chr(10)) + 1})' for p, _ in tree[1:]))

        outline = []
        for p, _ in tree:
            t = texts[p]
            for m in SECTION.finditer(t):
                line = t.count('\n', 0, m.start()) + 1
                lab = LABEL.search(t, m.end(), m.end() + 200)
                indent = {'part': '', 'chapter': '', 'section': '', 'subsection': '  '}[m[1]]
                outline.append(f'  {indent}{m[2].strip()[:50]}' + (f' [{lab[1]}]' if lab else '') + f'  {rel(p)}:{line}')
        out.append('outline:')
        out += outline or ['  (no sections)']

        labels = defaultdict(list)
        for lab in LABEL.findall(all_text):
            prefix, _, name = lab.partition(':')
            labels[prefix if name else '(no prefix)'].append(name or lab)
        out.append(f'labels ({sum(map(len, labels.values()))}): ' +
                   ' | '.join(f'{k}: {", ".join(v)}' for k, v in sorted(labels.items())))

        macros = list(dict.fromkeys(a or b for a, b in MACRO.findall(all_text)))
        out.append(f'macros ({len(macros)}): ' + ' '.join(macros))
        styles = list(dict.fromkeys(s.strip() for s in STYLE.findall(all_text)))
        if styles:
            out.append('tikz styles: ' + ', '.join(styles))
        pkgs = list(dict.fromkeys(x.strip() for m in PACKAGE.findall(all_text) for x in m.split(',')))
        out.append('packages: ' + ' '.join(pkgs))

        cited = {k.strip() for m in CITE.findall(all_text) for k in m.split(',')}
        bibs = []
        for m in BIB.findall(all_text):
            for b in m.split(','):
                bp = resolve(main.parent, b, '.bib')
                n = len(re.findall(r'^\s*@(?!string|comment|preamble)\w+\s*\{', bp.read_text(errors='replace'), re.M | re.I)) if bp.exists() else 0
                bibs.append(f'{rel(bp) if bp.exists() else b + " (MISSING)"} {n} entries')
        out.append(f'bib: {"; ".join(bibs) or "none"}; {len(cited)} keys cited')

        graphics = GRAPHIC.findall(all_text)
        missing = [g for g in graphics if not any((main.parent / (g + e)).exists() for e in GRAPHIC_EXT)]
        out.append(f'figures: {len(graphics)} included' + (f' (MISSING: {", ".join(missing)})' if missing else ''))

        todos = [f'{rel(p)}:{i}' for p, _ in tree
                 for i, l in enumerate(p.read_text(errors='replace').splitlines(), 1) if TODO.search(l)]
        if todos:
            out.append(f'todos ({len(todos)}): ' + ', '.join(todos[:8]) + (' ...' if len(todos) > 8 else ''))
    if standalone:
        out.append(f'standalone figures ({len(standalone)}): ' + ' '.join(rel(p) for p in standalone))

    text, lines = '', []
    for line in out:  # enforce the budget line by line, never mid-line
        if len(text) + len(line) + 1 > budget:
            lines.append(f'... (truncated at {budget} chars; raise --budget)')
            break
        lines.append(line)
        text += line + '\n'
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project_dir', nargs='?', default='.', type=Path)
    ap.add_argument('--budget', type=int, default=3000, help='max characters to print (default 3000)')
    args = ap.parse_args(argv)
    print(build_map(args.project_dir, args.budget))
    return 0


if __name__ == '__main__':
    sys.exit(main())
