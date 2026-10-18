#!/usr/bin/env python3
"""Find the published work closest to yours: query OpenAlex, arXiv and Semantic Scholar, merge
duplicates, then re-rank every candidate by text similarity to YOUR title + abstract.

Usage:
  related.py --from-tex paper/main.tex                 # title + abstract read from the .tex
  related.py -q "graph neural network weather" -q "GNN medium-range forecasting" --text "our abstract ..."
  related.py --from-tex main.tex -q "extra query" -n 20 --abstracts

Free public APIs, no key needed (set S2_API_KEY to raise Semantic Scholar's rate limit).
Output is one compact block per paper; pass ids/DOIs to the latex-references skill for BibTeX.
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

UA = {'User-Agent': 'AgenTeX-related/0.2 (https://github.com/Metahemeralism/AgenTeX)'}
STOP = set("""a an and are as at be by can for from has have in into is it its of on or our that the their
these this those to was we were which with without using use used via based new approach method methods paper
propose proposed show shows results study work also than then thus such both more most other over under""".split())


def tokens(text):
    return [t for t in re.findall(r'[a-z][a-z0-9-]+', text.lower()) if t not in STOP and len(t) > 2]


def keywords(text, k=6):
    """Most frequent content words, a decent keyword query when only an abstract is given."""
    return [w for w, _ in Counter(tokens(text)).most_common(k)]


def from_tex(path):
    t = re.sub(r'(?<!\\)%.*', '', open(path, encoding='utf-8', errors='replace').read())
    title = re.search(r'\\title\s*(?:\[[^\]]*\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}', t)
    abstract = re.search(r'\\begin\{abstract\}(.*?)\\end\{abstract\}', t, re.S)
    clean = lambda s: re.sub(r'\s+', ' ', re.sub(r'\\[a-zA-Z]+\*?|[{}$~\\]', ' ', s)).strip()
    return clean(title[1]) if title else '', clean(abstract[1]) if abstract else ''


def get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def openalex(q, n):
    url = 'https://api.openalex.org/works?' + urllib.parse.urlencode({
        'search': q, 'per-page': n,
        'select': 'doi,title,publication_year,primary_location,cited_by_count,abstract_inverted_index,ids'})
    out = []
    for w in json.loads(get(url))['results']:
        inv = w.get('abstract_inverted_index') or {}
        pos = sorted((i, word) for word, idx in inv.items() for i in idx)
        src = ((w.get('primary_location') or {}).get('source') or {})
        out.append({'title': w.get('title') or '', 'year': w.get('publication_year'), 'venue': src.get('display_name') or '',
                    'cites': w.get('cited_by_count') or 0, 'doi': (w.get('doi') or '').replace('https://doi.org/', ''),
                    'arxiv': '', 'url': w.get('doi') or (w.get('ids') or {}).get('openalex', ''),
                    'abstract': ' '.join(word for _, word in pos)})
    return out


def arxiv(q, n):
    terms = keywords(q, 5) or q.split()[:5]
    query = ' AND '.join(f'all:{t}' for t in terms)
    url = 'http://export.arxiv.org/api/query?' + urllib.parse.urlencode(
        {'search_query': query, 'max_results': n, 'sortBy': 'relevance'})
    ns = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}
    out = []
    for e in ET.fromstring(get(url)).findall('a:entry', ns):
        aid = e.findtext('a:id', '', ns).rsplit('/abs/', 1)[-1]
        doi = e.findtext('x:doi', '', ns)
        out.append({'title': ' '.join(e.findtext('a:title', '', ns).split()), 'year': int(e.findtext('a:published', '0000', ns)[:4]),
                    'venue': e.findtext('x:journal_ref', '', ns) or 'arXiv', 'cites': 0, 'doi': doi,
                    'arxiv': re.sub(r'v\d+$', '', aid), 'url': f'https://arxiv.org/abs/{aid}',
                    'abstract': ' '.join(e.findtext('a:summary', '', ns).split())})
    time.sleep(3)  # arXiv API etiquette: one request every 3 seconds
    return out


def semantic_scholar(q, n):
    url = 'https://api.semanticscholar.org/graph/v1/paper/search?' + urllib.parse.urlencode(
        {'query': q, 'limit': n, 'fields': 'title,year,venue,citationCount,externalIds,abstract,url'})
    key = os.environ.get('S2_API_KEY')
    out = []
    for p in json.loads(get(url, {'x-api-key': key} if key else None)).get('data', []):
        ids = p.get('externalIds') or {}
        out.append({'title': p.get('title') or '', 'year': p.get('year'), 'venue': p.get('venue') or '',
                    'cites': p.get('citationCount') or 0, 'doi': ids.get('DOI', ''), 'arxiv': ids.get('ArXiv', ''),
                    'url': p.get('url', ''), 'abstract': p.get('abstract') or ''})
    return out


SOURCES = {'openalex': openalex, 'arxiv': arxiv, 's2': semantic_scholar}


def norm_title(t):
    return re.sub(r'[^a-z0-9]', '', t.lower())


def merge(records):
    """Deduplicate by DOI, arXiv id or normalised title; keep the richest fields."""
    merged, index = [], {}
    for r in records:
        keys = [k for k in (r['doi'].lower(), r['arxiv'], norm_title(r['title'])) if k]
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            hit = dict(r, sources={r['source']})
            merged.append(hit)
        else:
            hit['sources'].add(r['source'])
            hit['cites'] = max(hit['cites'], r['cites'])
            for f in ('doi', 'arxiv', 'abstract', 'venue', 'year'):
                if not hit.get(f) or (f == 'abstract' and len(r[f]) > len(hit[f])):
                    hit[f] = r[f] or hit.get(f)
            if hit['venue'] == 'arXiv' and r['venue'] not in ('', 'arXiv'):
                hit['venue'] = r['venue']
        for k in keys:
            index[k] = hit
    return merged


def rank(reference, papers):
    """TF-IDF cosine between the reference text and each title+abstract (IDF over this candidate set)."""
    docs = [Counter(tokens(p['title'] + ' ' + p['title'] + ' ' + p['abstract'])) for p in papers]
    ref = Counter(tokens(reference))
    df = Counter(t for d in docs + [ref] for t in d)
    n = len(docs) + 1
    idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
    vec = lambda c: {t: (1 + math.log(f)) * idf[t] for t, f in c.items()}
    rv = vec(ref)
    rn = math.sqrt(sum(v * v for v in rv.values())) or 1
    for p, d in zip(papers, docs):
        dv = vec(d)
        dn = math.sqrt(sum(v * v for v in dv.values())) or 1
        p['score'] = sum(rv[t] * dv.get(t, 0) for t in rv) / (rn * dn)
    return sorted(papers, key=lambda p: (-p['score'], -p['cites']))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-q', '--query', action='append', default=[], help='search query (repeatable)')
    ap.add_argument('--from-tex', help='read \\title and abstract from this .tex as the reference text')
    ap.add_argument('--text', default='', help='reference text (e.g. your abstract) to rank against')
    ap.add_argument('-n', type=int, default=12, help='results to print (default 12)')
    ap.add_argument('--per-source', type=int, default=25, help='candidates fetched per query and source')
    ap.add_argument('--sources', default='openalex,arxiv,s2')
    ap.add_argument('--abstracts', action='store_true', help='print a 300-character abstract snippet')
    args = ap.parse_args(argv)

    reference = args.text
    queries = list(args.query)
    if args.from_tex:
        title, abstract = from_tex(args.from_tex)
        reference = ' '.join(filter(None, [title, abstract, reference]))
        if not queries:
            queries = [q for q in (title, ' '.join(keywords(abstract))) if q]
    if not queries:
        ap.error('give -q queries and/or --from-tex')
    reference = reference or ' '.join(queries)

    records = []
    for name in args.sources.split(','):
        for q in queries:
            try:
                records += [dict(r, source=name) for r in SOURCES[name](q, args.per_source)]
            except Exception as e:  # one dead or rate-limited API must not sink the others
                print(f'[{name}] "{q[:40]}" failed: {e}', file=sys.stderr)
    papers = rank(reference, merge([r for r in records if r['title']]))
    print(f'{len(papers)} unique candidates from {len(records)} hits; top {min(args.n, len(papers))} by similarity:')
    for i, p in enumerate(papers[:args.n], 1):
        ident = f"doi:{p['doi']}" if p['doi'] else f"arXiv:{p['arxiv']}" if p['arxiv'] else p['url']
        print(f"{i:2d}. {p['score']:.2f}  {p['year'] or '----'}  {p['title'][:110]}\n"
              f"    {p['venue'][:50] or '?'} · {p['cites']} cites · {ident} · via {'+'.join(sorted(p['sources']))}")
        if args.abstracts and p['abstract']:
            print(f"    {p['abstract'][:300]}{'...' if len(p['abstract']) > 300 else ''}")
    return 0 if papers else 1


if __name__ == '__main__':
    sys.exit(main())
