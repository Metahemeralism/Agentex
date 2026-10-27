#!/usr/bin/env python3
"""Claim ledger: every checkable claim in the paper, with a verdict and code evidence per claim.

  claims.py extract <paper_dir_or_main.tex>  claim sentences (numbers, \\res{} uses, comparatives/superlatives,
                                            "we show/prove", method statements) -> .agentex/claims.json; verdicts of
                                            unchanged claims are kept, edited ones become CHANGED, deleted ones REMOVED
  claims.py next [--n 5] [--code DIR]        unchecked claims, each with <= 3 candidate code locations (narrow context)
  claims.py record <id> --verdict supported|unsupported|partial|unclear [--evidence FILE:LINE ...] [--note TEXT]
  claims.py report                           counts + unsupported/partial/changed claims with file:line
  claims.py freeze                           re-extract, then freeze the current claim texts (the "claim spine")
  claims.py diff                             exit 0 = frozen claims intact, 1 = one changed or vanished (printed),
                                            2 = nothing frozen yet / paper missing (callers skip)
The ledger lives in <root>/.agentex/claims.json; root = --root, else the nearest folder from cwd up with .agentex/,
else cwd. Verdicts are flags for the authors; nothing here edits the paper. Status: .agentex/status/consistency.json.
"""
import argparse
import difflib
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from settings_audit import (CANON, NUM, REFS, agentex_dir, atomic_write, canon_of, find_root, norm_name,  # noqa: E402
                            num_value, paper_files, plain, rel, write_status)

VERDICTS = ('supported', 'unsupported', 'partial', 'unclear')
SKIP_ENV = re.compile(r'\\begin\{(tikzpicture|tabular\*?|tabularx|longtable|verbatim|lstlisting|minted|equation\*?|align\*?|'
                      r'gather\*?|multline\*?|eqnarray\*?|displaymath|algorithmic|thebibliography|comment|filecontents\*?|'
                      r'tikzcd|axis)\}.*?\\end\{\1\}', re.S)
HEADING = re.compile(r'\\(?:part|chapter|(?:sub)*section|paragraph)\*?(?:\[[^\]]*\])?\{(?:[^{}]|\{[^{}]*\})*\}')
BREAK = re.compile(r'\\(?:begin|end)\{[^}]*\}(?:\[[^\]]*\])?|\\item\b|\\caption\*?(?:\[[^\]]*\])?\{|'
                   r'\\(?:maketitle|centering|noindent|newpage|clearpage|appendix)\b')
CUT = re.compile(r'\x00|\n[ \t]*\n|[.!?][)"\'}\]]*(?=\s)')
NEXT = re.compile(r'\s*[A-Z\\$(`\x00]')
ABBR = re.compile(r'(?:\b(?i:e\.g|i\.e|et al|etc|vs|cf|resp|approx|fig|figs|eq|eqs|sec|secs|tab|no|ref|refs|thm|def|prop|alg|'
                  r'app|ch|vol|pp)|(?<![A-Za-z])[A-Z])$')
RES_USE = re.compile(r'\\res(?:pct)?\{([^}]+)\}')
REFNUM = re.compile(r'\b(?:tables?|tab|figures?|figs?|sections?|secs?|eqs?|equations?|appendix|app|algorithms?|alg|lines?|'
                    r'chapters?|theorems?|lemmas?|steps?)\.?[~\s]*\(?\d+(?:\.\d+)*\)?')
KINDS = [
    ('comparative', re.compile(r'\b(?:outperform\w*|surpass\w*|beats?|better|worse|superior|state[\s-]of[\s-]the[\s-]art|sota|'
                               r'best|significant(?:ly)?|consistent(?:ly)?|substantial(?:ly)?|always|never|first|improv\w*)\b', re.I)),
    ('show', re.compile(r'\bwe\s+(?:\w+ly\s+)?(?:show|prove|demonstrate|establish|find|found|observe|confirm|verify|validate)\w*\b|'
                        r'\b(?:results|experiments|analysis|ablations?)\s+(?:\w+\s+)?(?:show|demonstrate|confirm|indicate|suggest)s?\b', re.I)),
    ('method', re.compile(r'\bwe\s+(?:\w+ly\s+)?(?:train|use|apply|adopt|employ|fine[\s-]?tune|optimi[sz]e|initiali[sz]e|set|sample|'
                          r'run|report|implement|evaluate|pre[\s-]?train|compute|average|normali[sz]e|augment|filter|discard|remove|split|'
                          r'tune|select|choose)\w*\b|\b(?:is|are|was|were)\s+(?:\w+ly\s+)?(?:trained|set|initiali[sz]ed|optimi[sz]ed|'
                          r'sampled|computed|fine[\s-]?tuned|evaluated|implemented|normali[sz]ed|averaged|tuned|selected|'
                          r'filtered|split|clipped|applied|used)\b', re.I)),
]
CODE_EXT = {'.py', '.ipynb', '.yaml', '.yml', '.json', '.toml', '.ini', '.cfg', '.sh', '.r', '.jl', '.m', '.c', '.cc', '.cpp',
            '.h', '.hpp', '.cu', '.rs', '.go', '.java', '.scala', '.csv'}
INDEX_SKIP = {'node_modules', '__pycache__', 'venv', 'env', 'build', 'dist', 'site-packages', 'arxiv_submission', 'wandb', 'mlruns'}
STOP = set('''this that with from have been were which their there these those than then into also using used such each both
 more most other only over under when where while what about after before between through during without within paper
 section table figure results result method methods model models approach shows shown based number different same however
 therefore thus well very much many some across further same show their them they our ours here able given'''.split())
IDENT = re.compile(r'[A-Za-z_]\w*')
CODE_NUM = re.compile(r'(?<![\w.])-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?(?![\w.])')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def norm(s):
    return ' '.join(s.split()).lower()


def short(s, n=120):
    return s if len(s) <= n else s[:n - 1] + '…'


# ---------------------------------------------------------------- extraction

def blank(m, mark=''):
    return mark + re.sub(r'[^\n]', ' ', m[0][len(mark):])


def sentences(text):
    """[(line, sentence)] for the prose of one comment-stripped .tex file (no preamble, maths, tables or TikZ)."""
    a = text.find('\\begin{document}')
    if a >= 0:
        text = re.sub(r'[^\n]', ' ', text[:a]) + text[a:]
    b = text.find('\\end{document}')
    if b >= 0:
        text = text[:b]
    text = SKIP_ENV.sub(blank, text)
    text = re.sub(r'\\label\{[^}]*\}|\\pgfplotstableread\s*\{[^{}]*\}', blank, text)
    text = re.sub(r'(?<!\\)\\\[.*?\\\]', blank, text, flags=re.S)
    text = HEADING.sub(lambda m: blank(m, '\x00'), text)
    text = BREAK.sub(lambda m: blank(m, '\x00'), text)
    cuts, out = [0], []
    for m in CUT.finditer(text):
        if m[0][0] in '.!?' and (ABBR.search(text, max(0, m.start() - 8), m.start()) or not NEXT.match(text, m.end())):
            continue
        cuts.append(m.end())
    cuts.append(len(text))
    for x, y in zip(cuts, cuts[1:]):
        chunk = text[x:y]
        s = ' '.join(chunk.replace('\x00', ' ').split())
        while s.endswith('}') and s.count('}') > s.count('{'):
            s = s[:-1].rstrip()  # the closing brace of \caption{...}
        if len(s) < 25 or len(s.split()) < 4:
            continue
        lead = len(chunk) - len(chunk.lstrip(' \t\n\x00'))
        out.append((text.count('\n', 0, x + lead) + 1, s))
    return out


def numbers(t, small=False):
    """Values in plain text t that can carry a claim: never years; small integers only with small=True."""
    out = set()
    for m in NUM.finditer(REFNUM.sub(' ', t)):
        v, pct = num_value(m)
        if pct or not v.is_integer() or (small or abs(v) >= 10) and not 1900 <= v <= 2099:
            out |= {v, v / 100} if pct else {v}
    return out


def kinds(s):
    bare = REFS.sub(' ', s)  # "first" in \label{sec:related-first} is not a claim
    prose = re.sub(r'(?<!\\)\$[^$]*\$', ' ', bare)  # "6 layers" counts, the 1 in $x_{i=1}$ does not
    number = RES_USE.search(s) or numbers(plain(bare)) or numbers(plain(prose), small=True)
    return (['number'] if number else []) + [k for k, rx in KINDS if rx.search(bare)]


def all_sentences(paper, root):
    """Every prose sentence with a stable id (hash of its normalised text; repeats get an occurrence suffix)."""
    files, _ = paper_files(paper)
    out, seen = [], {}
    for p, text in files:
        for line, s in sentences(text):
            key = norm(s)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                key += f'#{seen[key]}'
            out.append({'id': hashlib.sha1(key.encode()).hexdigest()[:8], 'text': s, 'where': f'{rel(p, root)}:{line}'})
    return out


def similar(a, b):
    sm = difflib.SequenceMatcher(None, norm(a), norm(b))
    return sm.ratio() if sm.quick_ratio() >= 0.5 else 0.0


# ---------------------------------------------------------------- ledger

def ledger_path(root):
    return Path(root) / '.agentex' / 'claims.json'


def load(root):
    try:
        return json.loads(ledger_path(root).read_text())
    except (OSError, ValueError):
        return {'version': 1, 'paper': None, 'claims': {}, 'frozen': {}}


def save(root, led):
    agentex_dir(root)
    atomic_write(ledger_path(root), json.dumps(led, indent=1))
    publish(root, led)


def extract(paper, root, led):
    found = [dict(c, kinds=k, order=i) for i, c in enumerate(all_sentences(paper, root)) if (k := kinds(c['text']))]
    old = led['claims']
    ids = {c['id'] for c in found}
    claims, fresh = {}, []
    for c in found:
        prev = old.get(c['id'])
        claims[c['id']] = dict(prev or {'verdict': None}, text=c['text'], where=c['where'], kinds=c['kinds'], order=c['order'],
                               status=(prev or {}).get('status', 'current') if prev and prev.get('status') != 'removed' else 'current')
        if not prev:
            fresh.append(c['id'])
    changed = removed = 0
    for gid, g in old.items():
        if gid in ids:
            continue
        if g.get('status') == 'removed':
            claims[gid] = g
            continue
        best = max(fresh, key=lambda i: similar(g['text'], claims[i]['text']), default=None)
        if best and similar(g['text'], claims[best]['text']) >= 0.6:
            claims[best].update(status='changed', was={'id': gid, 'text': g['text'], 'verdict': g.get('verdict')})
            fresh.remove(best)
            changed += 1
        else:
            claims[gid] = dict(g, status='removed')
            removed += 1
    led.update(paper=rel(paper, root), extracted=now(), claims=claims)
    kept = sum(1 for i in ids if i in old and old[i].get('verdict'))
    return len(found), len(fresh), changed, removed, kept


# ---------------------------------------------------------------- next: narrow context per claim

def stem(w):
    for suf in ('ations', 'ation', 'ings', 'ing', 'ies', 'ed', 'es', 's'):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[:-len(suf)]
            break
    return w[:-1] if len(w) > 4 and w[-1] == w[-2] else w  # clipp -> clip


def terms(text):
    t = plain(text)
    nums = numbers(t)
    canons = {n for n, _, _, rx in CANON if rx.search(t)}
    idents = set(re.findall(r'[a-z]\w*_\w+', t)) | {p.lower() for k in RES_USE.findall(text) for p in k.split('.') if len(p) > 2}
    words = {stem(w) for w in re.findall(r'[a-z][a-z0-9]{3,}', t) if w not in STOP} - idents
    return nums, canons, idents, words


def code_index(code_dir, paper_root):
    files = []
    for dirpath, dirnames, filenames in os.walk(code_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in INDEX_SKIP and not d.startswith('.'))
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if p.suffix.lower() in CODE_EXT and p.stat().st_size <= 1_000_000:
                lines = p.read_text(encoding='utf-8', errors='replace').splitlines()
                files.append((rel(p, paper_root), lines))
    return files


def score(line, nums, canons, idents, words):
    if len(line) > 400:
        return 0  # notebook outputs, minified data
    low, s = line.lower(), 0
    if nums and any(math.isclose(float(m[0]), v, rel_tol=1e-9) for m in CODE_NUM.finditer(low) for v in nums):
        s += 3
    if canons:
        s += 2 * len(canons & {canon_of(norm_name(i))[0] for i in IDENT.findall(line)})
    s += 3 * sum(w in low for w in idents)
    return s + min(3, sum(w in low for w in words))


def candidates(text, index):
    nums, canons, idents, words = terms(text)
    best = []
    for path, lines in index:
        top = max(((score(line, nums, canons, idents, words), n) for n, line in enumerate(lines, 1)), default=(0, 0))
        if top[0] >= 3:
            best.append((-top[0], path, top[1], lines[top[1] - 1].strip()))
    return sorted(best)[:3]


# ---------------------------------------------------------------- status

def publish(root, led):
    cs = [c for c in led['claims'].values() if c.get('status') != 'removed']
    counts = {v: sum(c.get('verdict') == v for c in cs) for v in VERDICTS}
    counts.update(unchecked=sum(not c.get('verdict') for c in cs), changed=sum(c.get('status') == 'changed' for c in cs),
                  removed=sum(c.get('status') == 'removed' for c in led['claims'].values()))
    flagged = sorted((c for c in cs if c.get('verdict') in ('unsupported', 'partial') or c.get('status') == 'changed'),
                     key=lambda c: (c.get('verdict') != 'unsupported', c.get('order', 0)))
    items = [(c['where'], f'{(c.get("verdict") or "changed").upper()}: {short(c["text"], 100)}') for c in flagged]
    checked = len(cs) - counts['unchecked']
    status = 'fail' if counts['unsupported'] else 'warn' if counts['partial'] or counts['unclear'] or counts['unchecked'] else 'ok'
    summary = f'{checked}/{len(cs)} claims checked: {counts["unsupported"]} unsupported, {counts["partial"]} partial'
    write_status(root, 'consistency', status, summary, counts, items)
    return counts, flagged, summary


# ---------------------------------------------------------------- CLI

def evidence_ok(ev, root):
    m = re.fullmatch(r'(.+):(\d+)', ev)
    if not m:
        return f'evidence must be FILE:LINE, got {ev!r}'
    p = next((q for q in (Path(root) / m[1], Path(m[1])) if q.is_file()), None)
    if not p:
        return f'evidence file not found: {m[1]}'
    n = len(p.read_text(encoding='utf-8', errors='replace').splitlines())
    return None if 1 <= int(m[2]) <= n else f'{m[1]} has {n} lines, not {m[2]}'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', help='project folder holding .agentex/ (default: nearest from cwd up, else cwd)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('extract').add_argument('paper')
    nx = sub.add_parser('next')
    nx.add_argument('--n', type=int, default=5)
    nx.add_argument('--code', help='folder to search for evidence (default: the project root)')
    r = sub.add_parser('record')
    r.add_argument('id')
    r.add_argument('--verdict', required=True, choices=VERDICTS)
    r.add_argument('--evidence', action='append', default=[], help='FILE:LINE; repeat for several')
    r.add_argument('--note', default='')
    for name in ('report', 'freeze', 'diff'):
        sub.add_parser(name)
    args = ap.parse_args(argv)
    root = find_root(args.root)
    led = load(root)

    if args.cmd == 'extract':
        if not Path(args.paper).exists():
            print(f'no such paper: {args.paper}')
            return 2
        n, new, changed, removed, kept = extract(args.paper, root, led)
        save(root, led)
        print(f'{n} claims ({new} new, {changed} changed, {removed} removed; {kept} verdicts kept) -> {rel(ledger_path(root), root)}')
        return 0

    if args.cmd in ('freeze', 'diff') and not (led.get('paper') and (root / led['paper']).exists()):
        print('no ledger or paper: run `claims.py extract <paper>` first' + (' (diff skipped)' if args.cmd == 'diff' else ''))
        return 2

    if args.cmd == 'next':
        todo = sorted(((i, c) for i, c in led['claims'].items() if c.get('status') != 'removed' and not c.get('verdict')),
                      key=lambda ic: (ic[1].get('status') != 'changed', ic[1].get('order', 0)))
        if not todo:
            print('no unchecked claims' + ('' if led['claims'] else ': run `claims.py extract <paper>` first'))
            return 0
        index = code_index(args.code or root, root)
        for i, c in todo[:args.n]:
            print(f'{i}  {c["where"]}  [{", ".join(c["kinds"])}]' + ('  CHANGED' if c.get('status') == 'changed' else ''))
            print(f'  "{short(c["text"], 300)}"')
            if c.get('was'):
                print(f'  was ({c["was"].get("verdict") or "unchecked"}): "{short(c["was"]["text"], 200)}"')
            hits = candidates(c['text'], index)
            for _, path, line, snippet in hits:
                print(f'  ? {path}:{line}  {short(snippet, 100)}')
            if not hits:
                print('  ? no code match: search by hand, or record --verdict unclear')
        print(f'{len(todo)} unchecked. Record each: claims.py record <id> --verdict '
              f'{"|".join(VERDICTS)} --evidence FILE:LINE [--note ...]')
        return 0

    if args.cmd == 'record':
        c = led['claims'].get(args.id)
        if not c or c.get('status') == 'removed':
            print(f'unknown or removed claim id: {args.id} (ids are printed by `claims.py next`)')
            return 2
        if args.verdict in ('supported', 'partial') and not args.evidence:
            print(f'--evidence FILE:LINE is required for {args.verdict}')
            return 2
        errors = [e for e in (evidence_ok(ev, root) for ev in args.evidence) if e]
        if errors:
            print('\n'.join(errors))
            return 2
        c.update(verdict=args.verdict, evidence=args.evidence, note=args.note, recorded=now(), status='current')
        save(root, led)
        print(f'{args.id}: {args.verdict}')
        return 0

    if args.cmd == 'report':
        counts, flagged, summary = publish(root, led)
        print(summary + f'; {counts["unclear"]} unclear, {counts["unchecked"]} unchecked, {counts["changed"]} changed, '
                        f'{counts["removed"]} removed')
        for c in flagged:
            tag = (c.get('verdict') or 'changed').upper()
            print(f'{tag:11s} {c["where"]}  "{short(c["text"])}"')
            extra = c.get('note') or (f'was {c["was"].get("verdict") or "unchecked"}' if c.get('was') else '')
            if c.get('evidence') or extra:
                print(f'            evidence: {", ".join(c.get("evidence") or ["-"])}' + (f'; {extra}' if extra else ''))
        return 1 if counts['unsupported'] else 0

    if args.cmd == 'freeze':
        extract(root / led['paper'], root, led)
        led['frozen'] = {i: {'text': c['text'], 'where': c['where']} for i, c in led['claims'].items() if c.get('status') != 'removed'}
        led['frozen_at'] = now()
        save(root, led)
        print(f'froze {len(led["frozen"])} claims; `claims.py diff` exits 1 if any of them changes')
        return 0

    # diff: the edit guard. Re-reads the paper, never writes the ledger.
    frozen = led.get('frozen') or {}
    if not frozen:
        print('no frozen claims: run `claims.py freeze` to protect them (diff skipped)')
        return 2
    current = all_sentences(root / led['paper'], root)
    ids = {s['id'] for s in current}
    broken = [(i, f) for i, f in frozen.items() if i not in ids]
    for i, f in broken:
        near = max(current, key=lambda s: similar(f['text'], s['text']), default=None)
        if near and similar(f['text'], near['text']) >= 0.5:
            print(f'CHANGED  {i}  {f["where"]}\n  was: "{short(f["text"], 200)}"\n  now: "{short(near["text"], 200)}"  ({near["where"]})')
        else:
            print(f'REMOVED  {i}  {f["where"]}  "{short(f["text"], 200)}"')
    if broken:
        print(f'{len(broken)} of {len(frozen)} frozen claims changed or removed; ask the authors, then re-run `claims.py freeze`')
        return 1
    print(f'{len(frozen)} frozen claims intact')
    return 0


if __name__ == '__main__':
    sys.exit(main())
