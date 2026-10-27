#!/usr/bin/env python3
"""Compile any LaTeX document with the right engine; print a short digest and optional PNG previews.

Usage: build.py main.tex [--engine auto|pdflatex|xelatex|lualatex] [--pdfa | --tagged [LANG]] [--preview DIR]
                         [--pages 1-3] [--dpi 80] [--clean]
  auto: a `% !TEX program = ...` line wins; else xelatex for fontspec/xeCJK/polyglossia/unicode-math,
        lualatex for luacode/luatexja/lua-ul, otherwise pdflatex (or whatever a latexmkrc sets).
  Missing packages are listed before compiling (needs kpsewhich, i.e. TeX Live/MiKTeX; tectonic fetches its own).
  --pdfa  writes <stem>-pdfa.pdf with \\DocumentMetadata{pdfstandard=A-2b} (latexmk + LaTeX 2022-06 or newer).
  --tagged [LANG]  writes a tagged PDF/UA-2 copy, <stem>-tagged.pdf, with
          \\DocumentMetadata{lang=LANG,pdfstandard=ua-2,tagging=on} (LANG default en). Needs latexmk and
          LaTeX 2025-11-01 or newer; LuaLaTeX unless --engine pdflatex (the tagging code does not support XeTeX).
  --clean removes auxiliary files and exits.
Uses latexmk, else tectonic. Exit 1 on errors. Stdlib only.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from texlog import digest  # noqa: E402

MAGIC = re.compile(r'^%\s*!TEX\s+(?:TS-)?program\s*=\s*(pdflatex|xelatex|lualatex)', re.I | re.M)
PKG = re.compile(r'\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
CLS = re.compile(r'\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
XE_PKGS = {'fontspec', 'xeCJK', 'polyglossia', 'unicode-math', 'xltxtra', 'xunicode', 'mathspec'}
LUA_PKGS = {'luacode', 'luatexja', 'lua-ul', 'luaotfload', 'lua-visual-debug'}
LATEXMK_FLAG = {'pdflatex': '-pdf', 'xelatex': '-xelatex', 'lualatex': '-lualatex'}
PDFA_PRETEX = r"\DocumentMetadata{pdfstandard=A-2b}"
# latex3.github.io/tagging-project/documentation/usage-instructions (checked 2026-10): documented for LaTeX 2025-11-01
# and 2026-06-01; the 2025-02 prototype used testphase=latest instead of tagging=on
TAGGED_PRETEX = r"\DocumentMetadata{{lang={lang},pdfstandard=ua-2,tagging=on}}"
AUX = ('.aux', '.log', '.out', '.toc', '.lof', '.lot', '.fls', '.fdb_latexmk', '.synctex.gz', '.bbl', '.blg',
       '.bcf', '.run.xml', '.nav', '.snm', '.vrb', '.idx', '.ind', '.ilg', '.glo', '.gls', '.glg', '.xdv')
TIMEOUT = 300


def strip_comments(text):
    return re.sub(r'(?<!\\)%.*', '', text)


def packages(text):
    return [p.strip() for m in PKG.findall(strip_comments(text)) for p in m.split(',') if p.strip()]


def engine_for(text):
    """Pick the engine a document needs from its source."""
    m = MAGIC.search(text)
    if m:
        return m[1].lower()
    pkgs = set(packages(text))
    if pkgs & LUA_PKGS or '\\directlua' in text:
        return 'lualatex'
    if pkgs & XE_PKGS:
        return 'xelatex'
    return 'pdflatex'


def source_text(main):
    """The main file's text; for a wrapper without \\documentclass (e.g. \\AtBeginDocument{\\printanswers}\\input{exam})
    also the files it inputs, so engine and package checks see the real preamble."""
    text = main.read_text(encoding='utf-8', errors='replace')
    if '\\documentclass' not in strip_comments(text):
        for name in re.findall(r'\\input\s*\{([^}]+)\}', strip_comments(text)):
            p = main.parent / (name if name.endswith('.tex') else name + '.tex')
            if p.exists():
                text += '\n' + p.read_text(encoding='utf-8', errors='replace')
    return text


def has_latexmkrc(folder):
    return any(p.exists() for p in (folder / 'latexmkrc', folder / '.latexmkrc', Path.home() / '.latexmkrc'))


def pick_engine(text, engine='auto', tagged=None):
    if engine != 'auto':
        return engine
    return 'lualatex' if tagged else engine_for(text)  # LuaLaTeX: the tagging project's preferred engine (MathML)


def compile_cmd(main, pdfa=False, engine='auto', tagged=None):
    """The command that builds `main`, or None without latexmk/tectonic. Shared with hooks/compile_loop.py.
    tagged: a language tag (e.g. 'en') for a PDF/UA-2 copy, or None."""
    text = source_text(main)
    chosen = pick_engine(text, engine, tagged)
    if shutil.which('latexmk'):
        # A latexmkrc may choose the engine; only override it when the source needs xelatex/lualatex
        # or the user asked for one.
        flag = [] if chosen == 'pdflatex' and engine == 'auto' and has_latexmkrc(main.parent) else [LATEXMK_FLAG[chosen]]
        extra = [f'-usepretex={PDFA_PRETEX}', f'-jobname={main.stem}-pdfa'] if pdfa else []
        if tagged:
            extra = [f'-usepretex={TAGGED_PRETEX.format(lang=tagged)}', f'-jobname={main.stem}-tagged']
        return ['latexmk', *flag, *extra, '-interaction=nonstopmode', '-halt-on-error', '-file-line-error', main.name]
    if shutil.which('tectonic') and not pdfa and not tagged:
        return ['tectonic', '--keep-logs', main.name]  # XeTeX-based: fine for pdflatex and xelatex sources
    return None


def missing_packages(text):
    if not shutil.which('kpsewhich'):
        return []
    files = [p + '.sty' for p in dict.fromkeys(packages(text))]
    files += [c.strip() + '.cls' for c in CLS.findall(strip_comments(text))[:1]]
    if not files:
        return []
    found = subprocess.run(['kpsewhich', *files], capture_output=True, text=True).stdout.split()
    names = {Path(f).name for f in found}
    return [f for f in files if f not in names]


def find_output(main, suffix, stem=None):
    stem = stem or main.stem
    cands = [p for d in ('.', 'build', 'out', '_build') if (p := main.parent / d / (stem + suffix)).exists()]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def page_count(pdf):
    if shutil.which('pdfinfo'):
        out = subprocess.run(['pdfinfo', str(pdf)], capture_output=True, text=True).stdout
        m = re.search(r'^Pages:\s+(\d+)', out, re.M)
        if m:
            return int(m[1])
    # shortcut: counts /Type /Page objects, wrong for PDFs with compressed object streams; install poppler
    return len(re.findall(rb'/Type\s*/Page(?![s\w])', pdf.read_bytes())) or None


def page_range(spec, n):
    """'2' -> (2, 2), '1-3' -> (1, 3), 'all' -> (1, n); clamped to the document."""
    if spec in ('all', ''):
        return 1, n or 1
    a, _, b = spec.partition('-')
    first, last = int(a), int(b or a)
    return max(1, first), min(last, n) if n else last


def previews(pdf, out_dir, spec='1', dpi=80):
    if not shutil.which('pdftoppm'):
        return ['(no pdftoppm: install poppler for previews)']
    out_dir.mkdir(parents=True, exist_ok=True)
    first, last = page_range(spec, page_count(pdf))
    subprocess.run(['pdftoppm', '-png', '-r', str(dpi), '-f', str(first), '-l', str(last), str(pdf),
                    str(out_dir / pdf.stem)], capture_output=True)
    return [str(p) for p in sorted(out_dir.glob(pdf.stem + '-*.png'))
            if first <= int(p.stem.rsplit('-', 1)[1]) <= last]


def clean(main):
    if shutil.which('latexmk'):
        subprocess.run(['latexmk', '-c', main.name], cwd=main.parent, capture_output=True)
    removed = []
    for d in (main.parent, main.parent / 'build'):
        for ext in AUX:
            p = d / (main.stem + ext)
            if p.exists():
                p.unlink()
                removed.append(p.name)
    return removed


TOOL_HINTS = {'biber': 'install biber (TeX Live and MacTeX include it; brew install biber), or use bibtex/natbib',
              'bibtex': 'install bibtex (part of TeX Live / MacTeX)'}


def engine_errors(console, n=3):
    """The engine's own error lines, for failures that never reach the .log, plus a fix for a missing tool."""
    lines = [l.strip() for l in console.splitlines()
             if re.match(r'\s*(error|fatal|latexmk: )', l, re.I) or 'external tool' in l]
    out = [f'engine: {l[:160]}' for l in lines[:n]]
    tool = re.search(r'external tool (\w+)', console)
    if tool and tool[1] in TOOL_HINTS and not shutil.which(tool[1]):
        out.append(f'fix: {tool[1]} is not installed: {TOOL_HINTS[tool[1]]}')
    return out


def build(main, engine='auto', pdfa=False, preview_dir=None, pages='1', dpi=80, tagged=None):
    """-> (exit_code, report lines)."""
    text = source_text(main)
    out = []
    if tagged and engine == 'xelatex':
        return 2, ['--tagged needs lualatex or pdflatex: the LaTeX tagging code does not support XeTeX']
    if tagged and '\\DocumentMetadata' in strip_comments(text):
        return 2, ['the source already has \\DocumentMetadata: add lang=…, pdfstandard=ua-2, tagging=on there '
                   'and build normally']
    missing = missing_packages(text)
    if missing:
        out.append('MISSING (install first, e.g. tlmgr install <name>): ' + ' '.join(missing))
    cmd = compile_cmd(main, pdfa, engine, tagged)
    if cmd is None:
        if tagged and shutil.which('tectonic'):
            out.append('--tagged is not supported with tectonic: it is XeTeX-based, and tagged PDF needs LuaLaTeX or '
                       'pdfLaTeX from TeX Live (LaTeX 2025-11-01 or newer) plus latexmk')
        else:
            out.append('no TeX engine: install TeX Live / MacTeX, or tectonic (brew install tectonic)'
                       + ('; --pdfa needs latexmk' if pdfa else '') + ('; --tagged needs latexmk' if tagged else ''))
        return 2, out
    chosen = pick_engine(text, engine, tagged)
    if cmd[0] == 'tectonic' and chosen == 'lualatex':
        out.append('warning: this source needs lualatex but only tectonic (XeTeX) is installed')
    try:
        run = subprocess.run(cmd, cwd=main.parent, capture_output=True, text=True, errors='replace', timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        out.append(f'TIMEOUT after {TIMEOUT}s: {" ".join(cmd)}')
        return 1, out
    stem = main.stem + ('-pdfa' if pdfa else '-tagged' if tagged else '')
    log, pdf = find_output(main, '.log', stem), find_output(main, '.pdf', stem)
    report, has_errors = digest(log.read_text(encoding='utf-8', errors='replace')) if log else ('no .log written', True)
    if has_errors or not pdf:
        out.append(f'FAILED {main.name} ({cmd[0]} {chosen})')
        out.append(report)
        if not log or not has_errors:  # stopped outside TeX (e.g. a missing biber): only the console says why
            out += engine_errors((run.stdout or '') + (run.stderr or ''))
        return 1, out
    out.append(f'OK {pdf} | {page_count(pdf) or "?"} pages | {cmd[0]} {chosen}' + (' | PDF/A-2b' if pdfa else '')
               + (f' | tagged PDF/UA-2 (lang={tagged})' if tagged else ''))
    if report.startswith('clean'):
        out.append(report)
    else:
        out += report.splitlines()
    if preview_dir:
        out.append('preview: ' + ' '.join(previews(pdf, Path(preview_dir), pages, dpi)))
    return 0, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tex', type=Path)
    ap.add_argument('--engine', default='auto', choices=['auto', *LATEXMK_FLAG])
    std = ap.add_mutually_exclusive_group()  # PDF/A-2b is PDF 1.7; PDF/UA-2 is PDF 2.0
    std.add_argument('--pdfa', action='store_true', help='also write a PDF/A-2b copy (<stem>-pdfa.pdf)')
    std.add_argument('--tagged', nargs='?', const='en', metavar='LANG',
                     help='also write a tagged PDF/UA-2 copy (<stem>-tagged.pdf); LANG is a language tag, default en')
    ap.add_argument('--preview', metavar='DIR', help='write PNG previews of --pages into DIR')
    ap.add_argument('--pages', default='1', help="pages to preview: '2', '1-3' or 'all' (default 1)")
    ap.add_argument('--dpi', type=int, default=80, help='preview resolution; 80 keeps images cheap to look at')
    ap.add_argument('--clean', action='store_true', help='remove auxiliary files and exit')
    args = ap.parse_args(argv)
    if args.tagged and not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*', args.tagged):
        ap.error(f'--tagged expects a language tag such as en or en-GB, got {args.tagged!r}')
    main_tex = args.tex.resolve()
    if not main_tex.exists():
        print(f'not found: {args.tex}')
        return 2
    if args.clean:
        print('removed: ' + (' '.join(clean(main_tex)) or 'nothing'))
        return 0
    code, out = build(main_tex, args.engine, args.pdfa, args.preview, args.pages, args.dpi, args.tagged)
    print('\n'.join(out))
    return code


if __name__ == '__main__':
    sys.exit(main())
