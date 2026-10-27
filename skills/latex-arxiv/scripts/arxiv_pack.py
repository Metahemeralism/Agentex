#!/usr/bin/env python3
"""Package a LaTeX project for arXiv with only the files the document actually uses.

Usage: arxiv_pack.py path/to/main.tex [-o OUT] [--keep-comments] [--prefer-bib] [--compile] [--force]

Follows \\input/\\include/\\subfile/\\import, \\includegraphics (+\\graphicspath), \\includestandalone,
\\includepdf, listings/minted/verbatim inputs, pgfplots tables, local .sty/.cls/.bst/beamer themes
and the .bbl (or the .bib files when there is no .bbl). Strips comments from .tex files (verbatim blocks, \\url/\\href arguments and \\% are
kept), checks common arXiv rejection causes, then writes OUT/ and OUT.tar.gz.
Exit code 1 on errors; nothing is written unless --force. Stdlib only.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

GRAPHIC_EXTS = ['.pdf', '.png', '.jpg', '.jpeg', '.eps', '.ps', '.mps', '.PDF', '.PNG', '.JPG', '.JPEG']
TEXT_INPUT_EXTS = {'.tex', '.pgf', '.tikz'}  # scanned for further references (matplotlib .pgf can \includegraphics)
OPT = r'(?:\s*\[[^\]]*\])*'
REFS = [  # (regex, default extension, or 'graphic' to search \graphicspath and image extensions)
    (re.compile(r'\\(?:input|include|subfile|includestandalone)' + OPT + r'\s*\{([^}]+)\}'), '.tex'),
    (re.compile(r'\\(?:includegraphics|includepdf)\*?' + OPT + r'\s*\{([^}]+)\}'), 'graphic'),
    (re.compile(r'\\(?:lstinputlisting|verbatiminput|VerbatimInput)' + OPT + r'\s*\{([^}]+)\}'), ''),
    (re.compile(r'\\inputminted' + OPT + r'\s*\{[^}]*\}\s*\{([^}]+)\}'), ''),
    (re.compile(r'\\pgfplotstableread' + OPT + r'\s*\{([^}\s]+\.\w+)\}'), ''),
    (re.compile(r'\btable' + OPT + r'\s*\{([^}\s\\]+\.\w+)\}'), ''),  # \addplot table {data.csv}
]
IMPORT = re.compile(r'\\(?:sub)?(?:import|inputfrom|includefrom)\*?\s*\{([^}]*)\}\s*\{([^}]+)\}')
LOCAL_PKG = re.compile(r'\\(usepackage|RequirePackage|documentclass|bibliographystyle|use(?:inner|outer|color|font)?theme)'
                       + OPT + r'\s*\{([^}]+)\}')
PKG_EXT = {'usepackage': '.sty', 'RequirePackage': '.sty', 'documentclass': '.cls', 'bibliographystyle': '.bst'}
THEME_PREFIX = {'usetheme': 'beamertheme', 'useinnertheme': 'beamerinnertheme', 'useoutertheme': 'beameroutertheme',
                'usecolortheme': 'beamercolortheme', 'usefonttheme': 'beamerfonttheme'}
GRAPHICSPATH = re.compile(r'\\graphicspath\s*\{((?:\s*\{[^}]*\})+)\s*\}')
BIBS = re.compile(r'\\(?:bibliography|addbibresource' + OPT + r')\s*\{([^}]+)\}')
VERBATIM_BEGIN = re.compile(r'\\begin\{(verbatim\*?|Verbatim\*?|lstlisting|minted|alltt|filecontents\*?|comment)\}')
FLAGS = {
    'biblatex': r'\\usepackage' + OPT + r'\s*\{[^}]*\bbiblatex\b|\\addbibresource',
    'bibtex': r'\\bibliography\s*\{',
    'minted': r'\\usepackage' + OPT + r'\s*\{[^}]*\bminted\b',
    'externalize': r'\\tikzexternalize',
    'svg': r'\\includesvg',
    'todo': r'\\usepackage' + OPT + r'\s*\{[^}]*\btodonotes\b|\\todo\s*\{',
}
BUILD_JUNK = re.compile(r'(^|/)\.|(^|/)(build|_minted[^/]*)/|\.(aux|log|out|toc|lof|lot|fls|fdb_latexmk|synctex\.gz|'
                        r'blg|bcf|run\.xml|nav|snm|vrb|xdv|dvi)$')
MAX_TOTAL_MB = 50
ARXIV_BBL_FORMAT = '3.3'  # TeX Live 2025, arXiv's default (info.arxiv.org/help/submit_tex.html, checked 2026-10)


def comment_start(line):
    """Index of the first real comment '%' on a line, or None. A '%' after an odd number of
    backslashes is escaped; one inside a \\url{...} or \\href{...} argument is literal."""
    for m in re.finditer('%', line):
        i = m.start()
        if (len(line[:i]) - len(line[:i].rstrip('\\'))) % 2:
            continue
        u = max(line.rfind('\\url{', 0, i), line.rfind('\\href{', 0, i))
        if u != -1 and line.count('{', u, i) > line.count('}', u, i):
            continue
        return i
    return None


def uncomment(text):
    """Drop comment text (keep line structure) so commented-out references are not followed."""
    out = []
    for line in text.splitlines(keepends=True):
        i = comment_start(line)
        out.append(line if i is None else line[:i] + '\n')
    return ''.join(out)


# alltt is left out on purpose: commands inside it are live, so its \\input lines are real
VERBATIM_BLOCK = re.compile(r'\\begin\{(verbatim\*?|Verbatim\*?|lstlisting|minted|filecontents\*?|comment)\}.*?\\end\{\1\}'
                            r'|\\verb\*?([^\w\s]).*?\2', re.S)


def blank_verbatim(text):
    """Blank verbatim blocks and \\verb (newlines kept) so file names shown as code are not followed."""
    return VERBATIM_BLOCK.sub(lambda m: re.sub(r'[^\n]', ' ', m[0]), text)


def strip_comments(text):
    """Remove comments for publication. Verbatim-like environments are copied untouched;
    \\begin{comment} blocks are removed; a trailing comment keeps its '%' so no space appears."""
    out, env = [], None
    for line in text.splitlines(keepends=True):
        if env:
            if env != 'comment':
                out.append(line)
            if f'\\end{{{env}}}' in line:
                env = None
            continue
        i = comment_start(line)
        m = VERBATIM_BEGIN.search(line)
        if m and (i is None or m.start() < i) and f'\\end{{{m[1]}}}' not in line[m.end():]:
            env = m[1]
            if env != 'comment':
                out.append(line)
            continue
        if i is None:
            out.append(line)
        elif line[:i].strip():
            out.append(line[:i] + '%\n')
        # whole-line comments are dropped: they produce neither output nor space
    return ''.join(out)


def bbl_format(bbl):
    """biblatex writes '% $ biblatex bbl format version X.Y $' near the top of the .bbl."""
    m = re.search(r'bbl format version (\d+\.\d+)', ''.join(bbl.read_text(errors='replace').splitlines(True)[:5]))
    return m[1] if m else None


def exact_case(root, rel):
    """True if every path component exists with exactly this case (macOS hides mismatches)."""
    cur = root
    for part in Path(rel).parts:
        try:
            if part not in os.listdir(cur):
                return False
        except OSError:
            return False
        cur = cur / part
    return True


class Packer:
    def __init__(self, main):
        self.main = main.resolve()
        self.root = self.main.parent
        self.files, self.scanned = {self.main}, {self.main}
        self.errors, self.warnings, self.flags, self.bibs = [], [], set(), []
        self.graphicspath = ['']

    def rel(self, p):
        return os.path.relpath(p, self.root)

    def add(self, rel, origin):
        """Register rel if it exists inside the project; returns the path, or None if absent."""
        rel = rel.strip().replace('\\', '/')
        if os.path.isabs(rel) or rel.startswith('~'):
            self.errors.append(f'absolute path "{rel}" in {origin}: arXiv needs paths relative to {self.main.name}')
            return None
        p = (self.root / rel).resolve()
        if self.root not in p.parents:
            self.errors.append(f'"{rel}" in {origin} is outside the project folder; move it inside')
            return None
        if not p.is_file():
            return None
        if not exact_case(self.root, self.rel(p)):
            self.errors.append(f'"{rel}" in {origin}: letter case differs from the file on disk '
                               "(works on macOS/Windows, fails on arXiv's Linux)")
        if re.search(r'[^\w./+-]', self.rel(p)):
            self.warnings.append(f'unusual characters in "{self.rel(p)}" (spaces etc. break some arXiv builds)')
        self.files.add(p)
        return p

    def find(self, name, ext, origin, base=''):
        name = name.strip()
        has_ext = bool(Path(name).suffix)
        if ext == 'graphic':
            cands = [base + gp + name + e for gp in self.graphicspath
                     for e in ([''] if has_ext else []) + GRAPHIC_EXTS]
        else:
            cands = [base + name] + ([base + name + ext] if ext else [])
        n_errors = len(self.errors)
        for c in cands:
            p = self.add(c, origin)
            if p or len(self.errors) > n_errors:  # found, or already reported (outside/absolute)
                return p
        self.errors.append(f'missing file "{name}" referenced in {origin}')
        return None

    def follow(self, p, base):
        if p and p.suffix in TEXT_INPUT_EXTS | {'.sty', '.cls'} and p not in self.scanned:
            self.scanned.add(p)
            self.scan(p, base)

    def scan(self, path, base=''):
        """base: directory prefix that relative names resolve against (set by \\import)."""
        text = blank_verbatim(uncomment(path.read_text(encoding='utf-8', errors='replace')))
        origin = self.rel(path)
        for m in GRAPHICSPATH.finditer(text):
            self.graphicspath = [''] + re.findall(r'\{([^}]*)\}', m[1])
        for rx, ext in REFS:
            for m in rx.finditer(text):
                self.follow(self.find(m[1], ext, origin, base), base)
        for m in IMPORT.finditer(text):
            sub = m[1].strip()
            sub += '' if not sub or sub.endswith('/') else '/'
            # \subimport is relative to the current file's folder; \import/\inputfrom to the main folder.
            new_base = (base if m[0].startswith('\\sub') else '') + sub
            self.follow(self.find(m[2], '.tex', origin, new_base), new_base)
        for m in LOCAL_PKG.finditer(text):
            for name in m[2].split(','):
                name = name.strip()
                fname = (f'{THEME_PREFIX[m[1]]}{name}.sty' if m[1] in THEME_PREFIX
                         else name if Path(name).suffix else name + PKG_EXT[m[1]])
                if (self.root / fname).is_file():  # only local files; TeX Live provides the rest
                    self.follow(self.add(fname, origin), base)
        for flag, rx in FLAGS.items():
            if re.search(rx, text):
                self.flags.add(flag)
        self.bibs += [b.strip() for m in BIBS.finditer(text) for b in m[1].split(',')]

    def run(self, prefer_bib=False):
        self.scan(self.main)
        bbl = self.main.with_suffix('.bbl')
        if self.flags & {'biblatex', 'bibtex'}:
            # arXiv uses a shipped .bbl if present, otherwise runs bibtex/biber on the .bib itself.
            fmt = bbl_format(bbl) if bbl.is_file() else None
            if bbl.is_file() and not prefer_bib:
                self.files.add(bbl)
                if 'biblatex' in self.flags and fmt != ARXIV_BBL_FORMAT:
                    self.errors.append(f'{bbl.name} has biblatex bbl format {fmt or "unknown"}, arXiv (TeX Live 2025) '
                                       f'needs {ARXIV_BBL_FORMAT}: re-run with --prefer-bib so arXiv runs biber itself')
            else:
                for b in self.bibs:
                    self.find(b, '.bib', 'bibliography')
                if not bbl.is_file() and not self.bibs:
                    self.errors.append('bibliography used but no .bib or .bbl found')
        notes = {
            'minted': 'minted needs -shell-escape, which arXiv disables: compile locally with '
                      '\\usepackage[finalizecache]{minted}, then switch to [frozencache] and ship the _minted* folder',
            'externalize': '\\tikzexternalize needs shell-escape on arXiv: ship the externalized PDFs or remove it',
            'svg': '\\includesvg calls Inkscape, which arXiv lacks: convert SVGs to PDF',
            'todo': 'todonotes / \\todo found: leftover notes will be visible in the public PDF',
        }
        self.warnings += [notes[f] for f in sorted(self.flags & notes.keys())]
        exts = {p.suffix.lower() for p in self.files}
        if {'.eps', '.ps'} & exts and {'.pdf', '.png', '.jpg', '.jpeg'} & exts:
            self.warnings.append('EPS mixed with PDF/PNG/JPG figures: pdfLaTeX cannot read EPS; convert with epstopdf')
        head = self.main.read_text(errors='replace').splitlines()[:5]
        if not any('\\pdfoutput=1' in l for l in head) and not {'.eps', '.ps'} & exts:
            self.warnings.append('add \\pdfoutput=1 within the first 5 lines of the main file so arXiv uses pdfLaTeX (\\ifdefined\\pdftexversion\\pdfoutput=1\\fi also works with XeLaTeX/LuaLaTeX)')
        for p in self.files:
            if p.stat().st_size > 10 * 2**20:
                self.warnings.append(f'{self.rel(p)} is {p.stat().st_size / 2**20:.1f} MB; consider compressing it')
        total = sum(p.stat().st_size for p in self.files) / 2**20
        if total > MAX_TOTAL_MB:
            self.errors.append(f'package is {total:.1f} MB; the arXiv limit is {MAX_TOTAL_MB} MB')
        return total

    def unused(self, out):
        used = {self.rel(p) for p in self.files}
        compiled = self.rel(self.main.with_suffix('.pdf'))
        return sorted(r for p in self.root.rglob('*') if p.is_file()
                      for r in [self.rel(p)]
                      if r not in used and r != compiled and not BUILD_JUNK.search(r)
                      and out not in p.parents and p != out.with_suffix('.tar.gz'))


def write_tar(folder):
    tar = folder.with_suffix('.tar.gz')
    with tarfile.open(tar, 'w:gz') as tf:
        for f in sorted(folder.rglob('*')):
            if f.is_file():
                tf.add(f, arcname=os.path.relpath(f, folder))
    return tar


def compile_check(folder, main_name):
    """Build the packaged folder in place, then delete only files the build created."""
    for cmd in (['latexmk', '-pdf', '-interaction=nonstopmode', '-halt-on-error', main_name],
                ['tectonic', '--keep-logs', main_name]):
        if not shutil.which(cmd[0]):
            continue
        before = set(folder.rglob('*'))
        r = subprocess.run(cmd, cwd=folder, capture_output=True, text=True)
        log = folder / Path(main_name).with_suffix('.log')
        errs = [l for l in log.read_text(errors='replace').splitlines() if l.startswith('!')] if log.exists() else []
        for f in sorted(set(folder.rglob('*')) - before, reverse=True):
            f.unlink() if f.is_file() else f.rmdir()
        return r.returncode == 0, errs[:3]
    return None, ['no TeX engine (latexmk or tectonic) found to test-compile']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('main', type=Path)
    ap.add_argument('-o', '--out', type=Path, help='output folder (default: <project>/arxiv_submission)')
    ap.add_argument('--keep-comments', action='store_true', help='keep %% comments (they become public on arXiv)')
    ap.add_argument('--prefer-bib', action='store_true',
                    help='ship .bib files instead of the .bbl so arXiv runs bibtex/biber itself')
    ap.add_argument('--compile', action='store_true', help='test-compile the packaged folder')
    ap.add_argument('--force', action='store_true', help='write despite errors, replacing a non-empty output folder')
    args = ap.parse_args(argv)
    if not args.main.is_file():
        ap.error(f'not found: {args.main}')

    pk = Packer(args.main)
    total = pk.run(args.prefer_bib)
    out = (args.out or pk.root / 'arxiv_submission').resolve()
    unused = pk.unused(out)

    print(f'{len(pk.files)} files, {total:.2f} MB')
    for r in sorted(pk.rel(f) for f in pk.files):
        print('  +', r)
    if unused:
        print(f'excluded ({len(unused)} files not used by {pk.main.name}): ' + ', '.join(unused[:12])
              + (' ...' if len(unused) > 12 else ''))
    for w in pk.warnings:
        print('WARNING:', w)
    for e in pk.errors:
        print('ERROR:', e)
    if pk.errors and not args.force:
        print('nothing written; fix the errors above (or --force)')
        return 1

    if out.exists() and any(out.iterdir()):
        if not args.force:
            print(f'{out} exists and is not empty; remove it or use --force')
            return 1
        shutil.rmtree(out)
    for f in pk.files:
        dest = out / pk.rel(f)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix == '.tex' and not args.keep_comments:
            dest.write_text(strip_comments(f.read_text(encoding='utf-8', errors='replace')), encoding='utf-8')
        else:
            shutil.copy2(f, dest)
    print(f'wrote {out}/ and {write_tar(out).name}')
    print(f'arXiv also builds an HTML version: check it with html_check.py {args.main}')

    if args.compile:
        ok, errs = compile_check(out, pk.main.name)
        print('test compile:', {True: 'OK', False: 'FAILED', None: 'skipped'}[ok])
        for e in errs:
            print('  ', e)
        return 1 if ok is False else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
