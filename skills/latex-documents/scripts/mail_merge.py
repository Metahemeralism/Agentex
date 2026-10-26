#!/usr/bin/env python3
"""Mail merge: one LaTeX file per record of a CSV or JSON data source.

Usage: mail_merge.py TEMPLATE.tex DATA.csv|DATA.json [-o OUTDIR] [--name '{{last}}-{{first}}'] [--check]

Template syntax (a Mustache subset, so no Jinja2 is needed):
  {{key}}               value, LaTeX-escaped (& % $ # _ { } ~ ^ \\ < > are made safe)
  {{{key}}}             value inserted raw (it is already LaTeX)
  {{a.b}}               nested JSON field
  {{#key}}...{{/key}}   list: repeat the block per item ({{.}} is a scalar item); otherwise show the
                        block only if the value is truthy (not '', 0, false, no, null, [])
  {{^key}}...{{/key}}   show the block only if the value is falsy or missing
JSON data is a list of objects, or {"records": [...]}. Every record is rendered and checked before
anything is written: an unknown {{key}} stops the merge and names the records that lack it.
Compile the results with latex-debug/scripts/build.py. Stdlib only.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

TAG = re.compile(r'\{\{\{\s*([\w.]+)\s*\}\}\}|\{\{\s*([#^/]?)\s*([\w.]+|\.)\s*\}\}')
ESCAPES = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_', '{': r'\{',
           '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}', '<': r'\textless{}', '>': r'\textgreater{}'}
FALSY = {'', '0', 'false', 'no', 'n', 'none', 'null'}


def tex_escape(value):
    return ''.join(ESCAPES.get(c, c) for c in str(value))


def parse(template):
    """Template -> tree of text, ('var'|'raw', key) and (kind, key, children) section nodes."""
    root = []
    stack = [(None, root)]
    pos = 0
    for m in TAG.finditer(template):
        stack[-1][1].append(template[pos:m.start()])
        pos = m.end()
        line = template.count('\n', 0, m.start()) + 1
        if m[1]:
            stack[-1][1].append(('raw', m[1]))
        elif m[2] in ('#', '^'):
            node = (m[2], m[3], [])
            stack[-1][1].append(node)
            stack.append((m[3], node[2]))
        elif m[2] == '/':
            if stack[-1][0] != m[3]:
                raise ValueError(f'line {line}: {{{{/{m[3]}}}}} closes {"{{#" + stack[-1][0] + "}}" if stack[-1][0] else "nothing"}')
            stack.pop()
        else:
            stack[-1][1].append(('var', m[3]))
    if len(stack) > 1:
        raise ValueError(f'unclosed {{{{#{stack[-1][0]}}}}}')
    root.append(template[pos:])
    return root


def lookup(ctx, key):
    """Innermost-first lookup through the context stack; raises KeyError if nowhere."""
    if key == '.':
        return ctx[-1]
    for scope in reversed(ctx):
        value = scope
        for part in key.split('.'):
            if not isinstance(value, dict) or part not in value:
                break
            value = value[part]
        else:
            return value
    raise KeyError(key)


def truthy(value):
    if isinstance(value, str):
        return value.strip().lower() not in FALSY
    return bool(value)


def render(nodes, ctx, missing):
    out = []
    for n in nodes:
        if isinstance(n, str):
            out.append(n)
            continue
        kind, key = n[0], n[1]
        try:
            value = lookup(ctx, key)
        except KeyError:
            if kind in ('var', 'raw'):
                missing.add(key)
            value = None  # a missing section key is simply falsy
        if kind in ('var', 'raw'):
            text = '' if value is None else value
            out.append(str(text) if kind == 'raw' else tex_escape(text))
        elif kind == '^':
            out.append('' if truthy(value) else render(n[2], ctx, missing))
        else:
            items = value if isinstance(value, list) else [value] if truthy(value) else []
            out += [render(n[2], ctx + [item], missing) for item in items]
    return ''.join(out)


def load_records(path):
    if path.suffix.lower() == '.json':
        data = json.loads(path.read_text(encoding='utf-8'))
        data = data.get('records', data) if isinstance(data, dict) else data
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError('JSON data must be a list of objects or {"records": [...]}')
        return data
    with open(path, newline='', encoding='utf-8-sig') as f:  # -sig: Excel writes a BOM
        return [{k.strip(): (v or '').strip() for k, v in row.items() if k} for row in csv.DictReader(f)]


def safe_name(text):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('._') or 'record'


def merge(template_text, records, stem, name_pattern=None):
    """-> ([(filename, tex)], errors). Nothing is written here."""
    tree = parse(template_text)
    name_tree = parse(name_pattern) if name_pattern else None
    files, errors, seen = [], [], set()
    for i, rec in enumerate(records, 1):
        missing = set()
        tex = render(tree, [rec], missing)
        if missing:
            errors.append(f'record {i}: no value for {", ".join(sorted(missing))}')
            continue
        name = safe_name(render(name_tree, [rec], set())) if name_tree else f'{stem}-{i:03d}'
        if name in seen:
            errors.append(f'record {i}: output name {name}.tex is already used; make --name unique')
            continue
        seen.add(name)
        files.append((name + '.tex', tex))
    return files, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('template', type=Path)
    ap.add_argument('data', type=Path)
    ap.add_argument('-o', '--outdir', type=Path, help='default: <template dir>/merged')
    ap.add_argument('--name', help="output name pattern, e.g. '{{last}}-{{first}}' (default <stem>-001)")
    ap.add_argument('--check', action='store_true', help='validate only; write nothing')
    args = ap.parse_args(argv)
    try:
        records = load_records(args.data)
        files, errors = merge(args.template.read_text(encoding='utf-8'), records, args.template.stem, args.name)
    except (OSError, ValueError) as e:
        print(f'error: {e}')
        return 2
    if errors:
        print(f'{len(errors)} of {len(records)} records cannot be merged; nothing written:')
        print('\n'.join('  ' + e for e in errors[:10]) + (f'\n  ... (+{len(errors) - 10})' if len(errors) > 10 else ''))
        return 1
    if args.check:
        print(f'OK: {len(files)} records merge cleanly')
        return 0
    outdir = args.outdir or args.template.parent / 'merged'
    outdir.mkdir(parents=True, exist_ok=True)
    for name, tex in files:
        (outdir / name).write_text(tex, encoding='utf-8')
    print(f'wrote {len(files)} files to {outdir}: ' + ' '.join(n for n, _ in files[:3]) + (' ...' if len(files) > 3 else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
