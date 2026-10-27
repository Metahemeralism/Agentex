#!/usr/bin/env python3
"""Verify cited BibTeX entries against authoritative databases (catches fabricated references).

Usage:
  cite_verify.py paper/                       # every cited key
  cite_verify.py paper/ --all                 # every entry in the .bib files
  cite_verify.py paper/ --keys k1,k2          # only these keys (fast; what the cite-guard hook asks for)
  cite_verify.py paper/ --suggest             # corrected entries -> .agentex/suggested.bib; your .bib is never edited

Resolves DOIs (Crossref), arXiv ids (arXiv API) and titles (DBLP, Crossref, OpenAlex), fuzzy-matches
title, authors and year, and classifies each entry:
  verified      found; metadata agrees
  published     arXiv preprint that has a published version (consider citing it)
  mismatch      the work exists but title/authors/year in your entry are wrong
  bad-doi       the DOI/arXiv id does not resolve, or resolves to a different work
  not-found     no match anywhere: likely fabricated, check by hand
  retracted     the work was retracted, withdrawn or removed (Crossref + Retraction Watch)
  unverifiable  book/thesis/software/web entry not indexed: check by hand
Corrections, errata and expressions of concern are printed as NOTICE lines (warnings, not failures).
Results are cached in <project>/.agentex/cite-cache.json; full runs (no --keys) also write
.agentex/status/citations.json. Exit code 1 if anything is not verified (mismatch, bad-doi,
not-found, missing, retracted) or if two keys cite the same work. Stdlib only.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_refs import CITE_RE, scan, strip_comments  # noqa: E402  (same folder)

MAILTO = os.environ.get('AGENTEX_MAILTO', '')
UA = 'AgenTeX-cite-verify/0.3 (https://github.com/Metahemeralism/AgenTeX' + (f'; mailto:{MAILTO})' if MAILTO else ')')
CHECKABLE = {'article', 'inproceedings', 'conference', 'incollection', 'proceedings'}
OK_STATUSES = {'verified', 'published'}
ARXIV_NEW = re.compile(r'(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?')
ARXIV_OLD = re.compile(r'\b([a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?')
MONTHS = {m: m for m in 'jan feb mar apr may jun jul aug sep oct nov dec'.split()}
BIBFILE_RE = re.compile(r'\\(?:addbibresource|bibliography)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}')
SKIP_DIRS = {'.git', '.agentex', 'arxiv_submission'}
# Crossref update types (live check 2026-10-26): Retraction Watch notices use retraction, correction and
# expression_of_concern; publishers also deposit withdrawal, removal, partial_retraction, erratum, corrigendum.
RETRACTING = {'retraction', 'withdrawal', 'removal'}
FLAGGING = {'partial_retraction', 'expression_of_concern', 'correction', 'corrigendum', 'erratum'}


# ---------------------------------------------------------------- BibTeX parsing

def _braced(s, i):
    """s[i] == '{': return (inner text, index after the closing brace)."""
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == '\\':
            j += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


def _quoted(s, i):
    depth, j = 0, i + 1
    while j < len(s) and not (s[j] == '"' and depth == 0):
        if s[j] == '\\':
            j += 2
            continue
        depth += (s[j] == '{') - (s[j] == '}')
        j += 1
    return s[i + 1:j], j + 1


def parse_fields(s, strings):
    fields, i = {}, 0
    name_re, bare_re, cat_re = re.compile(r'[\s,]*([\w:.+-]+)\s*=\s*'), re.compile(r'[^\s,#}]+'), re.compile(r'\s*#\s*')
    while i < len(s):
        m = name_re.match(s, i)
        if not m:
            break
        name, i, parts = m[1].lower(), m.end(), []
        while i < len(s):
            if s[i] == '{':
                part, i = _braced(s, i)
            elif s[i] == '"':
                part, i = _quoted(s, i)
            else:
                b = bare_re.match(s, i)
                if not b:
                    break
                part, i = strings.get(b[0].lower(), MONTHS.get(b[0].lower(), b[0])), b.end()
            parts.append(part)
            c = cat_re.match(s, i)
            if not c:
                break
            i = c.end()
        fields[name] = ''.join(parts).strip()
    return fields


def parse_bib(text):
    """Return [{type, key, fields, line}]; @string macros are expanded, @comment/@preamble skipped."""
    entries, strings, i = [], {}, 0
    head = re.compile(r'@\s*(\w+)\s*([{(])')
    while True:
        at = text.find('@', i)
        if at < 0:
            break
        m = head.match(text, at)
        if not m:
            i = at + 1
            continue
        etype, close = m[1].lower(), '}' if m[2] == '{' else ')'
        depth, k = 0, m.end()
        while k < len(text):
            c = text[k]
            if c == '\\':
                k += 2
                continue
            if c == '{':
                depth += 1
            elif c == '}' and depth:
                depth -= 1
            elif c == close and depth == 0:
                break
            k += 1
        body, i = text[m.end():k], k + 1
        if etype == 'string':
            strings.update({n: v for n, v in parse_fields(body, strings).items()})
        elif etype not in ('comment', 'preamble'):
            key, _, rest = body.partition(',')
            entries.append({'type': etype, 'key': key.strip(), 'fields': parse_fields(rest, strings),
                            'line': text.count('\n', 0, at) + 1})
    return entries


# ---------------------------------------------------------------- normalisation

ACCENT = re.compile(r'\\[`\'^"~=.uvHtcdbrk]\s*\{?\s*\\?([A-Za-z])\}?')


def detex(s):
    s = ACCENT.sub(r'\1', s or '')
    s = re.sub(r'\\(ss|ae|oe|aa|o|l)\b', r'\1', s, flags=re.I)
    s = re.sub(r'\\[a-zA-Z]+\*?|[{}$~\\]', ' ', s)
    s = unicodedata.normalize('NFKD', s)
    return ' '.join(''.join(c for c in s if not unicodedata.combining(c)).split())


def norm_title(t):
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', detex(t).lower()).split())


def surname(name):
    name = detex(name).strip()
    last = name.split(',')[0] if ',' in name else (name.split() or [''])[-1]
    return re.sub(r'[^a-z]', '', last.lower().split()[-1] if last.split() else '')


def bib_surnames(field):
    names = [n for n in re.split(r'\s+and\s+', field or '') if n.strip() and n.strip().lower() != 'others']
    return [s for s in (surname(n) for n in names) if s]


def clean_doi(doi):
    return re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', (doi or '').strip(), flags=re.I)


def arxiv_id(f):
    """arXiv id from eprint/doi/url/journal/note fields, if any."""
    doi = clean_doi(f.get('doi', ''))
    if doi.lower().startswith('10.48550/arxiv.'):
        return doi[len('10.48550/arxiv.'):]
    eprint = f.get('eprint', '')
    if eprint and (f.get('archiveprefix', 'arxiv').lower() == 'arxiv' or f.get('eprinttype', '').lower() == 'arxiv'):
        m = ARXIV_NEW.search(eprint) or ARXIV_OLD.search(eprint)
        if m:
            return m[1]
    for field in ('url', 'journal', 'note', 'howpublished', 'journaltitle'):
        v = f.get(field, '')
        if 'arxiv' in v.lower():
            m = ARXIV_NEW.search(v) or ARXIV_OLD.search(v)
            if m:
                return m[1]
    return ''


def fingerprint(e):
    f = e['fields']
    blob = [e['type'], norm_title(f.get('title', '')), bib_surnames(f.get('author', '')),
            f.get('year', '') or f.get('date', '')[:4], clean_doi(f.get('doi', '')).lower(), arxiv_id(f)]
    return hashlib.sha1(json.dumps(blob).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- lookups (network)

def http(url, accept='application/json', tries=3, timeout=25, headers=None):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode('utf-8', 'replace')
                if accept == 'application/json' and body.lstrip()[:1] not in ('{', '['):
                    raise ValueError(f'non-JSON reply from {urllib.parse.urlparse(url).netloc} (bot check or outage)')
                return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(min(int(e.headers.get('Retry-After') or 3 * (attempt + 1)), 10))
                continue
            raise
        except urllib.error.URLError:
            if attempt < tries - 1:
                time.sleep(2)
                continue
            raise
    return None


def rec(title, authors, year, venue='', doi='', arxiv='', source='', url='', dblp_key='', bibtex='', updates=None):
    """updates: Crossref post-publication notices (parse_updates); None = not looked up yet."""
    return {'title': title or '', 'authors': [a for a in authors if a], 'year': str(year or ''), 'venue': venue or '',
            'doi': doi or '', 'arxiv': arxiv or '', 'source': source, 'url': url, 'dblp_key': dblp_key, 'bibtex': bibtex,
            'updates': updates}


def parse_updates(m):
    """Retractions and corrections of a Crossref work -> [{type, date, doi, source}].

    Verified live 2026-10-26 on Wakefield 1998 (10.1016/S0140-6736(97)11096-0) and its notice
    (10.1016/s0140-6736(10)60175-4): the RETRACTED work's own record lists the notices in `updated-by`
    ({DOI of the notice, type, label, source: publisher|retraction-watch, updated.date-time, record-id});
    the notice's record carries the mirror `update-to`; `relation` is empty on both. So the work lookup
    we already make is enough (no second request), and `select=updated-by` works on searches too.
    filter=update-type:retraction lists notices, not retracted works. The same notice often appears
    twice (publisher and retraction-watch): deduplicated. Reinstated works (Retraction Watch
    "Reinstatement") showed no retraction in `updated-by` (3 of 3 sampled)."""
    out = {}
    for u in m.get('updated-by') or []:
        t = u.get('type', '')
        if t in RETRACTING | FLAGGING:
            out.setdefault((t, u.get('DOI', '').lower()), {
                'type': t, 'date': (u.get('updated') or {}).get('date-time', '')[:10],
                'doi': u.get('DOI', ''), 'source': u.get('source', '')})
    return list(out.values())


def guarded(service):
    """Disable a service for the rest of the run after its first failure (e.g. dblp's bot wall),
    so one broken API costs one timeout, not one per entry."""
    def wrap(fn):
        def inner(self, *a, **k):
            if service in self.down:
                return [] if fn.__name__ != 's2_arxiv' else None
            try:
                return fn(self, *a, **k)
            except Exception as e:
                self.down.add(service)
                print(f'  {service} unavailable, skipping it for this run: {e}', file=sys.stderr)
                return [] if fn.__name__ != 's2_arxiv' else None
        return inner
    return wrap


ARXIV_NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}
PREPRINT_VENUES = {'', 'arxiv', 'corr', 'arxiv.org', 'biorxiv', 'medrxiv', 'ssrn electronic journal'}


class Lookups:
    """Network lookups; replace in tests."""

    def __init__(self):
        self.down, self.arxiv_cache, self.arxiv_abstracts, self.works = set(), {}, {}, {}

    def prefetch_arxiv(self, ids):
        """One API call per 50 ids instead of one (plus a 3 s pause) per entry."""
        ids = [i for i in dict.fromkeys(ids) if i not in self.arxiv_cache]
        for n in range(0, len(ids), 50):
            batch = ids[n:n + 50]
            body = http('http://export.arxiv.org/api/query?' + urllib.parse.urlencode(
                {'id_list': ','.join(batch), 'max_results': len(batch)}), 'application/atom+xml')
            time.sleep(3)  # arXiv API etiquette
            found = {}
            for e in ET.fromstring(body or '<feed xmlns="http://www.w3.org/2005/Atom"/>').findall('a:entry', ARXIV_NS):
                aid = re.sub(r'v\d+$', '', e.findtext('a:id', '', ARXIV_NS).rsplit('/abs/', 1)[-1])
                title = ' '.join(e.findtext('a:title', '', ARXIV_NS).split())
                if title and title != 'Error':
                    self.arxiv_abstracts[aid] = ' '.join(e.findtext('a:summary', '', ARXIV_NS).split())
                    found[aid] = rec(title, [surname(a.findtext('a:name', '', ARXIV_NS)) for a in e.findall('a:author', ARXIV_NS)],
                                     e.findtext('a:published', '', ARXIV_NS)[:4], e.findtext('x:journal_ref', '', ARXIV_NS),
                                     e.findtext('x:doi', '', ARXIV_NS), aid, 'arxiv')
            for aid in batch:
                self.arxiv_cache[aid] = found.get(aid)

    def crossref_work(self, doi):
        """Crossref's full record for a DOI (or None), fetched once per run."""
        if doi.lower() not in self.works:
            body = http('https://api.crossref.org/works/' + urllib.parse.quote(doi))
            self.works[doi.lower()] = json.loads(body)['message'] if body else None
        return self.works[doi.lower()]

    def doi(self, doi):
        m = self.crossref_work(doi)
        if not m:
            return None
        year = next((m[k]['date-parts'][0][0] for k in ('published-print', 'published-online', 'issued')
                     if m.get(k, {}).get('date-parts', [[None]])[0][0]), '')
        return rec((m.get('title') or [''])[0], [surname(a.get('family') or a.get('name', '')) for a in m.get('author', [])],
                   year, (m.get('container-title') or [''])[0], m.get('DOI', doi), source='crossref', updates=parse_updates(m))

    def updates(self, doi):
        """Notices for a record found elsewhere (dblp, OpenAlex, Semantic Scholar) that has a DOI."""
        m = self.crossref_work(doi)
        return parse_updates(m) if m else []

    def arxiv(self, aid):
        if aid not in self.arxiv_cache:
            self.prefetch_arxiv([aid])
        return self.arxiv_cache.get(aid)

    @guarded('semantic-scholar')
    def s2_arxiv(self, aid):
        """Published venue (+ ready BibTeX) for an arXiv paper. Without S2_API_KEY the shared pool
        rate-limits; http() backs off and retries."""
        key = os.environ.get('S2_API_KEY')
        body = http(f'https://api.semanticscholar.org/graph/v1/paper/arXiv:{aid}?fields='
                    'title,authors,venue,year,externalIds,citationStyles', headers={'x-api-key': key} if key else None, tries=4)
        if not body:
            return None
        p = json.loads(body)
        ids = p.get('externalIds') or {}
        return rec(p.get('title', ''), [surname(a.get('name', '')) for a in p.get('authors', [])], p.get('year', ''),
                   p.get('venue', ''), ids.get('DOI', ''), aid, 'semantic-scholar',
                   dblp_key=ids.get('DBLP', '') if not ids.get('DBLP', '').startswith('journals/corr') else '',
                   bibtex=(p.get('citationStyles') or {}).get('bibtex', ''))

    @guarded('dblp')
    def dblp(self, title):
        body = http('https://dblp.org/search/publ/api?' + urllib.parse.urlencode({'q': title, 'format': 'json', 'h': 6}),
                    tries=1, timeout=8)
        time.sleep(1)  # dblp throttles bursts
        hits = (json.loads(body or '{}').get('result', {}).get('hits', {}).get('hit')) or []
        out = []
        for h in hits:
            info = h.get('info', {})
            au = info.get('authors', {}).get('author', [])
            au = au if isinstance(au, list) else [au]
            ee = info.get('ee', '')
            ee = ee[0] if isinstance(ee, list) else ee
            m = ARXIV_NEW.search(ee) if 'arxiv' in ee else None
            out.append(rec(info.get('title', '').rstrip('.'), [surname(re.sub(r'\s\d{4}$', '', a.get('text', ''))) for a in au],
                           info.get('year', ''), info.get('venue', ''), info.get('doi', ''), m[1] if m else '',
                           'dblp', info.get('url', ''), info.get('key', '')))
        return out

    @guarded('crossref')
    def crossref_search(self, title, author=''):
        body = http('https://api.crossref.org/works?' + urllib.parse.urlencode(
            {'query.bibliographic': f'{title} {author}'.strip(), 'rows': 5,
             'select': 'DOI,title,author,issued,container-title,updated-by'}))
        out = []
        for m in json.loads(body or '{}').get('message', {}).get('items', []):
            out.append(rec((m.get('title') or [''])[0], [surname(a.get('family') or a.get('name', '')) for a in m.get('author', [])],
                           (m.get('issued', {}).get('date-parts') or [[None]])[0][0], (m.get('container-title') or [''])[0],
                           m.get('DOI', ''), source='crossref', updates=parse_updates(m)))
        return out

    @guarded('openalex')
    def openalex(self, title):
        body = http('https://api.openalex.org/works?' + urllib.parse.urlencode(
            {'search': title, 'per-page': 5, 'select': 'title,authorships,publication_year,primary_location,doi'}))
        out = []
        for w in json.loads(body or '{}').get('results', []):
            src = ((w.get('primary_location') or {}).get('source') or {})
            out.append(rec(w.get('title', ''), [surname(a.get('author', {}).get('display_name', '')) for a in w.get('authorships', [])],
                           w.get('publication_year', ''), src.get('display_name', ''),
                           clean_doi(w.get('doi') or ''), source='openalex'))
        return out

    def bibtex_for(self, r):
        """Authoritative BibTeX for a record: DOI content negotiation (publisher metadata), then
        dblp, then Semantic Scholar's, then arXiv's DataCite DOI."""
        if r.get('doi') and not r['doi'].lower().startswith('10.48550'):
            return http('https://doi.org/' + urllib.parse.quote(r['doi']), 'application/x-bibtex')
        if r.get('dblp_key') and 'dblp' not in self.down:
            try:
                return http(f"https://dblp.org/rec/{r['dblp_key']}.bib", 'application/x-bibtex', tries=1, timeout=8)
            except Exception:
                self.down.add('dblp')
        if r.get('bibtex'):
            return r['bibtex']
        if r.get('arxiv'):
            return http(f"https://doi.org/10.48550/arXiv.{r['arxiv']}", 'application/x-bibtex')
        return None


# ---------------------------------------------------------------- judging

def judge(entry, r):
    """Compare a bib entry with a database record -> (kind, title_similarity, diffs)."""
    f = entry['fields']
    ts = SequenceMatcher(None, norm_title(f.get('title', '')), norm_title(r['title'])).ratio()
    ba, ra = bib_surnames(f.get('author', '')), r['authors']
    authors_ok = not ba or not ra or ba[0] == ra[0] or len(set(ba) & set(ra)) / max(1, min(len(ba), len(ra))) >= 0.5
    by, ry = (f.get('year') or f.get('date', '')[:4]), r['year']
    year_ok = not (by.isdigit() and str(ry).isdigit()) or abs(int(by) - int(ry)) <= 1
    if ts < 0.6:
        return 'different', ts, []
    diffs = []
    if ts < 0.97:
        diffs.append(f'title should be "{r["title"]}"')
    if not authors_ok:
        diffs.append(f'authors should be {", ".join(ra[:4])}{" et al." if len(ra) > 4 else ""} (entry has {", ".join(ba[:4])})')
    if not year_ok:
        diffs.append(f'year should be {ry} (entry has {by})')
    kind = 'verified' if ts >= 0.9 and authors_ok and year_ok else 'mismatch'
    return kind, ts, diffs if kind == 'mismatch' else []


def describe(r):
    ident = f"doi:{r['doi']}" if r['doi'] else f"arXiv:{r['arxiv']}" if r['arxiv'] else r['url']
    return f"{r['venue'] or r['source']} {r['year']} ({ident})".strip()


def search_best(entry, L):
    """Title search across dblp -> crossref -> openalex; stop at the first strong match."""
    f = entry['fields']
    title, first = detex(f.get('title', '')), (bib_surnames(f.get('author', '')) or [''])[0]
    best = None
    for fetch in (lambda: L.dblp(title), lambda: L.crossref_search(title, first), lambda: L.openalex(title)):
        try:
            cands = fetch()
        except Exception as e:  # one dead service must not sink the check
            print(f'  lookup failed for "{title[:40]}": {e}', file=sys.stderr)
            continue
        for r in cands:
            kind, ts, diffs = judge(entry, r)
            plausible = ts >= 0.85 or (ts >= 0.7 and kind == 'verified')
            if plausible and (best is None or (kind == 'verified', ts) > (best[0] == 'verified', best[1])):
                best = (kind, ts, diffs, r)
        if best and best[0] == 'verified':
            break
    return best


def published_version(r, L):
    """For an arXiv record: its published (non-preprint) version as a record, or None.
    Sources in order: arXiv's own journal_ref/DOI, Semantic Scholar, dblp."""
    if r.get('doi') and not r['doi'].lower().startswith('10.48550'):
        return dict(r, venue=r['venue'] or 'journal')
    s2 = L.s2_arxiv(r['arxiv']) if r.get('arxiv') else None
    if s2 and s2['venue'].strip().lower() not in PREPRINT_VENUES:
        return s2
    for h in L.dblp(r['title']):
        if h['venue'] not in ('', 'CoRR') and SequenceMatcher(None, norm_title(h['title']), norm_title(r['title'])).ratio() >= 0.95:
            return h
    return None


def verify_entry(e, L):
    """-> {'status', 'message', 'record', 'notices'}"""
    return with_notices(classify(e, L), L)


def with_notices(res, L):
    """Attach the matched work's retraction/correction notices; a retracted work becomes 'retracted'.
    Crossref records already carry them; others cost one Crossref lookup if they have a DOI. If that
    lookup fails, 'notices' is left out so the next run checks the entry again."""
    r = res.get('record') or {}
    notices, doi = r.get('updates'), clean_doi(r.get('doi', ''))
    if notices is None and doi and not doi.lower().startswith('10.48550'):
        try:
            notices = L.updates(doi)
        except Exception as ex:
            print(f'  retraction check failed for DOI {doi}: {ex}', file=sys.stderr)
            return res
    res['notices'] = notices or []
    gone = [u for u in res['notices'] if u['type'] in RETRACTING]
    if gone:
        u, was = gone[0], '' if res['status'] == 'verified' else f"; also {res['status']}: {res['message']}"
        res.update(status='retracted', message=f"{u['type']} {u['date']} (notice doi:{u['doi']}): "
                                               f"cite the notice or remove the citation{was}")
    return res


def classify(e, L):
    """Existence and metadata check -> {'status', 'message', 'record'}."""
    f = e['fields']
    doi, ax = clean_doi(f.get('doi', '')), arxiv_id(f)
    if doi.lower().startswith('10.48550/'):
        doi = ''
    note = ''
    for ident, lookup, label in ((doi, L.doi, f'DOI {doi}'), (ax, L.arxiv, f'arXiv:{ax}')):
        if not ident:
            continue
        try:
            r = lookup(ident)
        except Exception as ex:
            print(f'  lookup failed for {label}: {ex}', file=sys.stderr)
            continue
        if r is None:
            note = f'{label} does not resolve'
            continue
        kind, ts, diffs = judge(e, r)
        if kind == 'different':
            note = f'{label} resolves to a different work: "{r["title"][:80]}"'
            continue
        if ident == ax:
            pub = published_version(r, L)
            if pub and kind == 'verified':
                return {'status': 'published', 'message': f'preprint; published version: {describe(pub)}', 'record': pub}
            if pub:  # wrong metadata AND a published version exists: suggest the published entry
                return {'status': kind, 'message': '; '.join(diffs + [f'published version: {describe(pub)}']), 'record': pub}
        return {'status': kind, 'message': '; '.join(diffs) or describe(r), 'record': r}

    if not f.get('title'):
        return {'status': 'unverifiable', 'message': 'no title to search for', 'record': None}
    best = search_best(e, L)
    if best:
        kind, ts, diffs, r = best
        if note:  # the identifier was wrong but the work exists
            return {'status': 'bad-doi', 'message': f'{note}; found as {describe(r)}', 'record': r}
        return {'status': kind, 'message': '; '.join(diffs) or describe(r), 'record': r}
    if note:
        return {'status': 'bad-doi', 'message': note + '; no match by title either', 'record': None}
    if e['type'] not in CHECKABLE:
        return {'status': 'unverifiable', 'message': f'@{e["type"]} not indexed in dblp/Crossref/OpenAlex: check by hand', 'record': None}
    return {'status': 'not-found', 'message': 'no match in dblp, Crossref or OpenAlex: likely fabricated, check by hand', 'record': None}


def duplicates(entries):
    seen, dups = {}, []
    for e in entries:
        f = e['fields']
        for ident in filter(None, [clean_doi(f.get('doi', '')).lower(), arxiv_id(f), norm_title(f.get('title', ''))]):
            if ident in seen and seen[ident] != e['key']:
                dups.append((seen[ident], e['key'], ident))
                break
            seen.setdefault(ident, e['key'])
    return dups


# ---------------------------------------------------------------- project plumbing

def project_files(path):
    """-> (root, bib files, cited keys)."""
    path = path.resolve()
    if path.suffix == '.bib':
        return path.parent, [path], None
    tex = [p for p in path.rglob('*.tex') if not set(p.relative_to(path).parts) & SKIP_DIRS]
    cited, bibs = set(), []
    for t in tex:
        text = strip_comments(t.read_text(encoding='utf-8', errors='replace'))
        cited |= {k.strip() for m in CITE_RE.finditer(text) for k in m.group(1).split(',') if k.strip()}
        for m in BIBFILE_RE.finditer(text):
            for b in m[1].split(','):
                p = (t.parent / b.strip())
                p = p if p.suffix == '.bib' else p.with_suffix('.bib')
                if p.exists() and p not in bibs:
                    bibs.append(p)
    if not bibs:
        bibs = [p for p in path.rglob('*.bib') if not set(p.relative_to(path).parts) & SKIP_DIRS]
    return path, bibs, cited


def load_cache(root):
    p = root / '.agentex' / 'cite-cache.json'
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {'version': 1, 'entries': {}, 'keys': {}}


def agentex_dir(root):
    """Scratch folder for caches; ignores itself so it never shows up in the user's git status."""
    d = root / '.agentex'
    d.mkdir(exist_ok=True)
    if not (d / '.gitignore').exists():
        (d / '.gitignore').write_text('*\n')
    return d


def write_status(root, tool, status, summary, counts, items):
    """Dashboard contract: <project>/.agentex/status/<tool>.json, replaced atomically.
    status ok|warn|fail; summary <= 100 chars; items <= 20 {where: 'file:line', message}."""
    d = agentex_dir(root) / 'status'
    d.mkdir(exist_ok=True)
    tmp = d / f'{tool}.json.tmp'
    tmp.write_text(json.dumps({'tool': tool, 'status': status, 'summary': summary[:100], 'counts': counts, 'items': items[:20],
                               'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}, indent=1))
    os.replace(tmp, d / f'{tool}.json')


def first_cites(root):
    """{key: 'file:line' of its first \\cite} (for keys that have no .bib entry to point at)."""
    sites = {}
    for t in sorted(root.rglob('*.tex')):
        if not set(t.relative_to(root).parts) & SKIP_DIRS:
            for k, loc in scan(CITE_RE, strip_comments(t.read_text(encoding='utf-8', errors='replace')), t.relative_to(root)):
                sites.setdefault(k, loc)
    return sites


def save_cache(root, cache):
    d = agentex_dir(root)
    tmp = d / 'cite-cache.json.tmp'
    tmp.write_text(json.dumps(cache, indent=1))
    tmp.replace(d / 'cite-cache.json')


def run(path, keys=None, check_all=False, refresh=False, offline=False, L=None):
    L = L or Lookups()
    root, bibs, cited = project_files(path)
    entries = [dict(e, file=os.path.relpath(b, root)) for b in bibs for e in parse_bib(b.read_text(encoding='utf-8', errors='replace'))]
    by_key = {e['key']: e for e in entries}
    if keys:
        wanted = list(keys)
    elif check_all or cited is None:
        wanted = list(by_key)
    else:
        wanted = sorted(k for k in cited if k != '*')
    cache = load_cache(root)
    cache['bibs'] = [os.path.relpath(b, root) for b in bibs]
    if not offline and hasattr(L, 'prefetch_arxiv'):
        todo = [by_key[k] for k in wanted if k in by_key and (refresh or 'notices' not in cache['entries'].get(fingerprint(by_key[k]), {}))]
        L.prefetch_arxiv([a for a in (arxiv_id(e['fields']) for e in todo) if a])
    results = {}
    for k in wanted:
        e = by_key.get(k)
        if e is None:
            results[k] = {'status': 'missing', 'message': 'cited but not in any .bib file', 'record': None}
            continue
        fp = fingerprint(e)
        hit = cache['entries'].get(fp)
        fresh = hit and 'notices' in hit  # entries cached before the retraction check get re-verified once
        if fresh and not refresh and hit['status'] != 'not-found' or (hit and offline):
            results[k] = hit
        elif offline:
            results[k] = {'status': 'unchecked', 'message': 'offline and not in cache', 'record': None}
        else:
            print(f'  checking {k} ...', file=sys.stderr)
            r = verify_entry(e, L)
            r['checked'] = date.today().isoformat()
            cache['entries'][fp] = r
            results[k] = r
        cache['keys'][k] = {'fp': fp, 'status': results[k]['status']}
    save_cache(root, cache)
    return root, entries, results, duplicates([by_key[k] for k in wanted if k in by_key])


def write_suggestions(path, entries, results, L):
    by_key = {e['key']: e for e in entries}
    out = ['% AgenTeX cite_verify suggestions: review each entry, then copy what you accept into your .bib.\n']
    for k, r in results.items():
        if r['status'] not in ('mismatch', 'published', 'bad-doi') or not r.get('record'):
            continue
        try:
            bib = L.bibtex_for(r['record'])
        except Exception:
            bib = None
        if not bib:
            continue
        bib = re.sub(r'^(\s*@\w+\s*\{)[^,]*,', lambda m: m[1] + k + ',', bib.strip(), count=1)  # keep the user's key
        bib = re.sub(r'(?im)^\s*(keywords|copyright|abstract)\s*=.*\n', '', bib)  # export noise
        out.append(f"% {k} ({r['status']}): {r['message']}\n% original at line {by_key[k]['line']}\n{bib}\n")
    Path(path).write_text('\n'.join(out), encoding='utf-8')
    return len(out) - 1


ORDER = ['retracted', 'not-found', 'bad-doi', 'missing', 'mismatch', 'published', 'unverifiable', 'unchecked', 'verified']
FAILING = {'retracted', 'not-found', 'bad-doi', 'missing', 'mismatch'}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path', type=Path, help='project folder or a .bib file')
    ap.add_argument('--all', action='store_true', help='check every entry, not only cited ones')
    ap.add_argument('--keys', help='comma-separated keys to check')
    ap.add_argument('--refresh', action='store_true', help='ignore the cache')
    ap.add_argument('--offline', action='store_true', help='report from the cache only')
    ap.add_argument('--suggest', metavar='FILE', nargs='?', const='', default=None,
                    help='write corrected BibTeX for review (default .agentex/suggested.bib); never edits your .bib')
    ap.add_argument('--verbose', action='store_true', help='also list verified entries')
    args = ap.parse_args(argv)
    if not args.path.exists():
        ap.error(f'not found: {args.path}')

    keys = [k.strip() for k in args.keys.split(',')] if args.keys else None
    root, entries, results, dups = run(args.path, keys, args.all, args.refresh, args.offline)
    if not results:
        print('nothing to check: no .bib entries' + ('' if args.path.suffix == '.bib' else ' or no \\cite commands') +
              f' found under {args.path}')
        return 0
    counts = {s: sum(r['status'] == s for r in results.values()) for s in ORDER}
    notices = [(k, u) for k, r in results.items() if r['status'] != 'retracted' for u in r.get('notices') or []]
    counts.update(duplicates=len(dups), notices=len(notices))
    print(' · '.join(f'{s} {n}' for s, n in counts.items() if n))
    lines = []  # (where, message) for the status file
    by_key = {e['key']: e for e in entries}
    sites = first_cites(root) if counts['missing'] else {}
    for k, r in sorted(results.items(), key=lambda kv: ORDER.index(kv[1]['status'])):
        if r['status'] != 'verified' or args.verbose:
            print(f"{r['status'].upper():13s} {k:28s} {r['message']}")
        if r['status'] != 'verified':
            e = by_key.get(k)
            lines.append((f"{e['file']}:{e['line']}" if e else sites.get(k, k), f"{k}: {r['status']}: {r['message']}"))
    for k, u in notices:  # corrections and expressions of concern: worth a look, not a failure
        msg = f"{u['type'].replace('_', ' ')} {u['date']} (doi:{u['doi']})"
        print(f"{'NOTICE':13s} {k:28s} {msg}")
        lines.append((f"{by_key[k]['file']}:{by_key[k]['line']}", f'{k}: {msg}'))
    for a, b, ident in dups:
        print(f'DUPLICATE     {a}, {b}: same work ({ident[:60]})')
        lines.append((f"{by_key[b]['file']}:{by_key[b]['line']}", f'{a}, {b}: same work'))
    bad = sum(counts[s] for s in FAILING) + len(dups)
    if not keys:  # a --keys run sees only part of the paper, so it leaves the dashboard alone
        status = 'fail' if bad else 'warn' if len(results) > counts['verified'] or notices else 'ok'
        write_status(root, 'citations', status, f'{len(results)} citations: ' + ', '.join(f'{n} {s}' for s, n in counts.items() if n),
                     counts, [{'where': w, 'message': m[:200]} for w, m in lines])
    if args.suggest is not None:
        out = Path(args.suggest) if args.suggest else agentex_dir(root) / 'suggested.bib'
        n = write_suggestions(out, entries, results, Lookups())
        print(f'wrote {n} suggested correction(s) to {out}: review them; your .bib was not changed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
