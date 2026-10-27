#!/usr/bin/env python3
"""Check a LaTeX paper for problems in arXiv's HTML conversion (LaTeXML); print a grouped digest with fixes.

Usage: html_check.py paper/main.tex

Static checks, each with file:line and a fix:
  packages/classes with no LaTeXML binding (reference/latexml-packages.txt, incl. LaTeXML's versioned-name
  fallback, e.g. neurips_2025 -> neurips), \\includegraphics without alt=, visual-only markup ({\\it}, {\\bf},
  bold or sized lines used as headings), missing \\title/\\author/abstract; info: local style files,
  TikZ outside a captioned float, macros built from low-level typesetting primitives.
With latexml_oxide (what arXiv runs) or latexmlc on PATH, also converts a scratch copy and digests its errors.
Writes <project>/.agentex/status/arxiv-html.json. Exit 0 only when nothing needs fixing. Stdlib only.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arxiv_pack import Packer, uncomment  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parent.parent / 'reference' / 'latexml-packages.txt'
LOAD = re.compile(r'\\(usepackage|RequirePackage|documentclass)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
# LaTeXML's FindFile_fallback (lib/LaTeXML/Package.pm; latexml-oxide matches it): strip version/arXiv suffixes and
# my/rw/preprint prefixes, then look for a binding of what is left.
SUFFIX = re.compile(r'(?:[._-](?:arx|arxiv|conference|workshop|tmp|alternate|preprint|fixed|[vV]?[-_.\d]+|old|new|final'
                    r'|clean|mine|priv|rev|mod|modified|edited|custom|altered|rtx)|[vV]?[-_.\d]+|arxiv)$', re.I)
PREFIX = re.compile(r'^(?:rw|my|preprint)[-_.]?', re.I)
IMG = re.compile(r'\\includegraphics\*?\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}')
OLD_FONT = re.compile(r'\{\\(it|bf|sl|sc|tt|rm|sf)\b')
OLD_FIX = {'it': '\\emph{…}', 'sl': '\\emph{…}', 'bf': '\\textbf{…}, or \\paragraph{…} if it is a heading',
           'sc': '\\textsc{…}', 'tt': '\\texttt{…} (\\url{…} for addresses)', 'rm': '\\textrm{…}', 'sf': '\\textsf{…}'}
BOLD_LINE = re.compile(r'^[ \t]*(?:\\noindent\s*)?\\textbf\{[^{}\n]{1,80}\}[ \t]*(?:\\\\|\\par\b|\\newline)?[ \t]*$', re.M)
SIZE = re.compile(r'\\(?:large|Large|LARGE|huge|Huge|fontsize)\b')
HEADING_HINT = re.compile(r'\\(?:bfseries|bf|textbf|vspace)\b')
DEF = re.compile(r'\\(?:(?:re)?newcommand|providecommand|DeclareRobustCommand)\*?\s*\{?\s*(\\[A-Za-z@]+)\s*\}?\s*'
                 r'(?:\[\d\])?\s*(?:\[[^\]]*\])?\s*(?=\{)|\\[egx]?def\s*(\\[A-Za-z@]+)[^{]*(?=\{)')
HEAVY = re.compile(r'\\(?:expandafter|csname|catcode|futurelet|afterassignment|kern|hskip|vskip|raisebox|fontsize'
                   r'|selectfont|vspace|hspace|makebox|mathchoice|edef|xdef|scalebox)\b|\\[A-Za-z]*@[A-Za-z@]*')
CONVERTERS = ('latexml_oxide', 'latexmlc')  # arXiv runs latexml_oxide (its HTML logs, 2026-09)
MSG = re.compile(r'^(Error|Fatal):([\w-]+):(\S*)\s*(.*)')
LOC = re.compile(r'^\s*at (.+?); line (\d+)')
TIMEOUT = 600
GROUPS = {  # key: (severity, heading)
    'conversion': ('fail', 'CONVERSION ERRORS (real LaTeXML run)'),
    'packages': ('warn', 'PACKAGES with no LaTeXML binding'),
    'alt-text': ('warn', 'IMAGES without alt text'),
    'markup': ('warn', 'VISUAL-ONLY MARKUP'),
    'front-matter': ('warn', 'FRONT MATTER'),
    'local-styles': ('info', 'LOCAL STYLE FILES (read as raw TeX)'),
    'tikz': ('info', 'TIKZ outside a captioned float'),
    'macros': ('info', 'LOW-LEVEL MACROS'),
}
RANK = {'fail': 0, 'warn': 1, 'info': 2}


def load_bindings(path=SNAPSHOT):
    return {l.strip().lower() for l in path.read_text(encoding='utf-8').splitlines() if l.strip() and not l.startswith('#')}


def has_binding(name, ext, names):
    """Exact (case-insensitive) binding, else LaTeXML's versioned-name fallback."""
    if f'{name}.{ext}'.lower() in names:
        return True
    base, prev = name, None
    while base != prev:
        prev, base = base, PREFIX.sub('', SUFFIX.sub('', base))
    return base != name and f'{base}.{ext}'.lower() in names


def line_of(text, pos):
    return text.count('\n', 0, pos) + 1


def braced(text, i):
    """The brace-balanced {...} group that starts at text[i]."""
    depth = 0
    for k in range(i, min(len(text), i + 5000)):
        if text[k] in '{}' and text[k - 1] != '\\':
            depth += 1 if text[k] == '{' else -1
            if depth == 0:
                return text[i:k + 1]
    return text[i:i + 5000]


def in_captioned_float(text, pos):
    start = max(text.rfind('\\begin{figure', 0, pos), text.rfind('\\begin{table', 0, pos))
    if start == -1 or re.search(r'\\end\{(?:figure|table)', text[start:pos]):
        return False
    end = re.search(r'\\end\{(?:figure|table)', text[pos:])
    return bool(re.search(r'\\caption', text[start:pos + (end.end() if end else len(text))]))


def check_packages(rel, text, local, names, seen):
    """local: lower-case stems of .sty files in the project; seen: names already reported (one finding per name)."""
    out = []
    for m in LOAD.finditer(text):
        ext = 'cls' if m[1] == 'documentclass' else 'sty'
        for name in (n.strip() for n in m[2].split(',')):
            if not name or name in seen or has_binding(name, ext, names):
                continue
            seen.add(name)
            where = f'{rel}:{line_of(text, m.start())}'
            if ext == 'cls':
                out.append(('packages', where, f'class {name} has no LaTeXML binding: arXiv converts with the generic '
                            'OmniBus class, so its own commands may come out as errors. Fix: check the HTML preview; '
                            'ask the publisher for LaTeXML support'))
            elif Path(name).name.lower() in local:
                out.append(('local-styles', where, f'{name}.sty is local with no binding: the converter reads its raw '
                            'TeX, and low-level code in it may fail. Fix: keep it to plain \\newcommand macros'))
            else:
                out.append(('packages', where, f'{name}.sty has no LaTeXML binding, so its commands may come out as '
                            'errors in the HTML. Fix: drop it or use a supported package (reference/latexml-packages.txt)'))
    return out


def check_tex(rel, text, is_main):
    out = []
    body = max(text.find('\\begin{document}'), 0) if is_main else 0
    for m in IMG.finditer(text):
        opts, path = m[1] or '', m[2]
        if '#' not in path and not re.search(r'\b(?:alt|artifact|actualtext)\b', opts):
            out.append(('alt-text', f'{rel}:{line_of(text, m.start())}', f'{path} has no alt text. Fix: '
                        f'\\includegraphics[{opts + "," if opts else ""}alt={{…}}]{{{path}}} (draft it from the script and data)'))
    seen = set()
    for m in OLD_FONT.finditer(text, body):
        seen.add(line_of(text, m.start()))
        out.append(('markup', f'{rel}:{line_of(text, m.start())}', f'{{\\{m[1]} …}} only changes the font. Fix: {OLD_FIX[m[1]]}'))
    for m in BOLD_LINE.finditer(text, body):
        if line_of(text, m.start()) not in seen:
            seen.add(line_of(text, m.start()))
            out.append(('markup', f'{rel}:{line_of(text, m.start())}', 'bold line used as a heading: missing from the HTML '
                        'outline and screen-reader navigation. Fix: \\paragraph{…} or \\subsection*{…}'))
    start = line_of(text, body)
    for n, line in enumerate(text[body:].splitlines(), start):
        if n not in seen and SIZE.search(line) and HEADING_HINT.search(line):
            out.append(('markup', f'{rel}:{n}', 'hand-made heading (font size + bold/\\vspace): missing from the HTML '
                        'outline. Fix: \\section{…} or \\subsection{…}, restyled in the preamble if needed'))
    for m in re.finditer(r'\\begin\{tikzpicture\}', text):
        # shortcut: a file with no float at all is assumed to be \input inside one (figure fragments)
        if re.search(r'\\begin\{(?:figure|table)', text) and not in_captioned_float(text, m.start()):
            out.append(('tikz', f'{rel}:{line_of(text, m.start())}', 'TikZ outside a captioned figure: arXiv turns it '
                        'into SVG (sometimes failing) and readers get no text alternative. Fix: a figure whose \\caption '
                        'says what it shows'))
    for m in DEF.finditer(text):
        hits = sorted(set(HEAVY.findall(braced(text, m.end()))))
        if hits:
            out.append(('macros', f'{rel}:{line_of(text, m.start())}', f'{m[1] or m[2]} uses {", ".join(hits[:3])}: '
                        'placement and font tweaks are lost or garbled in HTML. Fix: a plain semantic macro'))
    return out


def check_front(texts, main_rel):
    joined = '\n'.join(texts)
    begin = max(texts[0].find('\\begin{document}'), 0)
    where = f'{main_rel}:{line_of(texts[0], begin)}'
    missing = [(r'\\(?:icml)?title\s*(?:\[[^\]]*\])?\s*\{', '\\title{…}'), (r'\\(?:icml)?author\b', '\\author{…}'),
               (r'\\begin\{abstract\}|\\abstract\s*\{', '\\begin{abstract} … \\end{abstract}')]
    return [('front-matter', where, f'no {fix}: arXiv builds the HTML title block and metadata from the standard '
             f'commands. Fix: use {fix}') for rx, fix in missing if not re.search(rx, joined)]


def convert(pk, timeout=TIMEOUT):
    """Run LaTeXML on a scratch copy -> (tool, findings, summary) or None when no converter is installed."""
    exe = next((c for c in CONVERTERS if shutil.which(c)), None)
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as d:
        for f in pk.files:
            dest = Path(d) / pk.rel(f)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
        try:
            r = subprocess.run([exe, pk.main.name, f'--destination={pk.main.stem}.html'], cwd=d,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return exe, [('conversion', pk.main.name, f'{exe} timed out after {timeout}s')], 'timed out'
        lines = (r.stdout + '\n' + r.stderr).replace(d + os.sep, '').splitlines()
    found = []
    for i, line in enumerate(lines):
        m = MSG.match(line)
        if m:
            loc = LOC.match(lines[i + 1]) if i + 1 < len(lines) else None
            found.append(('conversion', f'{loc[1]}:{loc[2]}' if loc else pk.main.name, f'{m[1]}:{m[2]}:{m[3]} {m[4]}'.strip()))
    summary = next((l.strip() for l in reversed(lines) if 'Conversion complete' in l), f'exit code {r.returncode}')
    if r.returncode and not found:
        found.append(('conversion', pk.main.name, f'{exe} failed: {summary}'))
    return exe, found, summary


def write_status(root, status, summary, counts, items):
    """Dashboard contract: <project>/.agentex/status/arxiv-html.json, replaced atomically."""
    d = root / '.agentex'
    (d / 'status').mkdir(parents=True, exist_ok=True)
    if not (d / '.gitignore').exists():
        (d / '.gitignore').write_text('*\n')
    tmp = d / 'status' / 'arxiv-html.json.tmp'
    tmp.write_text(json.dumps({'tool': 'arxiv-html', 'status': status, 'summary': summary[:100], 'counts': counts,
                               'items': items[:20], 'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
                              indent=1))
    os.replace(tmp, d / 'status' / 'arxiv-html.json')


def project_root(start):
    return next((p for p in (start, *start.parents) if (p / '.agentex').is_dir() or (p / '.git').exists()), start)


def check(main_tex, names=None):
    """-> (status, report lines, findings)."""
    names = names if names is not None else load_bindings()
    pk = Packer(main_tex)
    pk.run()
    findings, texts, seen = [], [], set()
    local = {p.stem.lower() for p in pk.root.rglob('*.sty')}
    for f in sorted(pk.files, key=lambda p: (p != pk.main, str(p))):
        if f.suffix not in ('.tex', '.sty', '.cls'):
            continue
        text = uncomment(f.read_text(encoding='utf-8', errors='replace'))
        findings += check_packages(pk.rel(f), text, local, names, seen)
        if f.suffix == '.tex':
            texts.append(text)
            findings += check_tex(pk.rel(f), text, f == pk.main)
    findings += check_front(texts, pk.main.name)
    ran = convert(pk)
    if ran:
        findings += ran[1]
    findings.sort(key=lambda x: RANK[GROUPS[x[0]][0]])
    counts = {g: sum(1 for x in findings if x[0] == g) for g in GROUPS}
    severities = {GROUPS[g][0] for g, n in counts.items() if n}
    status = 'fail' if 'fail' in severities else 'warn' if 'warn' in severities else 'ok'
    to_fix = ', '.join(f'{n} {g}' for g, n in counts.items() if n and GROUPS[g][0] != 'info')
    info = sum(n for g, n in counts.items() if GROUPS[g][0] == 'info')
    summary = (f'to fix: {to_fix}' if to_fix else 'no HTML blockers found') + (f'; {info} info' if info else '')
    out = [f'arXiv HTML check: {pk.main.name} (+{len(texts) - 1} files) | {status.upper()} | {summary}']
    for g, (_, heading) in GROUPS.items():
        rows = [x for x in findings if x[0] == g]
        if rows:
            out.append(f'{heading} ({len(rows)})')
            out += [f'  {w}  {m}' for _, w, m in rows[:8]] + ([f'  ... {len(rows) - 8} more'] if len(rows) > 8 else [])
    if ran:
        out.append(f'{ran[0]}: {ran[2]}')
    else:
        out.append('no LaTeXML here, so no real conversion was run. arXiv shows the HTML during submission: check it '
                   'before you submit. Local preview: brew install dginev/tap/latexml-oxide, then re-run')
    write_status(project_root(pk.root), status, summary, {g: n for g, n in counts.items() if n},
                 [{'where': w, 'message': m} for _, w, m in findings])
    return status, out, findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('main', type=Path)
    args = ap.parse_args(argv)
    if not args.main.is_file():
        ap.error(f'not found: {args.main}')
    status, out, _ = check(args.main.resolve())
    print('\n'.join(out))
    return 0 if status == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
