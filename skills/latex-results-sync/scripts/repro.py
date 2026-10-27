#!/usr/bin/env python3
"""Reproduction table per paper figure/table, a clean-checkout smoke test, and draft checklist evidence.

  repro.py table [--manifest agentex-artifacts.json] [--paper paper/] [--write README.md] [--apply]
  repro.py smoke [--manifest agentex-artifacts.json] [--outputs a,b] [--tolerance 1e-6]
  repro.py checklist [--manifest agentex-artifacts.json] [--paper paper/]

Rows come from the manifest and the lock that `results.py make` writes (input hashes, commit, runtime, hardware).
`smoke` runs the manifest's commands with the shell in a temporary `git worktree` of HEAD: only use manifests
you wrote or reviewed. Stdlib only.
"""
import argparse
import difflib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from results import expand_inputs, flatten, git_commit, group_end, load_manifest, severity, sha, status, write_status

START, END = '<!-- agentex:repro:start -->', '<!-- agentex:repro:end -->'
OUTER = ('figure', 'figure*', 'table', 'table*', 'wrapfigure', 'wraptable')
INCLUDE = re.compile(r'\\(includegraphics|input|include)\*?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
CODE_EXT = {'.py', '.ipynb', '.r', '.jl', '.m', '.sh', '.c', '.cc', '.cpp', '.cu', '.rs', '.go', '.java', '.scala', '.js', '.ts'}
SKIP_DIRS = {'node_modules', '__pycache__', 'venv', 'env', 'site-packages', 'build', 'dist'}
# Seeding calls with an argument: random.seed() / default_rng() without one seed from the clock.
SEED = re.compile(r'\b(?:random\.seed|default_rng|manual_seed(?:_all)?|set_seed|set_random_seed|seed_everything|PRNGKey'
                  r'|set\.seed|Random\.seed!)\s*\(\s*[^)\s]|use_deterministic_algorithms\s*\(\s*True')
UNCERTAINTY = re.compile(r'\\pm\b|±|standard (?:deviation|error)|confidence interval|\bstd\b|error bars?|\b9[05]\s*\\?%\s*CI\b', re.I)
CODE_LINK = re.compile(r'github\.com|gitlab\.com|bitbucket\.org|zenodo\.org|huggingface\.co|osf\.io|anonymous\.4open\.science'
                       r'|codeocean|(?:code|implementation)[^.\n]{0,40}\b(?:available|released)\b', re.I)
DATA_LINE = re.compile(r'^(?=.*\b(?:data ?sets?|corpus|corpora|benchmarks?)\b)(?=.*\\(?:cite\w*|url|href)\{).*$', re.I | re.M)


def strip_comments(text):
    return re.sub(r'(?<!\\)%.*', '', text)  # keeps newlines, so line numbers survive


def line_of(text, pos):
    return text.count('\n', 0, pos) + 1


# ------------------------------------------------------------------ where the paper uses each output

def main_docs(paper):
    for f in sorted(Path(paper).rglob('*.tex')):
        t = strip_comments(f.read_text(encoding='utf-8', errors='replace'))
        if '\\begin{document}' in t and re.search(r'\\documentclass\s*(?:\[[^\]]*\])?\s*\{(?!standalone)', t):
            yield f


def tex_tree(main):
    """(file, comment-free text) for main and every .tex it \\input/\\include's, resolved from main's folder like LaTeX."""
    seen, todo = set(), [main]
    while todo:
        f = todo.pop(0)
        if f.resolve() in seen or not f.is_file():
            continue
        seen.add(f.resolve())
        text = strip_comments(f.read_text(encoding='utf-8', errors='replace'))
        yield f, text
        for m in INCLUDE.finditer(text):
            p = main.parent / m[2].strip()
            if m[1] != 'includegraphics' and p.suffix in ('', '.tex'):
                todo.append(p.with_name(p.name + '.tex') if not p.suffix else p)


def describe(body):
    """(label, first words of the caption) of a float; the last ones, so a subfigure's don't shadow the figure's."""
    labels = re.findall(r'\\label\{([^}]*)\}', body)
    caps = list(re.finditer(r'\\caption\*?\s*(?:\[[^\]]*\])?\s*\{', body))
    words = ''
    if caps:
        i = caps[-1].end() - 1
        raw = re.sub(r'\\(?:label|ref|cref|Cref|cite\w*)\{[^}]*\}', '', body[i + 1:group_end(body, i, '{', '}') - 1])
        ws = re.sub(r'\\[A-Za-z@]+\*?|[{}$~\\]', ' ', raw).split()
        words = ' '.join(ws[:8]) + ('…' if len(ws) > 8 else '')
    return (labels[-1] if labels else ''), words


def paper_uses(paper, base, outputs):
    """{output: [(where, label, caption)]} and [(where, label, caption)] for figure/table floats no output feeds."""
    by_key = {Path(os.path.abspath(base / o)).with_suffix(''): o for o in outputs}
    uses, orphans = {}, []
    for main in main_docs(paper):
        files = list(tex_tree(main))
        gdirs = [''] + [d for _, t in files for g in re.findall(r'\\graphicspath\s*\{((?:\{[^}]*\})+)\}', t)
                        for d in re.findall(r'\{([^}]*)\}', g)]
        for f, text in files:
            where = lambda pos: f'{os.path.relpath(f, base)}:{line_of(text, pos)}'
            floats = []  # outermost figure/table environments: (start, end)
            for m in re.finditer(r'\\begin\{(%s)\}' % '|'.join(map(re.escape, OUTER)), text):
                e = re.search(r'\\end\{%s\}' % re.escape(m[1]), text[m.end():])
                if e and not any(s <= m.start() < t for s, t in floats):
                    floats.append((m.start(), m.end() + e.end()))
            fed = set()
            for m in INCLUDE.finditer(text):
                out = None
                for d in (gdirs if m[1] == 'includegraphics' else ['']):
                    p = Path(os.path.abspath(main.parent / d / m[2].strip()))
                    out = by_key.get(p) or by_key.get(p.with_suffix(''))
                    if out:
                        break
                if not out:
                    continue
                fl = next((s for s in floats if s[0] <= m.start() < s[1]), None)
                fed.add(fl)
                uses.setdefault(out, []).append((where(m.start()), *(describe(text[fl[0]:fl[1]]) if fl else ('', ''))))
            for s, t in floats:
                body = text[s:t]
                diagram = '\\begin{tikzpicture}' in body and '\\addplot' not in body  # drawn by hand, not from results
                if (s, t) not in fed and not diagram:
                    orphans.append((where(s), *describe(body)))
    return uses, orphans


# ------------------------------------------------------------------ table

def host_text(rec):
    if 'seconds' not in rec:
        return 'not recorded'
    h = rec.get('host', {})
    gpu = '; '.join(h.get('gpus', [])) or 'no GPU'
    return f'{rec["seconds"]:.1f} s, {h.get("platform", "?")}, {h.get("cpus", "?")} CPUs, {gpu}'


def rows(manifest, paper):
    """One dict per manifest output plus one per figure/table float with no producer (status no-source)."""
    base, outputs = load_manifest(manifest)
    res, lock = status(base, outputs)
    uses, orphans = paper_uses(paper or base, base, outputs)
    out = []
    for o in sorted(outputs):
        rec, ins = lock.get(o, {}), expand_inputs(base, outputs[o].get('inputs', []))
        hashed = [f'{i}@{(rec.get("inputs", {}).get(i) or (sha(base / i) if (base / i).is_file() else "missing"))[:8]}'
                  for i in ins]
        out.append({'paper': list(dict.fromkeys(uses.get(o, []))), 'output': o,
                    'cmd': outputs[o].get('cmd', ''), 'inputs': hashed[:4] + ([f'+{len(hashed) - 4} more'] if len(hashed) > 4 else []),
                    'commit': rec.get('commit', ''), 'run': host_text(rec), 'status': 'fresh' if res[o][0] == 'ok' else res[o][0]})
    for orphan in dict.fromkeys(orphans):  # a file \input by two main documents is seen twice
        out.append({'paper': [orphan], 'output': '', 'cmd': '', 'inputs': [],
                    'commit': '', 'run': '', 'status': 'no-source'})
    return base, out


def markdown(rs):
    cell = lambda s: str(s).replace('|', '\\|').replace('\n', ' ') or '–'
    loc = lambda u: ' '.join(x for x in (f'`{u[1]}`' if u[1] else '', f'"{u[2]}"' if u[2] else '', f'({u[0]})') if x)
    lines = ['| Figure / table | Output | Command | Inputs (sha256) | Commit | Last run | Status |', '|---' * 7 + '|']
    for r in rs:
        lines.append('| ' + ' | '.join(cell(x) for x in (
            '; '.join(map(loc, r['paper'])) or 'not in the paper', f'`{r["output"]}`' if r['output'] else '',
            f'`{r["cmd"]}`' if r['cmd'] else '', ', '.join(r['inputs']), r['commit'], r['run'], r['status'].upper())) + ' |')
    return '\n'.join(lines)


def write_block(path, block, apply):
    """Replace only the marked block in `path` (markers appended if absent); a unified diff unless apply."""
    p = Path(path)
    old = p.read_text(encoding='utf-8') if p.exists() else ''
    new_block = f'{START}\n{block}\n{END}'
    i = old.find(START)
    j = old.find(END, i) if i >= 0 else -1
    if (i >= 0) != (j >= 0) or (i < 0 and END in old):
        return f'{p}: found only one of {START} / {END}; fix the markers by hand'
    new = old[:i] + new_block + old[j + len(END):] if j >= 0 else old.rstrip('\n') + ('\n\n' if old.strip() else '') + new_block + '\n'
    if new == old:
        return f'{p}: reproduction table unchanged'
    if apply:
        p.write_text(new, encoding='utf-8')
        return f'wrote the reproduction table into {p}'
    sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), str(p), str(p)))
    return f'(diff only: rerun with --apply to write {p})'


# ------------------------------------------------------------------ smoke

def ordered(base, outputs):
    """Producers before consumers: an output that is another output's input is built first."""
    deps = {o: set(expand_inputs(base, s.get('inputs', []))) & set(outputs) - {o} for o, s in outputs.items()}
    done = []
    while len(done) < len(deps):
        ready = sorted(o for o in deps if o not in done and deps[o] <= set(done))
        done += ready or sorted(o for o in deps if o not in done)  # a cycle: just run the rest
    return done


def first_error(r):
    lines = [x.strip() for x in (r.stderr or r.stdout or '').splitlines() if x.strip()]
    i = next((k for k, x in enumerate(lines) if re.search(r'error|exception|fatal|not found|no such', x, re.I)), max(len(lines) - 3, 0))
    return ' | '.join(lines[i:i + 3]) or f'exit code {r.returncode}, no output written'


def same(a, b, tol):
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    if num(a) and num(b):
        return math.isclose(a, b, rel_tol=tol) or (a != a and b != b)  # NaN reproduces NaN
    return a == b


def compare(ref, new, tol):
    if not ref.exists():
        return 'built', 'no output in the working tree to compare against'
    if sha(ref) == sha(new):
        return 'reproduced', 'sha256 identical'
    if ref.suffix == '.json':
        try:
            a, b = (dict(flatten(json.loads(p.read_text()), '')) for p in (ref, new))
        except ValueError:
            return 'differs', 'not valid JSON'
        diff = sorted(k for k in a.keys() | b.keys() if k not in a or k not in b or not same(a[k], b[k], tol))
        if not diff:
            return 'reproduced', f'all values equal within relative tolerance {tol:g}'
        return 'differs', f'{len(diff)} keys differ: ' + ', '.join(f'{k} {a.get(k, "-")} -> {b.get(k, "-")}' for k in diff[:5])
    return 'differs', 'sha256 differs (PDFs and images often embed timestamps; compare them visually)'


def smoke(manifest, selected=(), tol=1e-6):
    """Rerun producers in a throwaway `git worktree` of HEAD and compare with the working-tree outputs."""
    base, outputs = load_manifest(manifest)
    base = base.resolve()
    top = Path(subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=base, capture_output=True, text=True,
                              check=True).stdout.strip()).resolve()
    todo = [o for o in ordered(base, outputs) if not selected or o in selected]
    report = [(o, 'failed', 'not an output in the manifest') for o in sorted(set(selected) - set(outputs))]
    tmp = Path(tempfile.mkdtemp(prefix='agentex-smoke-'))
    wt = tmp / 'checkout'
    try:
        subprocess.run(['git', 'worktree', 'add', '--detach', str(wt), 'HEAD'], cwd=top, capture_output=True, text=True, check=True)
        wbase = wt / base.relative_to(top)
        for o in todo:
            spec = outputs[o]
            if (wbase / o).is_file():
                (wbase / o).unlink()  # a committed copy must not pass as reproduced
            missing = [i for i in expand_inputs(wbase, spec.get('inputs', [])) if not (wbase / i).exists()]
            if missing:
                hint = ' (an output of another producer: add it to --outputs)' if set(missing) & set(outputs) else ' (uncommitted or ignored?)'
                report.append((o, 'failed', f'not in the HEAD checkout: {", ".join(missing[:3])}{hint}'))
                continue
            r = subprocess.run(spec['cmd'], shell=True, cwd=wbase, capture_output=True, text=True)
            if r.returncode or not (wbase / o).exists():
                report.append((o, 'failed', first_error(r)))
            else:
                report.append((o, *compare(base / o, wbase / o, tol)))
    finally:
        subprocess.run(['git', 'worktree', 'remove', '--force', str(wt)], cwd=top, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(['git', 'worktree', 'prune'], cwd=top, capture_output=True)
    return base, report


# ------------------------------------------------------------------ checklist

def grep(files, pattern, base, limit=5):
    hits = []
    for f in files:
        try:
            text = f.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        text = strip_comments(text) if f.suffix == '.tex' else text
        for m in pattern.finditer(text):
            line = text.splitlines()[line_of(text, m.start()) - 1].strip()
            hits.append(f'{os.path.relpath(f, base)}:{line_of(text, m.start())}  {line[:90]}')
            if len(hits) >= limit:
                return hits
    return hits


def code_files(base):
    for d, dirs, files in os.walk(base):
        dirs[:] = sorted(x for x in dirs if not x.startswith('.') and x not in SKIP_DIRS)
        yield from (Path(d) / f for f in sorted(files) if Path(f).suffix.lower() in CODE_EXT)


def checklist(manifest, paper):
    """Draft evidence per checklist question: pointers or 'not found', never a verdict."""
    base, outputs = load_manifest(manifest)
    _, lock = status(base, outputs)
    tex = sorted(Path(paper or base).rglob('*.tex'))
    timed = {o: r for o, r in lock.items() if 'seconds' in r}
    compute = []
    if timed:
        hosts = sorted({host_text(r).split(', ', 1)[1] for r in timed.values()})
        slow = max(timed, key=lambda o: timed[o]['seconds'])
        compute.append(f'.agentex/artifacts.lock.json  {len(timed)} recorded runs, {sum(r["seconds"] for r in timed.values()):.1f} s '
                       f'in total (longest: {slow}, {timed[slow]["seconds"]:.1f} s); hardware: {" / ".join(hosts)}')
    untimed = sorted(set(outputs) - set(timed))
    if untimed:
        compute.append(f'no runtime recorded for {", ".join(untimed[:3])}{" …" if len(untimed) > 3 else ""} '
                       '(run `results.py make --all`; work outside the manifest, e.g. training jobs, is never counted)')
    produced = set(outputs)
    data = sorted({i for s in outputs.values() for i in expand_inputs(base, s.get('inputs', []))
                   if i not in produced and Path(i).suffix.lower() not in CODE_EXT})
    manifest_pm = [f'{Path(manifest).name}: `{s["cmd"]}`' for s in outputs.values() if '--pm' in s.get('cmd', '')]
    repo = [n for n in sorted(os.listdir(base)) if re.match(r'(LICEN[CS]E|COPYING|README)', n, re.I)]
    sections = [
        ('Compute (type, memory, time per run and in total)', compute),
        ('Code availability', grep(tex, CODE_LINK, base) + ([f'repo root: {", ".join(repo)}'] if repo else [])),
        ('Random seeds', grep(list(code_files(base)), SEED, base)),
        ('Error bars / uncertainty', grep(tex, UNCERTAINTY, base) + manifest_pm),
        ('Data sources', ([f'manifest inputs (not code, not produced): {", ".join(data[:6])}' + (' …' if len(data) > 6 else '')]
                          if data else []) + grep(tex, DATA_LINE, base)),
    ]
    lines = ['DRAFT checklist evidence: pointers only, not answers. Check each one before filling in the venue checklist.']
    for title, ev in sections:
        lines.append(f'\n{title}')
        lines += [f'  - {e}' for e in ev] or ['  - not found']
    return '\n'.join(lines)


# ------------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('table', 'smoke', 'checklist'):
        s = sub.add_parser(name)
        s.add_argument('--manifest', default='agentex-artifacts.json')
        if name != 'smoke':
            s.add_argument('--paper', help='folder with the main .tex (default: the manifest folder)')
    t = sub.choices['table']
    t.add_argument('--write', metavar='README.md', help='replace the agentex:repro block in this file (diff unless --apply)')
    t.add_argument('--apply', action='store_true')
    s = sub.choices['smoke']
    s.add_argument('--outputs', default='', help='comma-separated outputs to reproduce (default: all)')
    s.add_argument('--tolerance', type=float, default=1e-6, help='relative tolerance for numbers in JSON outputs')
    args = ap.parse_args(argv)
    if not Path(args.manifest).exists():
        print(f'no manifest at {args.manifest}; see `results.py --help` for the format')
        return 2

    if args.cmd == 'table':
        base, rs = rows(args.manifest, args.paper)
        block = ('<!-- generated by AgenTeX repro.py table: edit agentex-artifacts.json, not this block -->\n'
                 + markdown(rs))
        print(write_block(args.write, block, args.apply) if args.write else block)
        states = [r['status'] for r in rs]
        counts = {s: states.count(s) for s in dict.fromkeys(states)}
        summary = ' · '.join(f'{s} {n}' for s, n in counts.items()) or 'no outputs in the manifest'
        print(summary)
        write_status(base, 'repro', severity(states), summary, counts,
                     [(r['paper'][0][0] if r['paper'] else r['output'], f'{r["status"]}: {r["output"] or "figure/table with no producer"}')
                      for r in rs if r['status'] != 'fresh'])
        return 0 if severity(states) == 'ok' else 1

    if args.cmd == 'checklist':
        print(checklist(args.manifest, args.paper))
        return 0

    try:
        base, report = smoke(args.manifest, {o.strip() for o in args.outputs.split(',') if o.strip()}, args.tolerance)
    except subprocess.CalledProcessError as e:
        print(f'smoke needs a git repository with a commit: {(e.stderr or "").strip()[:200]}')
        return 2
    if git_commit(base).endswith('-dirty'):
        print('note: uncommitted changes are not in the HEAD checkout that was rerun')
    for o, st, msg in report:
        print(f'{st.upper():10s} {o}  {msg}')
    counts = {s: sum(r[1] == s for r in report) for s in ('reproduced', 'differs', 'failed', 'built')}
    summary = ' · '.join(f'{s} {n}' for s, n in counts.items() if n) or 'nothing selected'
    print(summary)
    level = 'fail' if counts['differs'] or counts['failed'] else 'warn' if counts['built'] else 'ok'
    write_status(base, 'smoke', level, summary, counts, [(o, f'{st}: {msg}') for o, st, msg in report if st != 'reproduced'])
    return 0 if level == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
