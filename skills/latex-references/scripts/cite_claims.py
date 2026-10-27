#!/usr/bin/env python3
"""Citation faithfulness: does each cited source say what the citing sentence claims?

Usage:
  cite_claims.py extract paper/                  # every \\cite -> its sentence; cited abstracts fetched once
  cite_claims.py next [--dir paper/] [--n 5]     # pending claims + cited abstracts, for the agent to judge
  cite_claims.py record ID [ID ...] --verdict supported|not-in-abstract|contradicted|unclear [--note TEXT] [--dir paper/]
  cite_claims.py report [--dir paper/]           # counts + contradicted / not-in-abstract claims with file:line

Claims are judged against abstracts only, so not-in-abstract means "check the full text", not
"wrong"; the author decides. A claim id hashes the sentence and its keys, so verdicts survive
re-extraction until the sentence changes. Abstracts come from arXiv, Crossref, OpenAlex (DOI lookup,
else title search) and finally the entry's own abstract field. Writes only .agentex/claims.json,
.agentex/abstracts.json and .agentex/status/cite-claims.json; never edits .tex or .bib.
report exits 1 if any claim is contradicted. Stdlib only.
"""
import argparse
import bisect
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cite_verify as cv  # noqa: E402  (same folder; tests patch cv.http)
from check_refs import CITE_RE, REF_RE, strip_comments  # noqa: E402

VERDICTS = ('supported', 'not-in-abstract', 'contradicted', 'unclear')
ABSTRACT_CHARS = 1200  # per cited work in `next`: most abstracts fit whole, long ones are cut
SENTENCE_CHARS = 600  # a "sentence" longer than this (no full stop) is cut to a window around the cite
INPUT_RE = re.compile(r'\\(?:input|include|subfile)\s*\{([^}]+)\}')
STANDALONE = re.compile(r'\\documentclass\s*(?:\[[^\]]*\])?\s*\{standalone\}')
ABBREV = ('e.g', 'i.e', 'al', 'cf', 'vs', 'Fig', 'Figs', 'Eq', 'Eqs', 'Sec', 'Tab', 'Ref', 'resp', 'approx')
# Where a sentence starts or ends: paragraph breaks, environments, headings, items, captions and
# footnotes, and . ! ? before whitespace unless they close an abbreviation.
BOUNDARY = re.compile(
    r'\n[ \t]*\n|\\(?:begin|end)\s*\{[^}]*\}'
    r'|\\(?:part|chapter|(?:sub)*section|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}'
    r'|\\(?:item|caption|footnote)\b'
    r'|' + ''.join(rf'(?<!\b{re.escape(a)})' for a in ABBREV) + r'[.!?](?=\s|$)')


def read(p):
    return p.read_text(encoding='utf-8', errors='replace')


def tex_files(root):
    """Main documents and their \\input tree in reading order; every .tex file if there is no main."""
    every = sorted(p for p in root.rglob('*.tex') if not set(p.relative_to(root).parts) & cv.SKIP_DIRS)
    order = []

    def visit(p, base):
        if p in order or not p.is_file():
            return
        order.append(p)
        for m in INPUT_RE.finditer(strip_comments(read(p))):
            name = m[1].strip() if Path(m[1].strip()).suffix else m[1].strip() + '.tex'
            visit(base / name if (base / name).exists() else p.parent / name, base)  # LaTeX resolves from the main file's folder

    for p in every:
        t = strip_comments(read(p))
        if '\\documentclass' in t and '\\begin{document}' in t and not STANDALONE.search(t):
            visit(p, p.parent)
    return order or every


def cite_keys(m):
    return sorted({k.strip() for k in m[1].split(',') if k.strip()} - {'*'})


def plain(tex):
    """LaTeX fragment -> readable text; citations become [key, key]."""
    tex = CITE_RE.sub(lambda m: '[' + ', '.join(cite_keys(m)) + ']', tex)
    tex = REF_RE.sub('[ref]', re.sub(r'\\label\s*\{[^}]*\}', ' ', tex))
    tex = re.sub(r'\\[A-Za-z]{2,}\*?', ' ', tex)  # drop macro names first: detex is tuned for titles and reads \textbf as an accent
    return cv.detex(tex)


def claims_in(path, root):
    """[(id, claim)] for every \\cite in one file (\\nocite has no sentence)."""
    text = strip_comments(read(path))
    bounds = list(BOUNDARY.finditer(text))
    starts, ends = [b.start() for b in bounds], [b.end() for b in bounds]
    out = []
    for m in CITE_RE.finditer(text):
        keys = cite_keys(m)
        if m[0].startswith('\\nocite') or not keys:
            continue
        i, j = bisect.bisect_right(ends, m.start()), bisect.bisect_left(starts, m.end())
        s0 = ends[i - 1] if i else 0
        s1 = len(text) if j == len(bounds) else bounds[j].end() if text[starts[j]] in '.!?' else starts[j]
        if s1 - s0 > SENTENCE_CHARS:
            s0, s1 = max(s0, m.start() - SENTENCE_CHARS // 2), min(s1, m.end() + SENTENCE_CHARS // 2)
        sentence = plain(text[s0:s1])
        cid = 'c' + hashlib.sha1(json.dumps([sentence, keys]).encode()).hexdigest()[:8]
        out.append((cid, {'where': f'{path.relative_to(root)}:{text.count(chr(10), 0, m.start()) + 1}',
                          'keys': keys, 'sentence': sentence, 'verdict': None, 'note': ''}))
    return out


# ---------------------------------------------------------------- abstracts

def jats(s):
    """Crossref abstracts are JATS XML ('<jats:title>Abstract</jats:title><jats:p>...')."""
    return ' '.join(html.unescape(re.sub(r'<jats:title>.*?</jats:title>|<[^>]+>', ' ', s or '', flags=re.S)).split())


def inverted(index):
    """OpenAlex ships abstracts as {word: [positions]}; put the words back in order."""
    return ' '.join(w for _, w in sorted((p, w) for w, ps in (index or {}).items() for p in ps))


def openalex_abstract(doi, title):
    """By DOI (a free single-record lookup), else by title (a search: costs OpenAlex's daily budget)."""
    if doi:
        body = cv.http(f'https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}?select=abstract_inverted_index')
        return inverted(json.loads(body or '{}').get('abstract_inverted_index'))
    body = cv.http('https://api.openalex.org/works?' + urllib.parse.urlencode(
        {'search': title, 'per-page': 3, 'select': 'title,abstract_inverted_index'}))
    for w in json.loads(body or '{}').get('results', []):
        if SequenceMatcher(None, cv.norm_title(w.get('title') or ''), cv.norm_title(title)).ratio() >= 0.9:
            return inverted(w.get('abstract_inverted_index'))
    return ''


def fetch_abstracts(root, keys, L, store):
    """Fill store[key] = {fp, abstract, source} for cited keys that are new or whose entry changed."""
    entries = {e['key']: e for b in cv.project_files(root)[1] for e in cv.parse_bib(read(b))}
    verified = cv.load_cache(root)['entries']  # cite_verify's match is the authority on which work this is
    todo = []
    for k in sorted(keys & set(entries)):
        e, fp = entries[k], cv.fingerprint(entries[k])
        if store.get(k, {}).get('fp') == fp:
            continue
        r = (verified.get(fp) or {}).get('record') or {}
        doi = cv.clean_doi(r.get('doi') or e['fields'].get('doi', ''))
        todo.append((k, e, fp, '' if doi.lower().startswith('10.48550/') else doi, r.get('arxiv') or cv.arxiv_id(e['fields'])))
    try:
        L.prefetch_arxiv([ax for *_, ax in todo if ax])  # one request per 50 ids
    except Exception as ex:
        print(f'  arXiv unavailable: {ex}', file=sys.stderr)
    for k, e, fp, doi, ax in todo:
        print(f'  abstract for {k} ...', file=sys.stderr)
        title, failed = cv.detex(e['fields'].get('title', '')), False
        sources = (('arxiv', lambda: L.arxiv_abstracts.get(ax, '') if ax else ''),
                   ('crossref', lambda: jats((L.crossref_work(doi) or {}).get('abstract')) if doi else ''),
                   ('openalex', lambda: openalex_abstract(doi or (f'10.48550/arXiv.{ax}' if ax else ''), title) if doi or ax or title else ''))
        for source, fetch in sources:
            try:
                text = fetch()
            except Exception as ex:
                print(f'  {source} failed for {k}: {ex}', file=sys.stderr)
                text, failed = '', True
            if text:
                break
        else:
            text = plain(e['fields'].get('abstract', ''))
            source = 'bib' if text else 'none'
        if text or not failed:  # a network failure is retried on the next extract
            store[k] = {'fp': fp, 'abstract': text, 'source': source}


# ---------------------------------------------------------------- storage + status

def load(root, name):
    try:
        return json.loads((root / '.agentex' / name).read_text())
    except (OSError, ValueError):
        return {}


def save(root, name, data):
    tmp = cv.agentex_dir(root) / (name + '.tmp')
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, root / '.agentex' / name)


def tally(claims):
    counts = dict.fromkeys(VERDICTS + ('pending',), 0)
    for c in claims.values():
        counts[c['verdict'] or 'pending'] += 1
    return counts


def flagged(claims):
    return [(cid, c) for v in ('contradicted', 'not-in-abstract') for cid, c in claims.items() if c['verdict'] == v]


def write_status(root, claims):
    counts = tally(claims)
    status = 'fail' if counts['contradicted'] else 'ok' if counts['supported'] == len(claims) else 'warn'
    cv.write_status(root, 'cite-claims', status,
                    f'{len(claims)} cited claims: ' + ', '.join(f'{n} {v}' for v, n in counts.items() if n),
                    counts, [{'where': c['where'], 'message': f"{c['verdict']}: {c['sentence'][:150]}"} for _, c in flagged(claims)])


def stored_claims(root):
    claims = load(root, 'claims.json').get('claims')
    if claims is None:
        raise SystemExit(f'no claims under {root}: run `cite_claims.py extract {root}` first')
    return claims


# ---------------------------------------------------------------- commands

def extract(root, L=None):
    root = root.resolve()
    files = tex_files(root)
    claims = {}
    for p in files:
        for cid, c in claims_in(p, root):
            claims.setdefault(cid, c)  # the same sentence citing the same keys twice is one claim
    old = load(root, 'claims.json').get('claims', {})
    kept = 0
    for cid, c in claims.items():
        if old.get(cid, {}).get('verdict'):
            c.update(verdict=old[cid]['verdict'], note=old[cid]['note'])
            kept += 1
    save(root, 'claims.json', {'version': 1, 'claims': claims})
    write_status(root, claims)
    keys = {k for c in claims.values() for k in c['keys']}
    store = load(root, 'abstracts.json').get('abstracts', {})
    fetch_abstracts(root, keys, L or cv.Lookups(), store)
    save(root, 'abstracts.json', {'version': 1, 'abstracts': store})
    have = [k for k in keys if store.get(k, {}).get('abstract')]
    sources = {}
    for k in have:
        sources[store[k]['source']] = sources.get(store[k]['source'], 0) + 1
    lacking = sorted(keys - set(have))
    return '\n'.join(filter(None, [
        f'{len(claims)} cited claims in {len(files)} files ({kept} keep their verdicts) · abstracts for {len(have)}/{len(keys)} keys'
        + (f" ({', '.join(f'{s} {n}' for s, n in sorted(sources.items()))})" if sources else ''),
        f"no abstract (judge by hand or mark unclear): {', '.join(lacking[:15])}{' …' if len(lacking) > 15 else ''}" if lacking else '',
        f'next: cite_claims.py next --dir {root}']))


def cut(text, n):
    return text if len(text) <= n else text[:n].rsplit(' ', 1)[0] + ' …'


def next_items(root, n=5):
    claims = stored_claims(root)
    pending = [(cid, c) for cid, c in claims.items() if not c['verdict']]
    if not pending:
        return 'no pending claims: run `cite_claims.py report`'
    batch, store = pending[:n], load(root, 'abstracts.json').get('abstracts', {})
    status = {k: v.get('status') for k, v in cv.load_cache(root).get('keys', {}).items()}
    out = [f'{len(batch)} of {len(pending)} pending. Does each cited abstract support the sentence? Then:',
           f'  cite_claims.py record <id> [<id> ...] --verdict {"|".join(VERDICTS)} [--note "..."] --dir {root}']
    out += [f'\n[{cid}] {c["where"]}\n  {c["sentence"]}' for cid, c in batch]
    out.append('\nabstracts:')
    for k in dict.fromkeys(k for _, c in batch for k in c['keys']):
        a = store.get(k) or {}
        flag = ' [RETRACTED]' if status.get(k) == 'retracted' else ''
        out.append(f"- {k}{flag} ({a['source']}): {cut(a['abstract'], ABSTRACT_CHARS)}" if a.get('abstract') else
                   f"- {k}{flag}: ({'no abstract found' if a else 'not in any .bib file'})")
    return '\n'.join(out)


def record(root, ids, verdict, note=''):
    data = load(root, 'claims.json')
    claims = stored_claims(root)
    unknown = [i for i in ids if i not in claims]
    if unknown:
        raise SystemExit(f"unknown claim id(s): {', '.join(unknown)} (ids come from `next`; re-run `next` after extract)")
    for i in ids:
        claims[i].update(verdict=verdict, note=note)
    save(root, 'claims.json', dict(data, claims=claims))
    write_status(root, claims)
    return f"recorded {verdict} for {len(ids)} claim(s); {tally(claims)['pending']} pending"


def report(root):
    claims = stored_claims(root)
    counts = tally(claims)
    write_status(root, claims)
    out = [f'{len(claims)} cited claims: ' + ' · '.join(f'{v} {n}' for v, n in counts.items() if n)]
    for cid, c in flagged(claims):
        out.append(f"{c['verdict'].upper():16s} {c['where']}  [{', '.join(c['keys'])}] {cut(c['sentence'], 160)}"
                   + (f"  -- {c['note']}" if c['note'] else ''))
    if counts['not-in-abstract'] or counts['contradicted']:
        out.append('Abstract-level check only: read the full text before changing a claim. The author decides; nothing was edited.')
    return '\n'.join(out), counts['contradicted']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('extract', help='find citing sentences, fetch abstracts').add_argument('dir', type=Path)
    nx = sub.add_parser('next', help='pending claims with abstracts')
    nx.add_argument('--n', type=int, default=5)
    rc = sub.add_parser('record', help='store a verdict')
    rc.add_argument('ids', nargs='+')
    rc.add_argument('--verdict', required=True, choices=VERDICTS)
    rc.add_argument('--note', default='')
    rp = sub.add_parser('report', help='counts and flagged claims')
    for p in (nx, rc, rp):
        p.add_argument('--dir', type=Path, default=Path('.'), help='the paper folder given to extract (default: .)')
    args = ap.parse_args(argv)
    root = args.dir.resolve()
    if not root.is_dir():
        ap.error(f'not a folder: {args.dir}')
    if args.cmd == 'extract':
        print(extract(root))
    elif args.cmd == 'next':
        print(next_items(root, args.n))
    elif args.cmd == 'record':
        print(record(root, args.ids, args.verdict, args.note))
    else:
        text, contradicted = report(root)
        print(text)
        return 1 if contradicted else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
