#!/usr/bin/env python3
"""Submission gate: will this paper be desk-rejected?

Usage: preflight.py main.tex --venue ID [--mode submission|camera-ready] [--pdf main.pdf]
                    [--page-limit N] [--verify-citations] [--no-build]
       preflight.py --venue list
ID names a rules file in <skill>/venues/ (or is a path to your own .json). Checks the PDF (main-body
pages up to the references, fonts, metadata, acknowledgements), the source (class mode, style-file
hash, required sections, LLM-use disclosure, placeholders, self-revealing phrases and links, missing
files, ACM/IEEE camera-ready rules) and AgenTeX state (citation cache, results audit, labels).
Builds the PDF with latex-debug/scripts/build.py only when none exists. --verify-citations runs
latex-references/scripts/cite_verify.py first (network); otherwise only its cache is read.
Prints grouped PASS/WARN/FAIL lines with file:line and the fix, writes .agentex/status/preflight.json,
exits 1 on any FAIL. Stdlib only.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, namedtuple
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent
for _d in (HERE, *(SKILLS / s / 'scripts' for s in ('latex-references', 'latex-results-sync', 'latex-pdf',
                                                    'latex-project', 'latex-arxiv'))):
    sys.path.insert(0, str(_d))
import arxiv_pack  # noqa: E402
import check_refs  # noqa: E402
import cite_verify  # noqa: E402
import pdftool  # noqa: E402
import results  # noqa: E402
import texmap  # noqa: E402
from disclosure import agentex_root, find_up, read_activity  # noqa: E402

VENUES = HERE.parent / 'venues'
BUILD = SKILLS / 'latex-debug' / 'scripts' / 'build.py'
CITE_VERIFY = SKILLS / 'latex-references' / 'scripts' / 'cite_verify.py'
MODES = ('submission', 'camera-ready')
GROUPS = ('format', 'anonymity', 'policy', 'integrity')
STALE_RULES_DAYS = 180  # venue rules change every year
SHOW = 3  # findings listed per check; the rest are counted
FAIL_CITES = {'not-found', 'bad-doi', 'missing', 'retracted'}
REF_HEAD = re.compile(r'^(?:[\dIVX]{1,4}\.?\s+)?(?:references|bibliography|literature cited)$', re.I)
ACK_HEAD = re.compile(r'^(?:[\dA-Z]{1,3}\.?\s+)?acknowledge?ments?(?: and disclosure of funding)?[.:]?$', re.I)
AUTHOR = re.compile(r'\\author\s*(?:\[[^\]]*\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}')
PLACEHOLDER = re.compile(r'\\(?:guide|filler|todo)\b|\bTODO\b|\bFIXME\b|\bplaceholder-[\w-]+|\[AUTHORS:')
SELF_REF = re.compile(r'\b(?:our|my)\s+(?:previous|prior|earlier)\s+(?:work|paper|study|results?|method)\b'
                      r'|\bwe\s+(?:have\s+)?previously\s+(?:showed|shown|proposed|introduced|demonstrated|presented|reported)\b'
                      r'|\bin\s+our\s+(?:previous|prior|earlier)\b', re.I)
ID_URL = re.compile(r'\b(?:github\.com|gitlab\.com|bitbucket\.org|huggingface\.co)/(?!anonymous\b)[\w.-]+'
                    r'|\b[\w-]+\.github\.io\b|\bsites\.google\.com/[\w/.-]+|/~[\w.-]+', re.I)
AI_TOOL = (r'(?:LLMs?|large language models?|language models?|AI (?:assistant|system|tool)s?|generative AI|coding agents?'
           r'|Claude|ChatGPT|GPT-\d\w*|Copilot|Gemini)')
DISCLOSURE_HEAD = re.compile(r'\\(?:sub)*section\*?\s*\{[^}]*(?:' + AI_TOOL + r'|\bAI\b)', re.I)
ACK_SRC = re.compile(r'\\(?:sub)*section\*?\s*\{\s*Acknowledge?ments?|\\begin\{(?:ack|acks|acknowledge?ments?)\}', re.I)
VERBATIM = re.compile(r'\\begin\{(verbatim\*?|Verbatim\*?|lstlisting|minted|comment)\}.*?\\end\{\1\}|\\verb\*?([^\w\s]).*?\2', re.S)
FIGURE = re.compile(r'\\begin\{(figure\*?|teaserfigure)\}(.*?)\\end\{\1\}', re.S)

R = namedtuple('R', 'level group msg where fix')


# ------------------------------------------------------------------ inputs

def load_venue(vid):
    path = Path(vid) if vid.endswith('.json') else VENUES / f'{vid}.json'
    return json.loads(path.read_text(encoding='utf-8'))


def sources(main):
    """[(path relative to the main folder, text)] for main and every file it inputs; comments and verbatim
    blanked (templates show class options and file names in verbatim), line numbers kept."""
    blank = lambda m: '\n' * m[0].count('\n')  # noqa: E731
    return [(os.path.relpath(p, main.parent),
             VERBATIM.sub(blank, texmap.strip_comments(p.read_text(encoding='utf-8', errors='replace'))))
            for p, _ in texmap.walk(main, main.parent)]


def hits(srcs, rx):
    """(file:line, match) for every match of rx in the sources."""
    return [(f'{rel}:{text.count(chr(10), 0, m.start()) + 1}', m) for rel, text in srcs for m in rx.finditer(text)]


def pdf_pages(pdf):
    """Text of each page (pdftotext ends every page with a form feed), or None without poppler."""
    if not shutil.which('pdftotext'):
        return None
    pages = pdftool.run(['pdftotext', '-enc', 'UTF-8', str(pdf), '-']).stdout.split('\f')
    return pages[:-1] if pages and not pages[-1].strip() else pages


def pdf_meta(pdf):
    """pdftool.py info as a dict (Title, Author, Pages, PDF version, Fonts, ...)."""
    return {k.strip(): v.strip() for k, _, v in (l.partition(':') for l in pdftool.cmd_info(pdf).splitlines())}


def type3_fonts(pdf):
    if not shutil.which('pdffonts'):
        return []
    return sorted({l.split()[0] for l in pdftool.run(['pdffonts', str(pdf)]).stdout.splitlines()[2:] if ' Type 3 ' in l})


def find_pdf(main, given=None):
    if given:
        return Path(given) if Path(given).exists() else None
    cands = [main.parent / d / (main.stem + '.pdf') for d in ('.', 'build', 'out', '_build')]
    return next((p for p in cands if p.exists()), None)


# ------------------------------------------------------------------ checks

def capped(level, group, found, msg, fix):
    """One R per finding, the first SHOW only; the rest summarised in one line."""
    out = [R(level, group, msg(m), where, fix) for where, m in found[:SHOW]]
    if len(found) > SHOW:
        out.append(R(level, group, f'... and {len(found) - SHOW} more like these', found[SHOW][0], fix))
    return out


def body_pages(pages, uncounted=()):
    """Main-body length: pages before the first References heading (or a section the venue does not count),
    including the page it starts on when body text precedes it there. -> (pages, heading) or None."""
    ends = [REF_HEAD] + [re.compile(r'^(?:[\dA-Z]{1,3}\.?\s+)?' + re.escape(u) + r'[.:]?$', re.I) for u in uncounted]
    lines = [[l.strip() for l in p.splitlines() if l.strip()] for p in pages]
    norm = lambda l: re.sub(r'\d+', '#', l)  # noqa: E731  page and line numbers differ per page
    seen = Counter(n for page in lines for n in {norm(l) for l in page})
    running = {n for n, c in seen.items() if len(pages) >= 3 and c >= len(pages) / 2}  # headers, footers, numbers
    for i, page in enumerate(lines):
        body = False
        for l in page:
            if any(e.match(l) for e in ends):
                return i + body, l
            body = body or not (norm(l) in running or l.isdigit())
    return None


def check_pages(pages, venue, mode, limit=None):
    limit = limit or venue.get('pages', {}).get(mode)
    got = body_pages(pages, venue.get('pages', {}).get('uncounted', []))
    if got is None:
        level = 'FAIL' if limit and len(pages) > limit else 'WARN'
        return [R(level, 'format', f'pages: no References heading found in the PDF text; {len(pages)} pages in total'
                  + (f' (limit {limit} + references)' if limit else ''), '', 'check the page count by eye')]
    n, head = got
    if limit and n > limit:
        return [R('FAIL', 'format', f'pages: main body is {n} pages before "{head}" (limit {limit})', '',
                  f'cut or move material to the appendix; text spilling onto page {limit + 1} counts')]
    return [R('PASS', 'format', f'pages: main body {n} pages before "{head}"' + (f' (limit {limit})' if limit else ''), '', '')]


def check_fonts(meta, type3):
    out = []
    m = re.search(r'NOT embedded: (.*)', meta.get('Fonts', ''))
    if m:
        out.append(R('FAIL', 'format', f'fonts not embedded: {m[1]}', '',
                     'embed all fonts (pdflatex embeds by default; for figures re-export with fonts embedded)'))
    if type3:
        out.append(R('WARN', 'format', f'Type 3 (bitmap) fonts: {", ".join(type3[:5])}', '',
                     "matplotlib: rcParams['pdf.fonttype'] = 42 (or text.usetex) and re-export the figures"))
    return out or [R('PASS', 'format', 'fonts: all embedded, no Type 3', '', '')]


def check_style(main, doc, venue):
    st = venue.get('style')
    if not st:
        return []
    stem = Path(st['file']).stem
    if not re.search(r'\\(?:usepackage|documentclass)\s*(?:\[[^\]]*\])?\s*\{[^}]*\b' + re.escape(stem) + r'\b', doc):
        return [R('FAIL', 'format', f'{st["file"]} is not loaded (another year\'s or venue\'s template?)', '',
                  f'use the official template: {st["url"]}')]
    if not st.get('sha256'):
        return [R('PASS', 'format', f'template {st["file"]} loaded', '', '')]
    found = [p for p in main.parent.rglob(st['file']) if '.agentex' not in p.parts]
    if not found:
        return [R('WARN', 'format', f'{st["file"]} is not in the project folder: cannot check it is unmodified', '',
                  f'copy the official file from {st["url"]}')]
    bad = [p for p in found if results.sha(p) != st['sha256']]
    if bad:
        return [R('FAIL', 'format', f'{os.path.relpath(bad[0], main.parent)} differs from the official file ({st["why"]})',
                  os.path.relpath(bad[0], main.parent),
                  f're-download it from {st["url"]} and move your changes into the preamble '
                  f'(if the venue updated the file after {venue["checked"]}, update the sha256 in the venue file)')]
    return [R('PASS', 'format', f'{st["file"]} matches the official file', '', '')]


def check_mode(srcs, doc, venue, mode):
    blind = mode == 'submission' and venue.get('double_blind')
    switch = venue.get('switch', {})
    if venue.get('named_if'):
        named = re.search(venue['named_if'], doc)
        if blind and named:
            return [R('FAIL', 'anonymity', 'the class is in camera-ready/preprint mode: author names will show', '',
                      switch.get('submission', ''))]
        if mode == 'camera-ready' and not named:
            return [R('FAIL', 'anonymity', 'the class is still in anonymous review mode: no author names', '',
                      switch.get('camera-ready', ''))]
        return [R('PASS', 'anonymity', f'class options match {mode} mode', '', '')]
    authors = hits(srcs, AUTHOR)
    anon = [(w, m) for w, m in authors if not m[1].strip() or re.search(r'anonymous', m[1], re.I)]
    if blind and len(anon) < len(authors):
        return [R('FAIL', 'anonymity', '\\author names the authors in a double-blind submission',
                  authors[0][0], '\\author{Anonymous Authors} (or the class\'s anonymous option)')]
    if mode == 'camera-ready' and (not authors or anon):
        return [R('FAIL', 'anonymity', 'no author names in the camera-ready version',
                  authors[0][0] if authors else '', 'fill in \\author{...} with names and affiliations')]
    return [R('PASS', 'anonymity', 'authors match ' + mode + ' mode', '', '')] if authors else []


def check_anonymity(srcs, pages, meta, venue):
    out = []
    if meta.get('Author') and 'anonymous' not in meta['Author'].lower():
        out.append(R('FAIL', 'anonymity', f'PDF metadata Author is "{meta["Author"]}"', '',
                     '\\hypersetup{pdfauthor={}} or the class\'s anonymous mode; rebuild'))
    acks = [(f'PDF page {i + 1}', l) for i, p in enumerate(pages or []) for l in p.splitlines() if ACK_HEAD.match(l.strip())]
    if acks:
        out.append(R('FAIL' if venue.get('no_acks_in_submission') else 'WARN', 'anonymity',
                     'acknowledgements are visible in the submission PDF', acks[0][0],
                     'remove them for review (some classes hide them for you, e.g. the NeurIPS ack environment)'))
    out += capped('WARN', 'anonymity', hits(srcs, re.compile(r'\\thanks\b')), lambda m: '\\thanks may identify you',
                  'drop funding/affiliation notes until camera-ready')
    out += capped('WARN', 'anonymity', hits(srcs, ID_URL), lambda m: f'link may identify you: {m[0]}',
                  'if it is yours, use an anonymized copy (e.g. anonymous.4open.science)')
    out += capped('WARN', 'anonymity', hits(srcs, SELF_REF), lambda m: f'self-revealing phrase "{" ".join(m[0].split())}"',
                  'cite your own work in the third person ("Smith et al. showed")')
    return out or [R('PASS', 'anonymity', 'no identifying metadata, acknowledgements, links or phrases found', '', '')]


def check_rules(srcs, doc, venue, mode):
    out = []
    for r in venue.get('required', []):
        if mode in r.get('modes', MODES):
            ok = re.search(r['pattern'], doc)
            out.append(R('PASS' if ok else 'FAIL', 'policy', f'{r["what"]}: ' + ('present' if ok else f'missing ({r["why"]})'),
                         '', '' if ok else r.get('fix', '')))
    for r in venue.get('forbidden', []):
        if mode in r.get('modes', MODES):
            found = hits(srcs, re.compile(r['pattern']))
            if found:
                out.append(R('FAIL', 'policy', f'{r["what"]} present ({r["why"]})', found[0][0], r.get('fix', '')))
    return out


def disclosure_found(doc):
    if DISCLOSURE_HEAD.search(doc):
        return True
    for m in ACK_SRC.finditer(doc):
        section = re.split(r'\\(?:section|end\{ack|bibliography|printbibliography)', doc[m.end():m.end() + 4000])[0]
        if re.search(AI_TOOL, section, re.I):
            return True
    return False


def check_disclosure(doc, venue, mode, edits):
    d = venue.get('llm_disclosure') or {}
    if not d.get('required'):
        return [R('PASS', 'policy', f'LLM-use disclosure not required by {venue["id"]}: {d.get("why", "")}'.rstrip(': '), '', '')]
    if mode not in d.get('modes', MODES):
        return [R('WARN', 'policy', f'declare LLM use in {d["where"]}', '', d.get('why', ''))]
    if disclosure_found(doc):
        return [R('PASS', 'policy', 'LLM-use disclosure present', '', '')]
    fix = f'python3 {HERE / "disclosure.py"} <project>, edit the draft, put it in {d["where"]}'
    if edits:
        added = sum(int(e.get('added_lines', 0)) for e in edits)
        return [R('FAIL', 'policy', f'no LLM-use disclosure, but the agent logged {len(edits)} edits (+{added} lines) '
                  f'({d["why"]})', '', fix)]
    return [R('WARN', 'policy', f'no LLM-use disclosure found; required if an LLM generated content ({d["why"]})', '', fix)]


def check_acm(srcs, venue):
    out = []
    if venue.get('figure_description'):
        bare = [(f'{rel}:{text.count(chr(10), 0, m.start()) + 1}', m) for rel, text in srcs
                for m in FIGURE.finditer(text) if '\\Description' not in m[2]]
        out += capped('FAIL', 'policy', bare, lambda m: f'{m[1]} without \\Description{{}} alt text',
                      'add \\Description{one-sentence description of the figure}')
    taps = venue.get('taps')
    if taps:
        pkgs = [(w, p.strip()) for w, m in hits(srcs, texmap.PACKAGE) for p in m[1].split(',') if p.strip()]
        out += capped('FAIL', 'policy', [x for x in pkgs if x[1] not in taps['accepted'] and x[1] not in taps['in_acmart']],
                      lambda p: f'package {p} is not on the TAPS accepted list (list updated {taps["page_updated"]})',
                      'remove it or replace it (ship figures as PDF); ask acmtexsupport@aptaracorp.com if needed')
        out += capped('WARN', 'policy', [x for x in pkgs if x[1] in taps['in_acmart'] and x[1] not in taps['accepted']],
                      lambda p: f'package {p} is already loaded by acmart', 'remove the \\usepackage line')
    return out


def check_ieee(doc, meta, venue):
    out = []
    lo_hi = venue.get('pdf_version')
    v = meta.get('PDF version')
    if lo_hi and v and not lo_hi[0] <= v <= lo_hi[1]:
        out.append(R('FAIL', 'format', f'PDF version {v} (IEEE Xplore accepts {lo_hi[0]}-{lo_hi[1]})', '',
                     '\\pdfminorversion=7 at the top of the preamble (pdflatex), or let PDF eXpress convert it'))
    if venue.get('no_links') and re.search(r'\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*\bhyperref\b', doc):
        out.append(R('WARN', 'format', 'hyperref adds links and bookmarks, which IEEE Xplore PDFs must not contain', '',
                     '\\usepackage[draft]{hyperref} (or remove it) for the final PDF; PDF eXpress reports the rest'))
    return out


def check_citations(main, srcs, verify=False):
    if verify:
        try:
            subprocess.run([sys.executable, str(CITE_VERIFY), str(main.parent)], capture_output=True, timeout=1800)
        except subprocess.TimeoutExpired:
            pass  # report from whatever the cache holds
    cache_file = find_up(main.parent, '.agentex/cite-cache.json')
    cited = {}
    for rel, text in srcs:
        for k, where in check_refs.scan(check_refs.CITE_RE, text, rel):
            cited.setdefault(k, where)
    cited.pop('*', None)
    if not cited:
        return []
    fix = f'python3 {CITE_VERIFY} {os.path.relpath(main.parent)}'
    if not cache_file:
        return [R('WARN', 'integrity', f'{len(cited)} cited keys never verified against bibliographic databases', '', fix)]
    root = cache_file.parent.parent
    cache = cite_verify.load_cache(root)
    bibs = [root / b for b in cache.get('bibs', [])] or cite_verify.project_files(main.parent)[1]
    entries = {e['key']: e for b in bibs if b.exists()
               for e in cite_verify.parse_bib(b.read_text(encoding='utf-8', errors='replace'))}
    status = {}
    for k in cited:
        known = cache.get('keys', {}).get(k)
        if k not in entries:
            status[k] = ('missing', 'cited but not in any .bib file')
        elif not known or known.get('fp') != cite_verify.fingerprint(entries[k]):
            status[k] = ('unchecked', 'not verified since the entry was added or changed')
        else:
            status[k] = (known['status'], cache.get('entries', {}).get(known['fp'], {}).get('message', ''))
    bad = [(cited[k], (k, s, msg)) for k, (s, msg) in sorted(status.items()) if s in FAIL_CITES]
    doubt = [(cited[k], (k, s, msg)) for k, (s, msg) in sorted(status.items()) if s in {'mismatch', 'unverifiable', 'unchecked'}]
    say = lambda x: f'citation {x[0]}: {x[1]}' + (f' ({x[2]})' if x[2] else '')  # noqa: E731
    out = capped('FAIL', 'integrity', bad, say, 'replace it with a verified source or remove the claim; never guess')
    out += capped('WARN', 'integrity', doubt, say, fix + ' --suggest (then fix by hand what stays unverifiable)')
    ok = len(cited) - len(bad) - len(doubt)
    return out + [R('PASS', 'integrity', f'citations: {ok} of {len(cited)} verified', '', '')]


def check_refs_and_text(main, srcs, pages):
    out = []
    report = check_refs.analyse(main.parent)
    for kind in ('undefined reference', 'duplicate label', 'duplicate bib key'):
        found = [(locs[0], k) for k, locs in sorted(report['errors'][kind].items()) if '#' not in k]  # skip macro args
        out += capped('FAIL', 'integrity', found, lambda k, kind=kind: f'{kind}: {k}', 'fix the label or the \\ref')
    qq = [i + 1 for i, p in enumerate(pages or []) if '??' in p]
    if qq:
        out.append(R('WARN', 'integrity', f'"??" in the PDF on page(s) {", ".join(map(str, qq[:5]))}', '',
                     'rebuild (bibtex/biber + 2 LaTeX runs); then fix what is still undefined'))
    out += capped('FAIL', 'integrity', hits(srcs, PLACEHOLDER), lambda m: f'leftover placeholder {m[0]}',
                  'replace it with real content, or delete it')
    packer = arxiv_pack.Packer(main)
    packer.scan(packer.main)
    # arxiv_pack also reads verbatim blocks; keep only files the (verbatim-free) source really names
    missing = [('', e) for e in packer.errors if e.startswith('missing file') and '#' not in e.split('"')[1]
               and e.split('"')[1] in '\n'.join(t for _, t in srcs)]
    out += capped('FAIL', 'integrity', missing, lambda e: e,
                  'fix the path (letter case matters on Linux build servers) or add the file')
    out += capped('WARN', 'integrity', [('', e) for e in packer.errors if not e.startswith('missing file')], lambda e: e,
                  'keep every file inside the project folder with relative, exact-case paths')
    reg, findings = results.audit(main.parent)
    if reg:
        out += capped('FAIL', 'integrity', [(f'{f}:{line}', (kind, tok, msg)) for kind, f, line, tok, msg in findings
                                            if kind in ('STALE', 'UNDEFINED')],
                      lambda x: f'{x[0].lower()} number {x[1]}: {x[2]}', 'use the \\res{} macro from the registry')
        out += capped('WARN', 'integrity', [(f'{f}:{line}', (tok, msg)) for kind, f, line, tok, msg in findings
                                            if kind == 'HARD-CODED'],
                      lambda x: f'hard-coded number {x[0]} {x[1]}', 'replace it with the \\res{} macro')
    return out or [R('PASS', 'integrity', 'no undefined refs, placeholders or missing files', '', '')]


# ------------------------------------------------------------------ run

def run(main, venue, mode='submission', pdf=None, page_limit=None, verify=False, build=True):
    """-> (results, pdf path or None)."""
    out = []
    checked = date.fromisoformat(venue['checked'])
    if not venue.get('verified') or (date.today() - checked).days > STALE_RULES_DAYS:
        out.append(R('WARN', 'policy', f'{venue["id"]} rules were checked on {venue["checked"]}'
                     + ('' if venue.get('verified') else ' and are not verified'), '',
                     'confirm page limits and policies against the current call: ' + ', '.join(venue.get('sources', [])[:2])))
    srcs = sources(main)
    doc = '\n'.join(t for _, t in srcs)
    path = find_pdf(main, pdf)
    if path is None and build and not pdf:
        r = subprocess.run([sys.executable, str(BUILD), str(main)], capture_output=True, text=True, timeout=600)
        path = find_pdf(main)
        if path is None:
            out.append(R('FAIL', 'format', 'no PDF: the build failed', main.name,
                         'fix the build first: ' + ' | '.join(r.stdout.strip().splitlines()[:3])))
    pages = meta = None
    if path:
        newest = max(main.parent.joinpath(rel).stat().st_mtime for rel, _ in srcs)
        if path.stat().st_mtime < newest:
            out.append(R('WARN', 'format', f'{path.name} is older than the sources', path.name, 'rebuild before checking'))
        pages, meta = pdf_pages(path), pdf_meta(path)
        if pages is None:
            out.append(R('WARN', 'format', 'pdftotext not found: page count and PDF text checks skipped', '',
                         'install poppler (brew install poppler)'))
        else:
            out += check_pages(pages, venue, mode, page_limit)
        out += check_fonts(meta, type3_fonts(path))
        out += check_ieee(doc, meta, venue)
    out += check_style(main, doc, venue)
    out += check_mode(srcs, doc, venue, mode)
    if mode == 'submission' and venue.get('double_blind'):
        out += check_anonymity(srcs, pages, meta or {}, venue)
    out += check_rules(srcs, doc, venue, mode)
    out += check_disclosure(doc, venue, mode, read_activity(main.parent))
    if mode == 'camera-ready':
        out += check_acm(srcs, venue)
    out += check_citations(main, srcs, verify)
    out += check_refs_and_text(main, srcs, pages)
    return out, path


def report(main, venue, mode, res):
    lines = [f'preflight {main.name} · {venue["id"]} ({venue["name"]}) · {mode} · rules checked {venue["checked"]}']
    for g in GROUPS:
        rows = sorted((r for r in res if r.group == g), key=lambda r: ('FAIL', 'WARN', 'PASS').index(r.level))
        if rows:
            lines.append(g.upper())
        for r in rows:
            lines.append(f'  {r.level}  {r.msg}' + (f'  [{r.where}]' if r.where else ''))
            if r.fix and r.level != 'PASS':
                lines.append(f'        fix: {r.fix}')
    counts = {k.lower(): sum(r.level == k for r in res) for k in ('FAIL', 'WARN', 'PASS')}
    lines.append(' · '.join(f'{v} {k}' for k, v in counts.items()) + (' -> NOT ready to submit' if counts['fail'] else ''))
    return '\n'.join(lines), counts


def write_status(main, venue, mode, res, counts):
    status = 'fail' if counts['fail'] else 'warn' if counts['warn'] else 'ok'
    items = [{'where': r.where or main.name, 'message': f'{r.level}: {r.msg}'}
             for lvl in ('FAIL', 'WARN') for r in res if r.level == lvl]
    try:
        cite_verify.write_status(agentex_root(main.parent), 'preflight', status,
                                 f'{venue["id"]} {mode}: {counts["fail"]} fail, {counts["warn"]} warn, {counts["pass"]} pass',
                                 counts, items)
    except OSError:
        pass  # the dashboard is cosmetic; the printed report is what counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tex', type=Path, nargs='?')
    ap.add_argument('--venue', default='default', help="venue id from <skill>/venues, a .json path, or 'list'")
    ap.add_argument('--mode', default='submission', choices=MODES)
    ap.add_argument('--pdf', type=Path)
    ap.add_argument('--page-limit', type=int, help="override the venue's limit (e.g. short papers, other tracks)")
    ap.add_argument('--verify-citations', action='store_true', help='run cite_verify.py first (network)')
    ap.add_argument('--no-build', action='store_true', help='never compile; skip PDF checks if there is no PDF')
    a = ap.parse_args(argv)
    if a.venue == 'list':
        for p in sorted(VENUES.glob('*.json')):
            v = json.loads(p.read_text(encoding='utf-8'))
            print(f'{v["id"]:18s} checked {v["checked"]}  {v["name"]}')
        return 0
    for f in (a.tex, a.pdf):
        if f is not None and not f.exists():
            print(f'not found: {f}')
            return 2
    if not a.tex:
        print('give the main .tex file')
        return 2
    try:
        venue = load_venue(a.venue)
    except (OSError, ValueError) as e:
        print(f'unknown venue {a.venue!r} ({e}); see --venue list')
        return 2
    main_tex = a.tex.resolve()
    res, _ = run(main_tex, venue, a.mode, a.pdf, a.page_limit, a.verify_citations, not a.no_build)
    text, counts = report(main_tex, venue, a.mode, res)
    print(text)
    write_status(main_tex, venue, a.mode, res, counts)
    return 1 if counts['fail'] else 0


if __name__ == '__main__':
    sys.exit(main())
