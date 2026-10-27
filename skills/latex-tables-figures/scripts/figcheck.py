#!/usr/bin/env python3
"""Check every \\includegraphics as it will sit in the page: rendered width, scale, text size, fonts, DPI, alt.

Usage: figcheck.py main.tex [--min-pt 6] [--no-compile]
  Layout (\\textwidth, \\columnwidth, body font size) is measured by compiling only the preamble of a scratch
  copy (a wrapper stops TeX at \\begin{document}) and cached in .agentex/layout.json by preamble hash.
  --no-compile uses the cache only; widths given relative to \\linewidth etc. are then 'unmeasured'.
  \\linewidth follows the environment: figure* spans \\textwidth, figure a column, minipage/subfigure their width.
  Text size in PDF figures is read from the content stream (font size x text and graphics matrices), so it is
  exact for matplotlib, TeX and R output; text inside a Form XObject ignores that XObject's own matrix.
  Writes .agentex/status/figures.json. Exit 1 if a figure is missing or has non-embedded fonts.
Stdlib + poppler (pdfinfo, pdffonts); a TeX engine (latexmk or tectonic) to measure the layout.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import zlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent
for _d in ('latex-project', 'latex-debug', 'latex-results-sync'):
    sys.path.insert(0, str(SKILLS / _d / 'scripts'))
from texmap import strip_comments, walk  # noqa: E402
from build import compile_cmd  # noqa: E402
from results import agentex_dir  # noqa: E402

INCLUDE = re.compile(r'\\includegraphics\s*\*?\s*(?:\[((?:[^\[\]{}]|\{[^{}]*\})*)\])?\s*\{([^}]+)\}')
ENV = re.compile(r'\\(begin|end)\s*\{([^}]+)\}')
GROUP = re.compile(r'\s*(?:\[[^\]]*\]|\{((?:[^{}]|\{[^{}]*\})*)\})')
GRAPHICSPATH = re.compile(r'\\graphicspath\s*\{((?:\s*\{[^{}]*\})+)\s*\}')
BOXED = re.compile(r'\\(?:resizebox|scalebox|adjustbox)\b')
DIM = re.compile(r'^\s*([-+]?(?:\d+\.?\d*|\.\d+)?)\s*(\\[a-z]+|pt|bp|in|cm|mm|pc|dd|cc|sp|em|ex)\s*$')
PT_PER = {'pt': 1, 'bp': 72.27 / 72, 'in': 72.27, 'cm': 72.27 / 2.54, 'mm': 72.27 / 25.4, 'pc': 12,
          'dd': 1238 / 1157, 'cc': 12 * 1238 / 1157, 'sp': 1 / 65536}
WIDTH_ARG = {'minipage': 0, 'subfigure': 0, 'subtable': 0, 'wrapfigure': 1, 'wraptable': 1}  # which {} is the width
EXTS = ('.pdf', '.png', '.jpg', '.jpeg', '.eps')
TEX_EXT = {'.tex', '.sty', '.cls', '.clo', '.cfg', '.def', '.fd', '.ldf', '.otf', '.ttf'}
TF = re.compile(rb'/[^\s/]+\s+[-+]?[\d.]+\s+Tf')
TOKEN = re.compile(rb'\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>|/[^\s/\[\]()<>{}%]*|[-+]?(?:\d+\.?\d*|\.\d+)'
                   rb'|[A-Za-z\'"][A-Za-z0-9*]*', re.S)
NUM = re.compile(rb'[-+]?(?:\d+\.?\d*|\.\d+)$')
MIN_DPI, LOUD = 300, 1.3  # LOUD: median figure text this many times the body size looks shouted
TIMEOUT = 120
WRAPPER = r"""\makeatletter
\def\agx@say#1#2{\typeout{AGX #1=#2}}
\def\agx@report{\agx@say{textwidth}{\the\textwidth}\agx@say{columnwidth}{\the\columnwidth}%
\agx@say{textheight}{\the\textheight}{\normalsize\agx@say{normalsize}{\f@size}}%
{\small\agx@say{small}{\f@size}}{\footnotesize\agx@say{footnotesize}{\f@size}}\@@end}
\ifdefined\AddToHook\AddToHook{begindocument/end}{\agx@report}\else\AtBeginDocument{\agx@report}\fi
\makeatother
\input{@MAIN@}
"""


# ------------------------------------------------------------------ layout

def preamble_key(main):
    """Hash of everything that sets the page layout: the preamble, files it \\inputs, local .cls/.sty."""
    pre = main.read_text(encoding='utf-8', errors='replace').split('\\begin{document}')[0]
    parts = [pre]
    for name in re.findall(r'\\input\s*\{([^}]+)\}', strip_comments(pre)):
        p = main.parent / (name if name.endswith('.tex') else name + '.tex')
        parts.append(p.read_text(encoding='utf-8', errors='replace') if p.exists() else name)
    parts += [p.read_text(encoding='utf-8', errors='replace')
              for ext in ('*.cls', '*.sty') for p in sorted(main.parent.glob(ext))]
    return hashlib.sha256('\0'.join(parts).encode()).hexdigest()[:16]


def compile_layout(main):
    """Compile the preamble of a scratch copy; -> (layout dict or None, note)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for dirpath, dirs, files in os.walk(main.parent):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__')]
            for f in files:
                src = Path(dirpath) / f
                if src.suffix.lower() in TEX_EXT:
                    dst = tmp / src.relative_to(main.parent)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        wrapper = tmp / '_agx_layout.tex'
        wrapper.write_text(WRAPPER.replace('@MAIN@', main.name))
        cmd = compile_cmd(wrapper)
        if cmd is None:
            return None, 'unmeasured: no latexmk/tectonic'
        try:
            r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return None, f'unmeasured: {cmd[0]} timed out'
        log = tmp / '_agx_layout.log'
        text = (log.read_text(errors='replace') if log.exists() else '') + r.stdout + r.stderr
    layout = {k: float(v) for k, v in re.findall(r'^AGX (\w+)=([\d.]+)', text, re.M)}
    if 'textwidth' not in layout:
        err = re.search(r'^! .*', text, re.M)
        return None, 'unmeasured: preamble did not compile' + (f' ({err[0][:60]})' if err else '')
    return layout, f'measured with {cmd[0]}'


def measure(main, compile_=True):
    """Layout from .agentex/layout.json, else compiled and cached. -> (layout or None, note)."""
    cache_path = agentex_dir(main.parent) / 'layout.json'
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    key = preamble_key(main)
    if key in cache:
        return cache[key], 'cached'
    if not compile_:
        return None, 'unmeasured: no cached layout (run without --no-compile)'
    layout, note = compile_layout(main)
    if layout:
        cache[key] = layout
        cache_path.write_text(json.dumps(dict(list(cache.items())[-8:]), indent=1))  # old preambles age out
    return layout, note


def dim(expr, layout, linewidth):
    """'0.5\\linewidth', '\\columnwidth', '3.4in', '8cm' -> TeX pt, or None when it can't be resolved."""
    m = DIM.match(expr or '')
    if not m:
        return None
    factor = float(m[1]) if m[1] and m[1] not in '+-' else -1.0 if m[1] == '-' else 1.0
    body = layout.get('normalsize')
    base = {'\\linewidth': linewidth, '\\hsize': linewidth, '\\columnwidth': layout.get('columnwidth'),
            '\\textwidth': layout.get('textwidth'), '\\textheight': layout.get('textheight'),
            'em': body, 'ex': body and 0.43 * body}.get(m[2], PT_PER.get(m[2]))  # ex: cmr10 x-height
    return factor * base if base else None


# ------------------------------------------------------------------ the source

def nth_arg(text, pos, n):
    """The n-th {...} argument after pos, skipping [...] optionals (e.g. minipage's width)."""
    while (m := GROUP.match(text, pos)):
        pos = m.end()
        if m[1] is not None:
            if n == 0:
                return m[1]
            n -= 1
    return None


def context(text, pos):
    """Environments open at pos, outermost first: [(name, width argument or None)]."""
    stack = []
    for m in ENV.finditer(text, 0, pos):
        name = m[2].strip()
        if m[1] == 'begin':
            stack.append((name, nth_arg(text, m.end(), WIDTH_ARG[name]) if name in WIDTH_ARG else None))
        elif any(n == name for n, _ in stack):
            while stack.pop()[0] != name:
                pass
    return stack


def line_width(stack, layout):
    """\\linewidth at an include. shortcut: the stack is per file, so a figure* that \\inputs the file
    holding the \\includegraphics reads as a column; lists (itemize, quote) narrowing it are ignored."""
    lw = layout.get('columnwidth')
    for name, arg in stack:
        if name in ('figure*', 'table*'):
            lw = layout.get('textwidth')
        if arg is not None:
            lw = dim(arg, layout, lw)
    return lw


def keyvals(opts):
    out = {}
    for part in re.findall(r'(?:[^,{}]|\{[^{}]*\})+', opts):
        k, _, v = part.partition('=')
        if k.strip():
            out[k.strip()] = v.strip().strip('{}').strip() if v else 'true'
    return out


def includes(main):
    """[dict(path, line, name, opts, stack, boxed)] for each \\includegraphics in the \\input tree."""
    found, gdirs = [], []
    for path, _ in walk(main, main.parent):
        text = strip_comments(path.read_text(encoding='utf-8', errors='replace'))
        for g in GRAPHICSPATH.findall(text):
            gdirs += re.findall(r'\{([^{}]*)\}', g)
        for m in INCLUDE.finditer(text):
            if '#' in m[2]:  # inside a macro definition: checked where the macro is used, if at all
                continue
            found.append({'path': path, 'line': text.count('\n', 0, m.start()) + 1, 'name': m[2].strip(),
                          'opts': keyvals(m[1] or ''), 'stack': context(text, m.start()),
                          'boxed': bool(BOXED.search(text, max(0, m.start() - 120), m.start()))})
    return found, gdirs


def find_file(name, base, gdirs):
    for d in ('', *gdirs):
        p = base / d / name
        for ext in ('',) if p.suffix.lower() in EXTS else EXTS:
            q = p.with_name(p.name + ext)
            if q.is_file():
                return q
    return None


# ------------------------------------------------------------------ the files

def png_info(data):
    """-> (width px, height px, dpi or None, software, compressed/raw size ratio)."""
    w, h, depth, ctype = struct.unpack('>IIBB', data[16:26])
    dpi, software, pos = None, '', 8
    while pos + 8 <= len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b'pHYs' and n == 9 and body[8] == 1:  # unit 1 = pixels per metre
            dpi = struct.unpack('>I', body[:4])[0] * 0.0254
        elif kind == b'tEXt' and body.startswith(b'Software\0'):
            software = body[9:].decode('latin-1')
        elif kind in (b'IDAT', b'IEND'):
            break
        pos += 12 + n
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype, 4)
    return w, h, dpi, software, len(data) / max(1, w * h * channels * depth / 8)


def jpeg_info(data):
    """-> (width px, height px, dpi or None) from the JFIF density and SOF markers."""
    pos, dpi = 2, None
    while pos + 9 <= len(data) and data[pos] == 0xFF:
        marker, n = data[pos + 1], struct.unpack('>H', data[pos + 2:pos + 4])[0]
        if marker == 0xE0 and data[pos + 4:pos + 9] == b'JFIF\0':
            units, xd = data[pos + 11], struct.unpack('>H', data[pos + 12:pos + 14])[0]
            dpi = xd if units == 1 else xd * 2.54 if units == 2 else None
        elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack('>HH', data[pos + 5:pos + 9])
            return w, h, dpi
        pos += 2 + n
    return None


def pdf_page_size(path):
    """Page size in bp from pdfinfo (crop box, as graphicx uses), or None."""
    if not shutil.which('pdfinfo'):
        return None
    out = subprocess.run(['pdfinfo', str(path)], capture_output=True, text=True, timeout=TIMEOUT).stdout
    m = re.search(r'^Page size:\s+([\d.]+) x ([\d.]+) pts', out, re.M)
    return (float(m[1]), float(m[2])) if m else None


def pdf_fonts(path):
    """[(name, type, embedded)] from pdffonts, or None without poppler."""
    if not shutil.which('pdffonts'):
        return None
    out = subprocess.run(['pdffonts', str(path)], capture_output=True, text=True, timeout=TIMEOUT).stdout
    return parse_pdffonts(out)


def parse_pdffonts(out):
    rows = []
    for line in out.splitlines()[2:]:
        t = line.split()
        if len(t) >= 8:  # name type... encoding emb sub uni num gen; the type may contain spaces
            rows.append((t[0], ' '.join(t[1:-6]), t[-5] == 'yes'))
    return rows


def scale_of(a, b, c, d):
    return abs(a * d - b * c) ** 0.5


def stream_text_sizes(body):
    """Font size (bp) of each text-showing operator: Tf size x text-matrix scale x CTM scale.
    shortcut: unescaped nested parentheses in strings and inline images can confuse the tokenizer."""
    ctm, saved, tm, tf, nums, sizes = 1.0, [], 1.0, None, [], []
    for t in TOKEN.findall(body):
        if NUM.match(t):
            nums.append(float(t))
            continue
        if t[:1] in b'(</':
            continue
        if t == b'q':
            saved.append(ctm)
        elif t == b'Q':
            ctm = saved.pop() if saved else 1.0
        elif t == b'cm' and len(nums) >= 6:
            ctm *= scale_of(*nums[-6:-2])
        elif t == b'BT':
            tm = 1.0
        elif t == b'Tm' and len(nums) >= 6:
            tm = scale_of(*nums[-6:-2])
        elif t == b'Tf' and nums:
            tf = abs(nums[-1])
        elif t in (b'Tj', b'TJ', b"'", b'"') and tf:
            sizes.append(round(tf * tm * ctm, 2))
        nums = []
    return sizes


def text_sizes(data):
    """Font sizes (bp) of all text in a PDF, from every content stream that sets a font."""
    sizes = []
    for m in re.finditer(rb'(?<!end)stream\r?\n', data):
        end = data.find(b'endstream', m.end())
        body = data[m.end():end if end > 0 else None]
        try:
            body = zlib.decompressobj().decompress(body)
        except zlib.error:  # not Flate: an uncompressed stream (kept as is) or one we can't read
            pass
        if TF.search(body):
            sizes += stream_text_sizes(body)
    return sizes


# ------------------------------------------------------------------ the check

def check_one(inc, layout, min_pt, gdirs, root):
    """-> row dict with problems [(level, code, message)]."""
    row = {'name': inc['name'], 'where': f"{os.path.relpath(inc['path'], root)}:{inc['line']}",
           'width': None, 'scale': None, 'text': None, 'problems': []}
    say = lambda level, code, msg: row['problems'].append((level, code, msg))  # noqa: E731
    if '\\' in inc['name']:
        say('warn', 'unchecked', 'file name uses a macro: not checked')
        return row
    path = find_file(inc['name'], root, gdirs)
    if not path:
        say('fail', 'missing', 'file not found')
        return row
    row['name'] = os.path.relpath(path, root)
    data, kind = path.read_bytes(), path.suffix.lower()
    px = dpi = None
    if kind == '.pdf':
        size = pdf_page_size(path)
        nat = size and (size[0] * 72.27 / 72, size[1] * 72.27 / 72)
        if not size:
            say('warn', 'unchecked', 'page size unknown (install poppler)')
    elif kind == '.png' and data[:8] == b'\x89PNG\r\n\x1a\n':
        w, h, dpi, software, ratio = png_info(data)
        px, nat = w, (w / (dpi or 72) * 72.27, h / (dpi or 72) * 72.27)  # graphicx: 72 dpi when none is stored
        if 'matplotlib' in software.lower() or ratio < 0.08:  # flat colours compress far better than photos
            say('warn', 'raster_plot', 'looks like a plot saved as PNG: save it as PDF (vector)')
    elif kind in ('.jpg', '.jpeg') and (info := jpeg_info(data)):
        w, h, dpi = info
        px, nat = w, (w / (dpi or 72) * 72.27, h / (dpi or 72) * 72.27)
    else:
        say('warn', 'unchecked', f'{kind or "no extension"}: size not checked')
        nat = None

    opts, lw = inc['opts'], line_width(inc['stack'], layout)
    sx = sy = None
    if inc['boxed']:
        say('warn', 'unchecked', 'inside \\resizebox/\\scalebox: scale not checked')
    elif nat:
        w = dim(opts['width'], layout, lw) if 'width' in opts else None
        hkey = 'height' if 'height' in opts else 'totalheight' if 'totalheight' in opts else None
        h = dim(opts[hkey], layout, lw) if hkey else None
        bad = [f"{k}={opts[k]}" for k, v in (('width', w), (hkey, h)) if k in opts and v is None]
        if bad:
            say('warn', 'unresolved', f"can't resolve {', '.join(bad)}" + ('' if layout else ' (layout unmeasured)'))
        else:
            sx, sy = (w / nat[0] if w else None), (h / nat[1] if h else None)
            if sx and sy and 'keepaspectratio' in opts:
                sx = sy = min(sx, sy)
            elif sx and sy and abs(sx / sy - 1) > 0.02:
                say('warn', 'distorted', 'width and height without keepaspectratio: distorted')
            sx, sy = sx or sy or 1.0, sy or sx or 1.0
            try:
                s = float(opts.get('scale', 1))
            except ValueError:
                s = 1.0
            sx, sy = sx * s, sy * s
            row['width'], row['scale'] = nat[0] * sx, sx

    if px and row['width']:
        eff = px / (row['width'] / 72.27)
        if eff < MIN_DPI:
            say('warn', 'low_dpi', f'{eff:.0f} dpi at this size (< {MIN_DPI}): export at least '
                f'{row["width"] / 72.27 * MIN_DPI:.0f} px wide, or as vector')
    if kind == '.pdf':
        fonts = pdf_fonts(path)
        if fonts is None:
            say('warn', 'unchecked', 'fonts not checked (install poppler)')
        else:
            loose = sorted({n for n, _, emb in fonts if not emb})
            if loose:
                say('fail', 'unembedded', f'fonts not embedded ({", ".join(loose)[:40]}): '
                    'matplotlib pdf.fonttype: 42, or re-export with fonts embedded')
            if any(t == 'Type 3' for _, t, _ in fonts):
                say('warn', 'type3', 'Type 3 fonts (IEEE PDF eXpress rejects them): matplotlib pdf.fonttype: 42')
        sizes = text_sizes(data)
        if sizes and sy:
            low, mid = min(sizes) * sy, statistics.median(sizes) * sy
            row['text'] = low
            body = layout.get('normalsize')
            redo = (f"plot at {row['width'] / 72.27:.2f}in wide (mplstyle.py) so it is not scaled"
                    if row['width'] and abs(sy - 1) > 0.1 else 'raise the font size in the plot')
            if low < min_pt:
                say('warn', 'small_text', f'text down to {low:.1f}pt (< {min_pt:g}): {redo}')
            if body and mid > LOUD * body:
                say('warn', 'large_text', f'text ~{mid:.0f}pt vs body {body:g}pt: {redo}')
    return row


def write_status(root, status, summary, counts, items):
    d = agentex_dir(root) / 'status'
    d.mkdir(exist_ok=True)
    doc = {'tool': 'figures', 'status': status, 'summary': summary[:100], 'counts': counts, 'items': items[:20],
           'updated': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    tmp = d / 'figures.json.tmp'
    tmp.write_text(json.dumps(doc, indent=1))
    os.replace(tmp, d / 'figures.json')
    return d / 'figures.json'


def check(main, min_pt=6.0, compile_=True):
    """-> (exit code, report lines)."""
    root = main.parent
    layout, note = measure(main, compile_)
    layout = layout or {}
    incs, gdirs = includes(main)
    rows = [check_one(inc, layout, min_pt, gdirs, root) for inc in incs]
    no_alt = sum('alt' not in inc['opts'] for inc in incs)

    if layout:
        cols = 'twocolumn' if layout['columnwidth'] < layout['textwidth'] - 1 else 'onecolumn'
        lay = (f"textwidth {layout['textwidth']:g}pt, columnwidth {layout['columnwidth']:g}pt, "
               f"body {layout.get('normalsize', 0):g}pt ({cols}, {note})")
    else:
        lay = note
    bad = [r for r in rows if r['problems']]
    out = [f'figcheck {main.name}: {len(rows)} figures, {len(bad)} with problems | {lay}']
    if rows:
        out.append(f"{'figure':24} {'where':18} {'width':>6} {'scale':>5} {'text':>6}  problems")
    pt = lambda v, fmt: fmt.format(v) if v is not None else '-'  # noqa: E731
    for r in rows:
        probs = ' | '.join(m for _, _, m in r['problems']) or 'ok'
        out.append(f"{r['name'][-24:]:24} {r['where'][-18:]:18} {pt(r['width'], '{:.0f}pt'):>6} "
                   f"{pt(r['scale'], '{:.2f}'):>5} {pt(r['text'], '{:.1f}pt'):>6}  {probs}")
    if no_alt:
        out.append(f'alt text: {no_alt}/{len(rows)} figures lack alt= (\\includegraphics[alt={{...}}]{{...}}; '
                   'arXiv recommends it for accessibility)')

    levels = [lvl for r in rows for lvl, _, _ in r['problems']]
    status = 'fail' if 'fail' in levels else 'warn' if levels or no_alt or not layout else 'ok'
    counts = {'figures': len(rows), **Counter(c for r in rows for _, c, _ in r['problems'])}
    if no_alt:
        counts['no_alt'] = no_alt
    items = [{'where': r['where'], 'message': f"{r['name']}: {m}"} for r in rows for _, _, m in r['problems']]
    summary = f'{len(rows)} figures, {len(bad)} with problems' + (f', {no_alt} without alt text' if no_alt else '')
    if not layout:
        summary += ', layout unmeasured'
    path = write_status(root, status, summary, counts, items)
    out.append(f'status {status}: {path.relative_to(root)}')
    return (1 if status == 'fail' else 0), out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tex', type=Path)
    ap.add_argument('--min-pt', type=float, default=6.0, help='smallest readable text size in print (default 6)')
    ap.add_argument('--no-compile', action='store_true', help='use the cached layout only')
    args = ap.parse_args(argv)
    main_tex = args.tex.resolve()
    if not main_tex.exists():
        print(f'not found: {args.tex}')
        return 2
    code, out = check(main_tex, args.min_pt, not args.no_compile)
    print('\n'.join(out))
    return code


if __name__ == '__main__':
    sys.exit(main())
