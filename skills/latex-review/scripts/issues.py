#!/usr/bin/env python3
"""Durable review-issue ledger: stable IDs across rounds, three terminal verdicts, a guard chain after edits
and a computed stopping rule, so the code (not the model) owns state, routing and when to stop.

  issues.py add --source self|reviewer:R2 --anchor sec/exp.tex:42 --severity major|minor --text "..."
  issues.py list [--open] [--source reviewer]
  issues.py verdict <id> invalid|fixable|author [--note ..] [--anchor file:line] [--severity major|minor]
  issues.py fix <id> [--commit SHA] [--note ..]           only issues with verdict 'fixable'
  issues.py reopen <id>
  issues.py round                                         start the next review round
  issues.py import-reviews reviews/R2.txt [--reviewer R2] one review per file, split into points
  issues.py guard [main.tex]                              build, refs, results audit, frozen claims: PASS/FAIL each
  issues.py stop [--max-rounds 3]                         exit 0 = stop (done, or cap reached); 1 = keep going
Global --project DIR (default .): the ledger is DIR/.agentex/issues.json and anchors are relative to DIR.
Every change also writes DIR/.agentex/status/review.json. Stdlib only.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent
SEVERITIES = ('major', 'minor')
VERDICTS = ('invalid', 'fixable', 'author')
MAX_ROUNDS = 3
MAX_SELF_PER_ROUND = 20  # bounds cost: a self-review that finds more keeps only the most important
GUARD_TIMEOUT = 600
SOURCE = re.compile(r'^(self|reviewer:[\w.-]{1,24})$')
ANCHOR = re.compile(r'^(?P<file>[^:]+?)(?::(?P<line>\d+))?$')

# import-reviews: section headings and list items in plain-text / OpenReview reviews
MINOR_HEAD = re.compile(r'minor|typo|nit', re.I)
MAJOR_HEAD = re.compile(r'weak|question|limitation|concern|major|claim|issue|problem|reference', re.I)
OTHER_MINOR_HEAD = re.compile(r'suggest|comment|feedback', re.I)
SKIP_HEAD = re.compile(r'summary|strength|rating|score|soundness|presentation|contribution|confidence|recommend|'
                       r'ethic|justification|flag|conduct|assessment|reproducib|excitement|dataset|software', re.I)
ITEM = re.compile(r'^(\s*)(?:[-*•–]|\(?\d{1,2}[.)]|\(?[a-z][.)]|[A-Za-z]{1,2}\d{1,2}[.:)])\s+(.*)$')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def short(text, n):
    text = ' '.join(text.split())
    return text if len(text) <= n else text[:n - 1] + '…'


# ------------------------------------------------------------------ storage

def agentex_dir(root):  # same contract as latex-results-sync/scripts/results.py
    d = Path(root) / '.agentex'
    d.mkdir(parents=True, exist_ok=True)
    if not (d / '.gitignore').exists():
        (d / '.gitignore').write_text('*\n')
    return d


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def load(root):
    p = Path(root) / '.agentex' / 'issues.json'
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    return {'rounds': [{'n': 1, 'started': now(), 'new': []}], 'issues': {}}


def save(root, ledger):
    write_atomic(agentex_dir(root) / 'issues.json', ledger)
    write_status(root, ledger)


def is_open(i):
    return i['verdict'] is None or (i['verdict'] == 'fixable' and not i['fixed'])


def write_status(root, ledger):
    """The dashboard contract: .agentex/status/review.json."""
    issues = list(ledger['issues'].values())
    opened = sorted((i for i in issues if is_open(i)), key=lambda i: i['severity'] != 'major')
    author = [i for i in issues if i['verdict'] == 'author']
    majors = sum(i['severity'] == 'major' for i in opened)
    n = ledger['rounds'][-1]['n']
    items = [{'where': i['anchor'] or '?', 'message': f"{i['id']} [{i['severity']}] {short(i['text'], 80)}"} for i in opened]
    items += [{'where': i['anchor'] or '?', 'message': f"{i['id']} author-required: {short(i['text'], 70)}"} for i in author]
    write_atomic(agentex_dir(root) / 'status' / 'review.json', {
        'tool': 'review',
        'status': 'fail' if majors else 'warn' if opened or author else 'ok',
        'summary': f'round {n}: {majors} open major, {len(opened) - majors} open minor, {len(author)} author-required',
        'counts': {'open major': majors, 'open minor': len(opened) - majors, 'author-required': len(author), 'round': n},
        'items': items[:20],
        'updated': now(),
    })


# ------------------------------------------------------------------ ledger operations

def norm(text):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text.lower()).split())


def issue_id(source, text):
    """Stable across rounds and re-imports: the same point from the same source always gets the same ID."""
    prefix = 'S' if source == 'self' else source.split(':', 1)[1]
    key = source + '\n' + norm(text)
    return prefix + '-' + hashlib.sha1(key.encode('utf-8')).hexdigest()[:6]


def check_anchor(root, anchor):
    """'file[:line]' relative to the project (a cwd-relative path is converted); ValueError if the file is missing."""
    m = ANCHOR.match(anchor.strip())
    if not m:
        raise ValueError(f'anchor must be file or file:line, got {anchor!r}')
    for base in (Path(root), Path.cwd()):
        p = (base / m['file']).resolve()
        if p.is_file():
            return os.path.relpath(p, Path(root).resolve()) + (f":{m['line']}" if m['line'] else '')
    raise ValueError(f"anchor file not found: {m['file']}")


def add(ledger, source, anchor, severity, text):
    """-> (id, created). A point already in the ledger is never duplicated or reset."""
    iid = issue_id(source, text)
    if iid in ledger['issues']:
        return iid, False
    cur = ledger['rounds'][-1]
    ledger['issues'][iid] = {'id': iid, 'source': source, 'anchor': anchor, 'severity': severity,
                             'text': ' '.join(text.split()), 'round': cur['n'], 'verdict': None, 'fixed': False,
                             'commits': [], 'notes': []}
    cur['new'].append(iid)
    return iid, True


def get(ledger, iid):
    if iid not in ledger['issues']:
        raise ValueError(f'no issue {iid}; see `issues.py list`')
    return ledger['issues'][iid]


def note(ledger, issue, kind, text):
    if text:
        issue['notes'].append(f"r{ledger['rounds'][-1]['n']} {kind}: {text}")


def set_verdict(ledger, iid, verdict, text='', anchor=None, severity=None):
    i = get(ledger, iid)
    if i['verdict'] != verdict:
        i['fixed'] = False
    i['verdict'] = verdict
    i['anchor'] = anchor or i['anchor']
    i['severity'] = severity or i['severity']
    note(ledger, i, verdict, text)
    return i


def fix(ledger, iid, commit=None, text=''):
    i = get(ledger, iid)
    if i['verdict'] != 'fixable':
        raise ValueError(f"{iid} has verdict {i['verdict'] or 'none'}; only 'fixable' issues are edited "
                         "(author-required ones are reported to the author)")
    i['fixed'] = True
    if commit and commit not in i['commits']:
        i['commits'].append(commit)
    note(ledger, i, 'fix', text)
    return i


def reopen(ledger, iid):
    i = get(ledger, iid)
    i['verdict'], i['fixed'] = None, False
    note(ledger, i, 'reopened', 'yes')
    return i


def new_round(ledger):
    prev = ledger['rounds'][-1]
    ledger['rounds'].append({'n': prev['n'] + 1, 'started': now(), 'new': []})
    return prev


def stop_check(ledger, max_rounds=MAX_ROUNDS):
    """-> (stop, lines). Done when the latest round raised no new valid major self-review issue, every major
    has a verdict and every fixable issue is fixed; otherwise stop anyway once the round cap is reached."""
    cur, issues = ledger['rounds'][-1], ledger['issues']
    new_major = [i for i in cur['new'] if issues[i]['source'] == 'self' and issues[i]['severity'] == 'major'
                 and issues[i]['verdict'] != 'invalid']
    no_verdict = [i['id'] for i in issues.values() if i['severity'] == 'major' and i['verdict'] is None]
    unfixed = [i['id'] for i in issues.values() if i['verdict'] == 'fixable' and not i['fixed']]
    missing = []
    if new_major:
        missing.append(f"round {cur['n']} raised {len(new_major)} new major issue(s): {' '.join(new_major)}"
                       ' (a later round must raise none)')
    if no_verdict:
        missing.append(f"{len(no_verdict)} major issue(s) without a verdict: {' '.join(no_verdict)}")
    if unfixed:
        missing.append(f"{len(unfixed)} fixable issue(s) not fixed: {' '.join(unfixed)}")
    author = [i['id'] for i in issues.values() if i['verdict'] == 'author']
    tail = [f"author-required (report, don't edit): {' '.join(author)}"] if author else []
    if not missing:
        counts = {v: sum(i['verdict'] == v for i in issues.values()) for v in VERDICTS}
        return True, [f"done: round {cur['n']}; {len(issues)} issues ({counts['fixable']} fixable, "
                      f"{counts['author']} author-required, {counts['invalid']} invalid)"] + tail
    if cur['n'] >= max_rounds:
        return True, [f'cap reached ({max_rounds} rounds); still missing:'] + ['  ' + m for m in missing] + tail
    return False, ['not done:'] + ['  ' + m for m in missing] + tail + \
        ['next: verdict/fix the above, run `guard`, then `round` and review again']


# ------------------------------------------------------------------ import-reviews

def header(line):
    """-> (kind, rest) when the line opens a review section (kind 'major'|'minor'|'skip'), else None."""
    s = line.strip()
    marked = s.startswith(('#', '**', '__'))
    s = re.sub(r'^#+\s*', '', s).replace('**', '').replace('__', '')
    name, colon, rest = s.partition(':')
    name, rest = name.strip(), rest.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z ,&/()'-]*", name) or len(name.split()) > 6:
        return None
    kind = ('minor' if MINOR_HEAD.search(name) else 'major' if MAJOR_HEAD.search(name)
            else 'minor' if OTHER_MINOR_HEAD.search(name) else 'skip' if SKIP_HEAD.search(name) else None)
    if kind is None:  # an unknown heading counts only when it looks like one; its points are kept
        return ('major', '') if marked or (colon and not rest) else None
    if not marked and not colon and len(name.split()) > 4:
        return None  # a sentence that happens to start with "Questions ..." etc.
    return kind, rest


def split_points(lines):
    """Numbered/bulleted items (nested bullets stay with their parent); else blank-line paragraphs."""
    if not any(ITEM.match(line) for line in lines):
        paras = re.split(r'\n\s*\n', '\n'.join(lines))
        return [' '.join(p.split()) for p in paras if p.strip()]
    items, base, lead_in = [], None, False
    for line in lines:
        m = ITEM.match(line)
        if m and (base is None or len(m[1]) <= base):
            base = len(m[1]) if base is None else base
            items.append([m[2]])
        elif items:
            items[-1].append(line.strip())
        elif line.strip():
            items.append([line.strip()])  # lead-in text before the first item
            lead_in = True
    points = [' '.join(' '.join(i).split()) for i in items]
    if lead_in and points[0].endswith(':'):
        points = points[1:]  # "The paper has these weaknesses:" is not a point
    return points


def parse_review(text):
    """-> [(severity, point)] from the critique sections (weaknesses, questions, comments...) of one review.
    Summary, strengths and score lines are skipped; a review with no headings is all critique."""
    sections, kind, buf, headed = [], None, [], False
    for line in text.splitlines():
        h = header(line)
        if h:
            sections.append((kind, buf))
            kind, buf, headed = h[0], [h[1]] if h[1] else [], True
        else:
            buf.append(line)
    sections.append((kind if headed else 'major', buf))
    out = []
    for kind, lines in sections:
        if kind not in SEVERITIES:
            continue
        for p in split_points(lines):
            if len(p.split()) < 3:
                continue  # "None.", "N/A", stray labels
            sev = 'minor' if re.match(r'\W*(minor|nit|typo)\b', p, re.I) else \
                'major' if re.match(r'\W*major\b', p, re.I) else kind
            out.append((sev, p))
    return out


# ------------------------------------------------------------------ guard

def find_main(root):
    """The shallowest main document under root (\\documentclass + \\begin{document}, not standalone)."""
    for p in sorted(Path(root).rglob('*.tex'), key=lambda p: (len(p.parts), str(p))):
        # shortcut: skips latexdiff output by name (main-diffv1.tex); pass main.tex explicitly if yours differs
        if {'.git', '.agentex'} & set(p.parts) or '-diff' in p.stem:
            continue
        t = p.read_text(encoding='utf-8', errors='replace')
        if re.search(r'^\s*\\documentclass', t, re.M) and '\\begin{document}' in t \
                and not re.search(r'\\documentclass\s*(\[[^\]]*\])?\s*\{standalone\}', t):
            return p
    return None


def run(script, args, cwd):
    """-> (returncode, output) of another skill's script; (None, '') when that skill is not installed."""
    if not script.exists():
        return None, ''
    try:
        p = subprocess.run([sys.executable, str(script), *args], cwd=str(cwd), capture_output=True, text=True,
                           timeout=GUARD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 1, f'timed out after {GUARD_TIMEOUT}s'
    return p.returncode, (p.stdout + '\n' + p.stderr).strip()


def guard(root, main):
    """-> [(check, PASS|FAIL|SKIP, detail, output)] for the chain every edit must pass."""
    paper, rows = main.parent, []
    rc, out = run(SKILLS / 'latex-debug' / 'scripts' / 'build.py', [str(main)], paper)
    lines = out.splitlines() or ['']
    rows.append(('build', 'SKIP' if rc in (None, 2) else 'PASS' if rc == 0 else 'FAIL', lines[0], out))

    rc, out = run(SKILLS / 'latex-references' / 'scripts' / 'check_refs.py', [str(paper)], paper)
    rows.append(('refs', 'SKIP' if rc is None else 'PASS' if rc == 0 else 'FAIL', (out.splitlines() or [''])[-1], out))

    rc, out = run(SKILLS / 'latex-results-sync' / 'scripts' / 'results.py', ['audit', str(paper)], paper)
    m = re.search(r'stale (\d+) · undefined (\d+) · hard-coded (\d+)', out)
    if rc is None:
        state = 'SKIP'
    elif m:  # hand-typed numbers are a warning, not an unsafe edit; stale or undefined \res values are
        state = 'FAIL' if int(m[1]) + int(m[2]) else 'PASS'
    else:
        state = 'PASS' if rc == 0 else 'FAIL'
    rows.append(('results', state, m[0] if m else (out.splitlines() or [''])[-1], out))

    rc, out = run(SKILLS / 'latex-consistency' / 'scripts' / 'claims.py', ['diff'], root)
    rows.append(('claims', 'SKIP' if rc is None or rc > 1 else 'PASS' if rc == 0 else 'FAIL',
                 (out.splitlines() or [''])[0], out))
    return rows


# ------------------------------------------------------------------ CLI

def fmt_issue(i):
    state = i['verdict'] or 'open'
    if i['verdict'] == 'fixable':
        state += ' fixed' if i['fixed'] else ' TODO'
    return f"{i['id']:10s} {i['severity']:5s} {state:13s} {i['anchor'] or '?':24s} {short(i['text'], 70)}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', type=Path, default=Path('.'), help='paper project holding .agentex/ (default .)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('add')
    a.add_argument('--source', required=True, help='self or reviewer:<name>')
    a.add_argument('--anchor', required=True, help='file:line')
    a.add_argument('--severity', required=True, choices=SEVERITIES)
    a.add_argument('--text', required=True)
    li = sub.add_parser('list')
    li.add_argument('--open', action='store_true', help='only issues without a verdict or fixable and not fixed')
    li.add_argument('--source', help="prefix filter, e.g. 'self', 'reviewer' or 'reviewer:R2'")
    v = sub.add_parser('verdict')
    v.add_argument('id')
    v.add_argument('verdict', choices=VERDICTS)
    v.add_argument('--note', default='')
    v.add_argument('--anchor', help='set or correct the location (file:line)')
    v.add_argument('--severity', choices=SEVERITIES)
    f = sub.add_parser('fix')
    f.add_argument('id')
    f.add_argument('--commit')
    f.add_argument('--note', default='')
    r = sub.add_parser('reopen')
    r.add_argument('id')
    sub.add_parser('round')
    im = sub.add_parser('import-reviews')
    im.add_argument('file', type=Path)
    im.add_argument('--reviewer', help='reviewer name (default: the file name, e.g. R2.txt -> R2)')
    g = sub.add_parser('guard')
    g.add_argument('main', nargs='?', type=Path)
    s = sub.add_parser('stop')
    s.add_argument('--max-rounds', type=int, default=MAX_ROUNDS)
    args = ap.parse_args(argv)
    root = args.project

    try:
        ledger = load(root)
    except ValueError as e:
        print(f'ledger unreadable ({e}); fix or move {root / ".agentex" / "issues.json"}')
        return 2

    try:
        if args.cmd == 'add':
            if not SOURCE.match(args.source):
                raise ValueError("--source must be 'self' or 'reviewer:<name>'")
            cur = ledger['rounds'][-1]
            iid = issue_id(args.source, args.text)
            if args.source == 'self' and iid not in ledger['issues'] and \
                    sum(ledger['issues'][i]['source'] == 'self' for i in cur['new']) >= MAX_SELF_PER_ROUND:
                print(f"cap: {MAX_SELF_PER_ROUND} new self-review issues in round {cur['n']}; keep the most important")
                return 1
            iid, created = add(ledger, args.source, check_anchor(root, args.anchor), args.severity, args.text)
            save(root, ledger)
            i = ledger['issues'][iid]
            print(f'added {iid}' if created else f"exists {iid} ({i['verdict'] or 'open'}{', fixed' if i['fixed'] else ''})")
            return 0
        if args.cmd == 'list':
            issues = [i for i in ledger['issues'].values()
                      if (not args.open or is_open(i)) and (not args.source or i['source'].startswith(args.source))]
            for i in sorted(issues, key=lambda i: (i['severity'] != 'major', not is_open(i))):
                print(fmt_issue(i))
            allv = list(ledger['issues'].values())
            print(f"{len(issues)} shown · {sum(map(is_open, allv))} open · "
                  f"{sum(i['verdict'] == 'author' for i in allv)} author-required · round {ledger['rounds'][-1]['n']}")
            return 0
        if args.cmd == 'verdict':
            anchor = check_anchor(root, args.anchor) if args.anchor else None
            i = set_verdict(ledger, args.id, args.verdict, args.note, anchor, args.severity)
            save(root, ledger)
            print(fmt_issue(i))
            return 0
        if args.cmd == 'fix':
            i = fix(ledger, args.id, args.commit, args.note)
            save(root, ledger)
            print(fmt_issue(i))
            return 0
        if args.cmd == 'reopen':
            i = reopen(ledger, args.id)
            save(root, ledger)
            print(fmt_issue(i))
            return 0
    except ValueError as e:
        print(e)
        return 2

    if args.cmd == 'round':
        prev = new_round(ledger)
        save(root, ledger)
        majors = sum(ledger['issues'][i]['severity'] == 'major' for i in prev['new'])
        print(f"round {prev['n'] + 1} started; round {prev['n']} raised {len(prev['new'])} new issue(s), {majors} major")
        return 0
    if args.cmd == 'import-reviews':
        name = args.reviewer or re.sub(r'[^\w.-]', '', args.file.stem)[:24] or 'R'
        source = f'reviewer:{name}'
        if not SOURCE.match(source):
            print(f'bad reviewer name {name!r} (letters, digits, . _ - only)')
            return 2
        points = parse_review(args.file.read_text(encoding='utf-8', errors='replace'))
        made = []
        for sev, text in points:
            iid, created = add(ledger, source, '', sev, text)
            if created:
                made.append((iid, sev, text))
        save(root, ledger)
        print(f"{name}: {len(made)} new point(s) ({sum(s == 'major' for _, s, _ in made)} major), "
              f"{len(points) - len(made)} already in the ledger")
        for iid, sev, text in made:
            print(f'  {iid:10s} {sev:5s} {short(text, 90)}')
        if made:
            print('next: triage each with `issues.py verdict <id> invalid|fixable|author --anchor file:line`')
        return 0
    if args.cmd == 'guard':
        main_tex = (args.main or find_main(root))
        if not main_tex or not main_tex.is_file():
            print('no main .tex found; pass it: issues.py guard paper/main.tex')
            return 2
        rows = guard(root.resolve(), main_tex.resolve())
        for check, state, detail, out in rows:
            print(f'{state} {check:8s} {short(detail, 90) if detail else ("not installed" if state == "SKIP" else "")}')
            if state == 'FAIL':
                print('\n'.join('    ' + short(line, 110) for line in out.splitlines()[:6] if line.strip()))
        return 1 if any(state == 'FAIL' for _, state, _, _ in rows) else 0
    if args.cmd == 'stop':
        done, lines = stop_check(ledger, args.max_rounds)
        print('\n'.join(lines))
        return 0 if done else 1
    return 2


if __name__ == '__main__':
    sys.exit(main())
