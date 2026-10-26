#!/usr/bin/env python3
"""PDF chores with whatever is installed (qpdf, Ghostscript, pdftk, poppler), falling back to LaTeX.

  pdftool.py info FILE                                    pages, size, version, encryption, fonts
  pdftool.py preview FILE [--pages 1-3|all] [--dpi 80] [--max-px 2000] [-o DIR]   PNG pages to look at
  pdftool.py merge OUT IN [IN ...]                        concatenate
  pdftool.py pages IN SPEC -o OUT                         SPEC: 1-3,5  7-  odd  even  last:3  all
  pdftool.py compress IN -o OUT [--quality screen|ebook|printer]
  pdftool.py encrypt IN -o OUT --password PW [--owner PW] [--no-print] [--no-modify]   (AES-256)
  pdftool.py fields IN                                    fillable form fields, types, options
  pdftool.py fill IN VALUES.json -o OUT [--flatten]       fill a fillable form ({"field": "value"})
  pdftool.py overlay IN SPEC.json -o OUT                  write text onto any PDF (non-fillable forms)
  pdftool.py watermark IN TEXT -o OUT [--opacity 0.15]    diagonal text on every page

Overlay SPEC: [{"page": 1, "x": 72, "y": 700, "text": "Ada", "size": 10}] in PDF points from the
bottom-left corner, or "box": [x0, y0, x1, y1] instead of x/y to place text in a box and check it fits.
Or read positions off a `preview --dpi D` image: {"dpi": D, "items": [{"page": 1, "box": [left, top,
right, bottom], "text": "Ada"}]} in pixels from the top-left, exactly as measured on the PNG.
merge/pages/overlay/watermark fall back to LaTeX (pdfpages) when qpdf/poppler are missing; that copy
drops links and form fields. Never invent a password: ask the user for it. Stdlib only.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ESCAPES = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_', '{': r'\{',
           '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}', '<': r'\textless{}', '>': r'\textgreater{}'}
GS_QUALITY = ('screen', 'ebook', 'printer', 'prepress')
TIMEOUT = 300
PAGE_OBJ = re.compile(rb'/Type\s*/Page(?![s\w])')


def have(tool):
    return shutil.which(tool) is not None


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, **kw)


def tex_escape(s):
    return ''.join(ESCAPES.get(c, c) for c in str(s))


def kb(path):
    return f'{Path(path).stat().st_size / 1024:,.0f} KB'


# ------------------------------------------------------------------ pages

def page_count(pdf):
    if have('pdfinfo'):
        m = re.search(r'^Pages:\s+(\d+)', run(['pdfinfo', str(pdf)]).stdout, re.M)
        if m:
            return int(m[1])
    if have('qpdf'):
        out = run(['qpdf', '--show-npages', str(pdf)]).stdout.strip()
        if out.isdigit():
            return int(out)
    return count_page_objects(Path(pdf).read_bytes())


def count_page_objects(data):
    """Stdlib page count: /Type /Page objects, including those inside compressed object streams."""
    n = len(PAGE_OBJ.findall(data))
    for m in re.finditer(rb'stream\r?\n', data):
        try:
            n += len(PAGE_OBJ.findall(zlib.decompressobj().decompress(data[m.end():m.end() + (1 << 20)])))
        except zlib.error:
            pass  # not Flate (images, fonts): nothing to count
    return n


def parse_pages(spec, n):
    """'1-3,5' / '7-' / 'odd' / 'even' / 'last:3' / 'all' -> 1-based page numbers, in order given."""
    out = []
    for part in spec.replace(' ', '').split(','):
        if part in ('all', ''):
            out += range(1, n + 1)
        elif part in ('odd', 'even'):
            out += range(1 if part == 'odd' else 2, n + 1, 2)
        elif part.startswith('last:'):
            out += range(max(1, n - int(part[5:]) + 1), n + 1)
        elif '-' in part:
            a, b = part.split('-', 1)
            out += range(int(a), (int(b) if b else n) + 1)
        else:
            out.append(int(part))
    bad = [p for p in out if not 1 <= p <= n]
    if bad:
        raise ValueError(f'page {bad[0]} is outside 1-{n}')
    return out


def ranges(pages):
    """[1,2,3,5] -> '1-3,5' (compact form for qpdf and pdfpages)."""
    out, start = [], None
    for i, p in enumerate(pages):
        if start is None:
            start = p
        if i + 1 == len(pages) or pages[i + 1] != p + 1:
            out.append(str(start) if start == p else f'{start}-{p}')
            start = None
    return ','.join(out)


# ------------------------------------------------------------------ LaTeX fallback

def latex_compile(body, out, workdir_files=()):
    """Compile a pdfpages document whose body is `body`; copy the PDF to `out`."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        for i, f in enumerate(workdir_files):  # copy inputs in: TeX dislikes spaces and odd paths
            shutil.copy(f, d / f'in{i}.pdf')
        (d / 'job.tex').write_text('\\documentclass{article}\n\\usepackage{pdfpages}\n\\usepackage{graphicx}\n'
                                   '\\usepackage{xcolor}\n\\begin{document}\n' + body + '\n\\end{document}\n')
        if have('latexmk'):
            cmd = ['latexmk', '-pdf', '-interaction=nonstopmode', '-halt-on-error', 'job.tex']
        elif have('tectonic'):
            cmd = ['tectonic', 'job.tex']
        else:
            raise RuntimeError('needs qpdf or poppler (brew install qpdf poppler), or a TeX engine for the fallback')
        r = run(cmd, cwd=d)
        if not (d / 'job.pdf').exists():
            err = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(('!', 'error'))]
            raise RuntimeError('LaTeX fallback failed: ' + ('; '.join(err[:3]) or 'see output'))
        shutil.copy(d / 'job.pdf', out)


def includepdf(i, pages, picture=''):
    opts = f'pages={{{pages}}},fitpaper=true' + (f',picturecommand={{{picture}}}' if picture else '')
    return f'\\includepdf[{opts}]{{in{i}.pdf}}'


# ------------------------------------------------------------------ commands

def cmd_info(pdf):
    lines = []
    if have('pdfinfo'):
        keep = ('Title', 'Author', 'Producer', 'Pages', 'Encrypted', 'Page size', 'PDF version', 'Form', 'Tagged')
        lines += [l for l in run(['pdfinfo', str(pdf)]).stdout.splitlines() if l.split(':')[0] in keep]
    else:
        lines.append(f'Pages: {page_count(pdf)} (install poppler for metadata)')
    if have('pdffonts'):
        rows = run(['pdffonts', str(pdf)]).stdout.splitlines()[2:]
        unembedded = [r.split()[0] for r in rows if r.split() and len(r.split()) > 4 and r.split()[-5] == 'no']
        lines.append(f'Fonts: {len(rows)}' + (f'; NOT embedded: {", ".join(unembedded)}' if unembedded else ', all embedded'))
    lines.append(f'File size: {kb(pdf)}')
    return '\n'.join(lines)


def cmd_preview(pdf, spec, dpi, max_px, out_dir):
    if not have('pdftoppm'):
        raise RuntimeError('needs pdftoppm (brew install poppler / apt install poppler-utils)')
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = parse_pages(spec, page_count(pdf))
    size = ['-scale-to', str(max_px)] if max_px else ['-r', str(dpi)]
    made = []
    for p in pages:
        stem = out_dir / f'{pdf.stem}-p{p:03d}'
        run(['pdftoppm', '-png', *size, '-f', str(p), '-l', str(p), '-singlefile', str(pdf), str(stem)])
        made.append(f'{stem}.png')
    return f'{len(made)} previews: ' + ' '.join(made[:6]) + (' ...' if len(made) > 6 else '')


def cmd_merge(out, inputs):
    if have('qpdf'):
        r = run(['qpdf', '--empty', '--pages', *map(str, inputs), '--', str(out)])
    elif have('pdfunite'):
        r = run(['pdfunite', *map(str, inputs), str(out)])
    else:
        latex_compile('\n'.join(includepdf(i, '-') for i in range(len(inputs))), out, inputs)
        r = None
    if r is not None and r.returncode not in (0, 3):  # qpdf exits 3 on warnings only
        raise RuntimeError(r.stderr.strip()[:300])
    return f'OK {out} ({page_count(out)} pages, {kb(out)})'


def cmd_pages(pdf, spec, out):
    pages = parse_pages(spec, page_count(pdf))
    if have('qpdf'):
        r = run(['qpdf', '--empty', '--pages', str(pdf), ranges(pages), '--', str(out)])
        if r.returncode not in (0, 3):
            raise RuntimeError(r.stderr.strip()[:300])
    elif have('pdfseparate') and have('pdfunite'):
        with tempfile.TemporaryDirectory() as d:
            run(['pdfseparate', str(pdf), f'{d}/p%d.pdf'])
            r = run(['pdfunite', *[f'{d}/p{p}.pdf' for p in pages], str(out)])
            if r.returncode:
                raise RuntimeError(r.stderr.strip()[:300])
    else:
        latex_compile(includepdf(0, ranges(pages)), out, [pdf])
    return f'OK {out} ({len(pages)} pages: {ranges(pages)})'


def cmd_compress(pdf, out, quality):
    before = Path(pdf).stat().st_size
    if have('gs'):
        r = run(['gs', '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.6', f'-dPDFSETTINGS=/{quality}', '-dNOPAUSE',
                 '-dQUIET', '-dBATCH', f'-sOutputFile={out}', str(pdf)])
    elif have('qpdf'):  # lossless only: recompress streams, pack objects
        r = run(['qpdf', '--recompress-flate', '--compression-level=9', '--object-streams=generate', str(pdf), str(out)])
    else:
        raise RuntimeError('needs Ghostscript (lossy, images) or qpdf (lossless): brew install ghostscript qpdf')
    if r.returncode not in (0, 3) or not Path(out).exists():
        raise RuntimeError(r.stderr.strip()[:300])
    after = Path(out).stat().st_size
    note = '' if after < before else ' (no smaller: keep the original)'
    return f'OK {out}: {before / 1024:,.0f} KB -> {after / 1024:,.0f} KB ({100 * (before - after) / before:.0f}% smaller){note}'


def cmd_encrypt(pdf, out, password, owner, no_print, no_modify):
    if not password:
        raise RuntimeError('a password is required: ask the user for one, never invent it')
    owner = owner or password
    if have('qpdf'):
        cmd = ['qpdf', '--encrypt', password, owner, '256', *(['--print=none'] if no_print else []),
               *(['--modify=none'] if no_modify else []), '--', str(pdf), str(out)]
    elif have('pdftk'):
        allow = [] if no_print and no_modify else ['allow', *(['Printing'] if not no_print else []),
                                                   *(['ModifyContents'] if not no_modify else [])]
        cmd = ['pdftk', str(pdf), 'output', str(out), 'encrypt_128bit', 'user_pw', password, 'owner_pw', owner, *allow]
    else:
        raise RuntimeError('needs qpdf (brew install qpdf) or pdftk')
    r = run(cmd)
    if r.returncode not in (0, 3):
        raise RuntimeError(r.stderr.strip()[:300])
    return f'OK {out} encrypted ({"AES-256" if cmd[0] == "qpdf" else "128-bit"}); the user must keep the password'


def parse_pdftk_fields(text):
    """pdftk dump_data_fields_utf8 output -> [{name, type, value, options}]."""
    fields = []
    for block in text.split('---'):
        f = {'options': []}
        for line in block.strip().splitlines():
            k, _, v = line.partition(': ')
            if k == 'FieldName':
                f['name'] = v
            elif k == 'FieldType':
                f['type'] = v
            elif k == 'FieldValue':
                f['value'] = v
            elif k == 'FieldStateOption':
                f['options'].append(v)
        if 'name' in f:
            fields.append(f)
    return fields


def parse_qpdf_fields(data):
    """qpdf --json acroform section -> [{name, type, value, options, page}]."""
    out = []
    for f in data.get('acroform', {}).get('fields', []):
        kind = ('Checkbox' if f.get('ischeckbox') else 'Radio' if f.get('isradiobutton') else
                'Choice' if f.get('ischoice') else 'Text' if f.get('istext') else f.get('fieldtype', '?').lstrip('/'))
        value = f.get('value')
        out.append({'name': f.get('fullname'), 'type': kind, 'value': value if isinstance(value, str) else '',
                    'options': f.get('choices', []), 'page': f.get('pageposfrom1')})
    return out


def read_fields(pdf):
    if have('qpdf'):
        r = run(['qpdf', '--json', '--json-key=acroform', str(pdf)])
        if r.stdout.strip():
            return parse_qpdf_fields(json.loads(r.stdout))
    if have('pdftk'):
        return parse_pdftk_fields(run(['pdftk', str(pdf), 'dump_data_fields_utf8']).stdout)
    raise RuntimeError('needs qpdf or pdftk to read form fields (brew install qpdf pdftk-java)')


def cmd_fields(pdf):
    fields = read_fields(pdf)
    if not fields:
        return 'no fillable fields: this is a flat form, use `overlay` (see SKILL.md)'
    lines = [f'{len(fields)} fields (name | type | current value | options):']
    for f in fields:
        opts = f' | {"/".join(o for o in f["options"] if o)}' if f['options'] else ''
        page = f' (p{f["page"]})' if f.get('page') else ''
        lines.append(f'  {f["name"]} | {f["type"]}{page} | {f.get("value", "")!s}{opts}')
    return '\n'.join(lines)


def xfdf(values):
    rows = ''.join(f'<field name="{xml_escape(k, {chr(34): "&quot;"})}"><value>{xml_escape(str(v))}</value></field>'
                   for k, v in values.items())
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<xfdf xmlns="http://ns.adobe.com/xfdf/" xml:space="preserve"><fields>{rows}</fields></xfdf>\n'


def check_values(fields, values):
    """Unknown names and invalid checkbox/choice values, before anything is written."""
    by_name = {f['name']: f for f in fields}
    problems = [f'unknown field: {k}' for k in values if k not in by_name]
    for k, v in values.items():
        f = by_name.get(k)
        if f and f['options'] and f['type'] in ('Button', 'Checkbox', 'Radio', 'Choice') and str(v) not in f['options']:
            problems.append(f'{k}: {v!r} is not one of {f["options"]}')
    return problems


def cmd_fill(pdf, values_path, out, flatten):
    values = json.loads(Path(values_path).read_text(encoding='utf-8'))
    if not have('pdftk'):
        raise RuntimeError('filling fillable forms needs pdftk (brew install pdftk-java); '
                           'or flatten it yourself with `overlay` at the field positions')
    problems = check_values(read_fields(pdf), values)
    if problems:
        raise RuntimeError('nothing written:\n  ' + '\n  '.join(problems))
    with tempfile.NamedTemporaryFile('w', suffix='.xfdf', delete=False, encoding='utf-8') as f:
        f.write(xfdf(values))
    try:
        r = run(['pdftk', str(pdf), 'fill_form', f.name, 'output', str(out), *(['flatten'] if flatten else ['need_appearances'])])
    finally:
        Path(f.name).unlink()
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return f'OK {out}: {len(values)} fields filled' + (' and flattened' if flatten else '')


def check_overlay(items, n, scale=1.0):
    """Box sanity (their validate_boxes): page exists, text fits its box, boxes don't overlap.
    `scale` converts box units to points (72/dpi for preview pixels)."""
    problems, boxes = [], []
    for i, it in enumerate(items, 1):
        if not 1 <= it.get('page', 1) <= n:
            problems.append(f'item {i}: page {it.get("page")} outside 1-{n}')
        if 'box' in it:
            x0, y0, x1, y1 = it['box']
            if x1 <= x0 or y1 <= y0:
                problems.append(f'item {i}: box must be [left, low, right, high] with positive size')
            elif (y1 - y0) * scale < it.get('size', 10):
                problems.append(f'item {i}: box is {(y1 - y0) * scale:.3g}pt tall, text is {it.get("size", 10)}pt')
            for j, (p, b) in enumerate(boxes, 1):
                if p == it.get('page', 1) and x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1:
                    problems.append(f'item {i}: box overlaps item {j}')
            boxes.append((it.get('page', 1), (x0, y0, x1, y1)))
        elif 'x' not in it or 'y' not in it:
            problems.append(f'item {i}: needs x and y, or box')
    return problems


def overlay_put(it, dpi=None):
    """One \\put for pdfpages' picture (origin bottom-left, unit 1bp).
    With `dpi`, coordinates are preview pixels from the top-left: the box is [left, top, right, bottom]."""
    size = it.get('size', 10)
    text = f'\\fontsize{{{size}}}{{{size * 1.2:g}}}\\selectfont\\makebox[0pt][l]{{{tex_escape(it["text"])}}}'
    if dpi:
        s = 72 / dpi
        if 'box' in it:
            left, top, _, bottom = (v * s for v in it['box'])
            x, from_top = left + 2, bottom - max(1.5, (bottom - top - size) / 2)
        else:
            x, from_top = it['x'] * s, it['y'] * s
        # the page height is only known to TeX, so lift the text from the bottom edge
        return f'\\put({x:.2f},0){{\\raisebox{{\\dimexpr\\paperheight-{from_top:.2f}bp\\relax}}[0pt][0pt]{{{text}}}}}'
    if 'box' in it:  # baseline a little above the box bottom, so descenders stay inside
        x, y = it['box'][0] + 2, it['box'][1] + max(1.5, (it['box'][3] - it['box'][1] - size) / 2)
    else:
        x, y = it['x'], it['y']
    return f'\\put({x:g},{y:g}){{{text}}}'


def cmd_overlay(pdf, spec_path, out):
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    dpi = spec.get('dpi') if isinstance(spec, dict) else None
    items = spec.get('items', []) if isinstance(spec, dict) else spec
    n = page_count(pdf)
    problems = check_overlay(items, n, 72 / dpi if dpi else 1.0)
    if problems:
        raise RuntimeError('nothing written:\n  ' + '\n  '.join(problems))
    body = []
    for p in range(1, n + 1):
        puts = ''.join(overlay_put(it, dpi) for it in items if it.get('page', 1) == p)
        body.append(includepdf(0, str(p), '\\setlength{\\unitlength}{1bp}' + puts if puts else ''))
    latex_compile('\n'.join(body), out, [pdf])
    return f'OK {out}: {len(items)} text items on {len({it.get("page", 1) for it in items})} pages (flattened)'


def cmd_watermark(pdf, text, out, opacity):
    grey = max(0, min(100, round(opacity * 100)))
    picture = (r'\put(0,0){\parbox[b][\paperheight][c]{\paperwidth}{\centering\rotatebox{45}{'
               rf'\color{{black!{grey}}}\fontsize{{90}}{{90}}\selectfont\bfseries ' + tex_escape(text) + '}}}')
    latex_compile(includepdf(0, '-', picture), out, [pdf])
    return f'OK {out}: "{text}" on every page'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('info').add_argument('pdf', type=Path)
    p = sub.add_parser('preview')
    p.add_argument('pdf', type=Path)
    p.add_argument('--pages', default='1')
    p.add_argument('--dpi', type=int, default=80)
    p.add_argument('--max-px', type=int, help='longest side in pixels (e.g. 2000 for vision models); overrides --dpi')
    p.add_argument('-o', '--out', type=Path, default=Path('previews'))
    p = sub.add_parser('merge')
    p.add_argument('out', type=Path)
    p.add_argument('inputs', type=Path, nargs='+')
    p = sub.add_parser('pages')
    p.add_argument('pdf', type=Path)
    p.add_argument('spec')
    p.add_argument('-o', '--out', type=Path, required=True)
    p = sub.add_parser('compress')
    p.add_argument('pdf', type=Path)
    p.add_argument('-o', '--out', type=Path, required=True)
    p.add_argument('--quality', default='ebook', choices=GS_QUALITY)
    p = sub.add_parser('encrypt')
    p.add_argument('pdf', type=Path)
    p.add_argument('-o', '--out', type=Path, required=True)
    p.add_argument('--password', required=True, help='user password (ask the user; never invent one)')
    p.add_argument('--owner', help='owner password (default: same as --password)')
    p.add_argument('--no-print', action='store_true')
    p.add_argument('--no-modify', action='store_true')
    sub.add_parser('fields').add_argument('pdf', type=Path)
    p = sub.add_parser('fill')
    p.add_argument('pdf', type=Path)
    p.add_argument('values', type=Path)
    p.add_argument('-o', '--out', type=Path, required=True)
    p.add_argument('--flatten', action='store_true', help='bake values in so they can no longer be edited')
    p = sub.add_parser('overlay')
    p.add_argument('pdf', type=Path)
    p.add_argument('spec', type=Path)
    p.add_argument('-o', '--out', type=Path, required=True)
    p = sub.add_parser('watermark')
    p.add_argument('pdf', type=Path)
    p.add_argument('text')
    p.add_argument('-o', '--out', type=Path, required=True)
    p.add_argument('--opacity', type=float, default=0.15, help='grey level 0-1 (default 0.15)')
    a = ap.parse_args(argv)

    for f in [getattr(a, 'pdf', None), *getattr(a, 'inputs', [])]:
        if f is not None and not f.exists():
            print(f'not found: {f}')
            return 2
    out = getattr(a, 'out', None)
    if isinstance(out, Path) and a.cmd != 'preview' and out.resolve() in {p.resolve() for p in [getattr(a, 'pdf', None), *getattr(a, 'inputs', [])] if p}:
        print('refusing to overwrite an input: choose a different output path')
        return 2
    try:
        print({
            'info': lambda: cmd_info(a.pdf),
            'preview': lambda: cmd_preview(a.pdf, a.pages, a.dpi, a.max_px, a.out),
            'merge': lambda: cmd_merge(a.out, a.inputs),
            'pages': lambda: cmd_pages(a.pdf, a.spec, a.out),
            'compress': lambda: cmd_compress(a.pdf, a.out, a.quality),
            'encrypt': lambda: cmd_encrypt(a.pdf, a.out, a.password, a.owner, a.no_print, a.no_modify),
            'fields': lambda: cmd_fields(a.pdf),
            'fill': lambda: cmd_fill(a.pdf, a.values, a.out, a.flatten),
            'overlay': lambda: cmd_overlay(a.pdf, a.spec, a.out),
            'watermark': lambda: cmd_watermark(a.pdf, a.text, a.out, a.opacity),
        }[a.cmd]())
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as e:
        print(f'error: {e}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
