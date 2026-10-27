#!/usr/bin/env python3
"""Keep a paper's numbers, tables and figures in sync with the code that produced them.

  results.py build results/ -o paper/results.tex     JSON results -> \\res{key} macros (+ value history)
  results.py audit paper/                            hard-coded numbers, STALE numbers, undefined \\res keys
  results.py table results/main.csv -o paper/tables/main.tex [--bold-max acc] [--bold-min loss] [--decimals 1] [--pm]
  results.py stale [--manifest agentex-artifacts.json] [--paper paper/]   figures/tables older than their inputs
  results.py make  [--manifest agentex-artifacts.json] [--all]            rerun stale producers, record provenance + runtime/hardware

The manifest maps each output to the command and inputs that produce it, e.g.
  {"outputs": {"paper/figures/loss.pdf": {"cmd": "python scripts/plot.py", "inputs": ["scripts/plot.py", "results/*.json"]}}}
`make` runs those commands with the shell: only use manifests you wrote or reviewed. Stdlib only.
"""
import argparse
import csv
import glob
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REG_DEF = re.compile(r'\\@namedef\{agx@res@([^}]*)\}\{([^}]*)\}')
RES_USE = re.compile(r'\\res(?:pct)?\{([^}]*)\}')
SKIP_ARG_CMDS = {'label', 'ref', 'cref', 'Cref', 'eqref', 'autoref', 'pageref', 'nameref', 'input', 'include', 'subfile',
                 'includegraphics', 'url', 'href', 'begin', 'end', 'vspace', 'hspace', 'setlength', 'addtolength',
                 'hypersetup', 'usepackage', 'RequirePackage', 'documentclass', 'bibliography', 'addbibresource',
                 'res', 'respct', 'fpeval', 'newcommand', 'renewcommand', 'def', 'setcounter', 'addtocounter', 'sisetup', 'graphicspath',
                 'cite', 'citep', 'citet', 'parencite', 'textcite', 'autocite', 'nocite', 'resizebox', 'scalebox',
                 'rule', 'raisebox', 'multicolumn', 'cmidrule', 'arraystretch', 'pgfplotsset', 'tikzset', 'color'}
SKIP_ENVS = ('tikzpicture', 'axis', 'verbatim', 'lstlisting', 'minted', 'filecontents', 'comment', 'tikzcd')
NUMBER = re.compile(r'(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)(?![\w])')
UNIT_AFTER = re.compile(r'\s*(?:pt|cm|mm|in|em|ex|bp|pc|sp|mu)\b|\s*\\(?:line|text|column|paper)width|\s*\\(?:textheight|baselineskip)')
PERCENT_AFTER = re.compile(r'\s*\\%|\s*\\(?:percent|unit\{\\percent\})')


# ------------------------------------------------------------------ helpers

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def git_commit(cwd):
    try:
        c = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=cwd, capture_output=True, text=True, timeout=5)
        if c.returncode:
            return ''
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=cwd, capture_output=True, text=True, timeout=5).stdout
        return c.stdout.strip() + ('-dirty' if dirty.strip() else '')
    except (OSError, subprocess.SubprocessError):
        return ''


def agentex_dir(root):
    d = Path(root) / '.agentex'
    d.mkdir(parents=True, exist_ok=True)
    if not (d / '.gitignore').exists():
        (d / '.gitignore').write_text('*\n')
    return d


def project_root(path):
    """Nearest folder at or above `path` with .git or a manifest; else path's parent (where .agentex/status goes)."""
    p = Path(path).resolve()
    for d in [p, *p.parents]:
        if (d / '.git').exists() or (d / 'agentex-artifacts.json').exists():
            return d
    return p.parent


def severity(states):
    """Dashboard level for provenance states: ok/fresh pass, untracked/no-source warn, anything else fails."""
    bad = set(states) - {'ok', 'fresh'}
    return 'fail' if bad - {'untracked', 'no-source'} else 'warn' if bad else 'ok'


def write_status(root, tool, level, summary, counts, items):
    """Atomically write .agentex/status/<tool>.json for the dashboard; items are (where, message) pairs."""
    data = {'tool': tool, 'status': level, 'summary': summary[:100], 'counts': counts,
            'items': [{'where': w, 'message': m} for w, m in items[:20]],
            'updated': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    try:
        d = agentex_dir(root) / 'status'
        d.mkdir(exist_ok=True)
        tmp = d / f'.{tool}.{os.getpid()}.tmp'
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, d / f'{tool}.json')
    except OSError:
        pass  # the dashboard is cosmetic: never fail a check because its status file can't be written


def hardware():
    """Where producers run, recorded in the lock so the paper can report compute (NeurIPS checklist)."""
    hw = {'platform': platform.platform(), 'python': platform.python_version(), 'cpus': os.cpu_count()}
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                           capture_output=True, text=True, timeout=10)
        gpus = [g.strip() for g in r.stdout.splitlines() if g.strip()] if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        gpus = []
    if gpus:
        hw['gpus'] = gpus  # e.g. "NVIDIA A100-SXM4-80GB, 81920 MiB"
    return hw


def tex_escape(s):
    return re.sub(r'([&%$#_{}])', r'\\\1', str(s)).replace('~', r'\textasciitilde{}').replace('^', r'\textasciicircum{}')


def fmt(v, decimals):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        s = f'{round(v, decimals):.{decimals}f}'
        return s.rstrip('0').rstrip('.') if '.' in s else s
    if isinstance(v, str) and len(v) <= 60:
        return tex_escape(v)
    return None


def flatten(obj, prefix):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten(v, f'{prefix}.{re.sub(r"[^A-Za-z0-9_-]", "-", str(k))}' if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from flatten(v, f'{prefix}.{i}')
    else:
        yield prefix, obj


def json_files(paths):
    for p in map(Path, paths):
        yield from (sorted(p.rglob('*.json')) if p.is_dir() else [p])


# ------------------------------------------------------------------ build

def build(sources, out, decimals=4):
    out = Path(out)
    values, files = {}, []
    for f in json_files(sources):
        data = json.loads(f.read_text())
        files.append(f)
        for key, v in flatten(data, f.stem):
            s = fmt(v, decimals)
            if s is not None:
                values[key] = s
    hist_path = agentex_dir(out.parent) / 'results-history.json'
    try:
        history = json.loads(hist_path.read_text())
    except (OSError, ValueError):
        history = {}
    previous = {k: v for k, v in REG_DEF.findall(out.read_text())} if out.exists() else {}
    for k, old in previous.items():
        if values.get(k) != old:
            history[k] = (history.get(k, []) + [old])[-10:]
    hist_path.write_text(json.dumps(history, indent=1))

    commit = git_commit(out.parent)
    lines = ['% Generated by AgenTeX results.py -- do not edit; regenerate with `results.py build`.',
             f'% commit: {commit or "n/a"}  built: {datetime.now().isoformat(timespec="seconds")}']
    lines += [f'% source: {os.path.relpath(f, out.parent)}  sha256:{sha(f)[:12]}' for f in files]
    lines += ['\\makeatletter',
              '% \\res{key}: expandable, so \\num{\\res{key}} works; an unknown key prints a bold ??',
              '\\providecommand*{\\res}[1]{\\ifcsname agx@res@#1\\endcsname\\csname agx@res@#1\\endcsname\\else\\textbf{??}\\fi}',
              '% \\respct{key}: the value x100, for \\num[round-precision=1]{\\respct{acc}}\\,\\% (input this file in the preamble)',
              '\\@ifundefined{fpeval}{\\RequirePackage{xfp}}{}',
              '\\providecommand*{\\respct}[1]{\\fpeval{100*(\\res{#1})}}']
    lines += [f'\\@namedef{{agx@res@{k}}}{{{v}}}' for k, v in sorted(values.items())]
    lines += ['\\makeatother', '']
    tmp = out.with_suffix('.tmp')
    tmp.write_text('\n'.join(lines), encoding='utf-8')
    tmp.replace(out)
    changed = sorted(k for k in values if k in previous and previous[k] != values[k])
    return values, changed


# ------------------------------------------------------------------ audit

def blank(text, start, end):
    """Replace text[start:end] with spaces, keeping newlines so line numbers survive."""
    return text[:start] + re.sub(r'[^\n]', ' ', text[start:end]) + text[end:]


def group_end(text, i, open_ch, close_ch):
    """Index just past the group opening at text[i]; escaped delimiters (\\{) don't count."""
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == '\\':
            j += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(text)


# Mandatory {groups} to skip after these commands (default 1 for the rest of SKIP_ARG_CMDS);
# e.g. \multicolumn{3}{c}{content} skips the first two and keeps the content.
ARG_COUNT = {'multicolumn': 2, 'setlength': 2, 'addtolength': 2, 'setcounter': 2, 'addtocounter': 2,
             'newcommand': 2, 'renewcommand': 2, 'resizebox': 2}
EXTRA_BEGIN_ARGS = {'tabular': 1, 'array': 1, 'longtable': 1, 'tabu': 1, 'tabular*': 2, 'tabularx': 2}


def maskable(text):
    """Blank everything that is not prose or table content: comments, TikZ/verbatim environments,
    arguments of reference/layout commands, optional [arguments] and tabular column specs."""
    text = re.sub(r'(?<!\\)%.*', lambda m: ' ' * len(m[0]), text)
    for env in SKIP_ENVS:
        for m in list(re.finditer(r'\\begin\{%s\*?\}.*?\\end\{%s\*?\}' % (re.escape(env), re.escape(env)), text, re.S)):
            text = blank(text, m.start(), m.end())
    for m in list(re.finditer(r'\\([A-Za-z@]+)\*?', text)):
        name, j = m[1], m.end()
        todo = ARG_COUNT.get(name, 1) if name in SKIP_ARG_CMDS else 0
        while True:
            k = j
            while k < len(text) and text[k] in ' \t':
                k += 1
            if k < len(text) and text[k] == '[':          # optional args never hold reported results
                j = group_end(text, k, '[', ']')
            elif k < len(text) and text[k] == '{' and todo:
                arg_end = group_end(text, k, '{', '}')
                if name == 'begin':
                    todo += EXTRA_BEGIN_ARGS.get(text[k + 1:arg_end - 1].strip(), 0)
                j, todo = arg_end, todo - 1
            else:
                break
        if j > m.end() or name in SKIP_ARG_CMDS:
            text = blank(text, m.start(), j)
    return text


def numbers_in(text):
    """Yield (line, token, value, decimals, percent) for each number that could be a reported result."""
    masked = maskable(text)
    for m in NUMBER.finditer(masked):
        tok = m[1]
        if UNIT_AFTER.match(masked, m.end()):
            continue
        val = float(tok.replace(',', ''))
        decimals = len(tok.split('.')[1]) if '.' in tok else 0
        if decimals == 0 and (val < 100 or 1900 <= val <= 2099):
            continue  # small counts, section numbers, years
        if len(tok.replace(',', '').replace('.', '').lstrip('0')) < 2:
            continue  # one significant digit (0.3, 0.05) matches too many values to mean anything
        yield masked.count('\n', 0, m.start()) + 1, tok, val, decimals, bool(PERCENT_AFTER.match(masked, m.end()))


def matches(val, decimals, registry):
    """Registry keys whose value displays as `val` at this precision (directly or as a percentage)."""
    hits = []
    for key, s in registry.items():
        try:
            v = float(s)
        except ValueError:
            continue
        for scale, how in ((1, ''), (100, ' (x100)')):
            if round(v * scale, decimals) == val:
                hits.append(key + how)
                break
    return hits


def find_registry(paper):
    for p in sorted(Path(paper).rglob('*.tex')):
        if 'agx@res@' in p.read_text(encoding='utf-8', errors='replace')[:4000]:
            return p
    return None


def audit(paper, registry_path=None, max_ambiguous=3):
    paper = Path(paper)
    registry_path = Path(registry_path) if registry_path else find_registry(paper)
    registry = dict(REG_DEF.findall(registry_path.read_text())) if registry_path else {}
    try:
        history = json.loads((registry_path.parent / '.agentex' / 'results-history.json').read_text()) if registry_path else {}
    except (OSError, ValueError):
        history = {}
    # every past value of every key (a number two reruns old is still stale)
    old_values = {f'{k}@old{i}': v for k, vs in history.items() for i, v in enumerate(vs) if v != registry.get(k)}
    findings = []
    for f in sorted(paper.rglob('*.tex')):
        if registry_path and f.resolve() == registry_path.resolve():
            continue
        text = f.read_text(encoding='utf-8', errors='replace')
        if text.startswith('% Generated by AgenTeX'):
            continue  # generated tables are in sync by construction
        rel = os.path.relpath(f, paper)
        for m in RES_USE.finditer(re.sub(r'(?<!\\)%.*', '', text)):
            if m[1] not in registry:
                findings.append(('UNDEFINED', rel, text.count('\n', 0, m.start()) + 1, m[1], 'not in the registry'))
        for line, tok, val, dec, pct in numbers_in(text):
            cur = matches(val, dec, registry)
            if cur and len(cur) <= max_ambiguous:
                macro = 'respct' if '(x100)' in cur[0] else 'res'
                hint = f'\\num[round-mode=places,round-precision={dec}]{{\\{macro}{{{cur[0].split(" ")[0]}}}}}'
                findings.append(('HARD-CODED', rel, line, tok, f'= {", ".join(cur)}; use {hint}'))
                continue
            old = list(dict.fromkeys(re.sub(r'@old\d+$', '', k.split(' ')[0]) for k in matches(val, dec, old_values)))
            if old and not cur:
                now = ', '.join(f'{k}={registry.get(k, "?")}' for k in old[:3])
                findings.append(('STALE', rel, line, tok, f'matches an OLD value of {", ".join(old[:3])}; current: {now}'))
    return registry_path, findings


# ------------------------------------------------------------------ table

def table(csv_path, out, decimals=2, bold_max=(), bold_min=(), pm=False):
    rows = list(csv.reader(open(csv_path, newline='', encoding='utf-8')))
    header, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    cols = list(range(len(header)))
    std_of = {}
    if pm:  # pair X / X_std (or X_mean / X_std) into one "mean ± std" column
        for i, h in enumerate(header):
            base = re.sub(r'_mean$', '', h)
            j = next((j for j, g in enumerate(header) if g in (f'{base}_std', f'{base}_sd')), None)
            if j is not None and j != i:
                std_of[i] = j
        cols = [i for i in cols if i not in std_of.values()]

    def num(s):
        try:
            return float(s)
        except ValueError:
            return None

    best = {}
    for i in cols:
        name = re.sub(r'_mean$', '', header[i])
        vals = [num(r[i]) for r in body if i < len(r)]
        vals = [v for v in vals if v is not None]
        if vals and (name in bold_max or header[i] in bold_max):
            best[i] = max(vals)
        elif vals and (name in bold_min or header[i] in bold_min):
            best[i] = min(vals)

    def cell(r, i):
        v = num(r[i]) if i < len(r) else None
        if v is None:
            return tex_escape(r[i] if i < len(r) else '')
        s = f'{v:.{decimals}f}'
        if i in std_of and num(r[std_of[i]]) is not None:
            s += f' $\\pm$ {num(r[std_of[i]]):.{decimals}f}'
        return f'\\textbf{{{s}}}' if i in best and round(v, decimals) == round(best[i], decimals) else s

    spec = 'l' + 'r' * (len(cols) - 1)
    lines = [f'% Generated by AgenTeX results.py from {os.path.relpath(csv_path, Path(out).parent)} '
             f'(sha256:{sha(csv_path)[:12]}) -- regenerate, do not edit.',
             f'\\begin{{tabular}}{{@{{}}{spec}@{{}}}}', '\\toprule',
             ' & '.join(tex_escape(re.sub(r'_mean$', '', header[i])) for i in cols) + r' \\', '\\midrule']
    lines += [' & '.join(cell(r, i) for i in cols) + r' \\' for r in body]
    lines += ['\\bottomrule', '\\end{tabular}', '']
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text('\n'.join(lines), encoding='utf-8')


# ------------------------------------------------------------------ provenance

def load_manifest(path):
    path = Path(path)
    m = json.loads(path.read_text())
    return path.parent, m.get('outputs', m)


def expand_inputs(base, patterns):
    out = []
    for p in patterns:
        hits = sorted(glob.glob(str(base / p), recursive=True))
        out += [os.path.relpath(h, base) for h in hits if Path(h).is_file()] or [p]
    return sorted(set(out))


def status(base, outputs):
    lock_path = base / '.agentex' / 'artifacts.lock.json'
    try:
        lock = json.loads(lock_path.read_text())
    except (OSError, ValueError):
        lock = {}
    res = {}
    for out, spec in outputs.items():
        o = base / out
        inputs = expand_inputs(base, spec.get('inputs', []))
        missing_in = [i for i in inputs if not (base / i).exists()]
        if missing_in:
            res[out] = ('broken', f'input missing: {", ".join(missing_in)}')
        elif not o.exists():
            res[out] = ('missing', 'never built or deleted')
        elif out not in lock:
            res[out] = ('untracked', 'exists, but no recorded provenance: run make')
        else:
            rec = lock[out]
            changed = [i for i in inputs if rec['inputs'].get(i) != sha(base / i)]
            gone = sorted(set(rec['inputs']) - set(inputs))
            if changed or gone:
                res[out] = ('stale', 'changed inputs: ' + ', '.join(changed + [f'{g} (removed)' for g in gone]))
            elif rec.get('output') != sha(o):
                res[out] = ('modified', 'output differs from what its command produced (edited by hand?)')
            else:
                res[out] = ('ok', f'built {rec.get("made", "?")} at {rec.get("commit") or "no git"}')
    return res, lock


def make(manifest, everything=False):
    base, outputs = load_manifest(manifest)
    res, lock = status(base, outputs)
    # Outputs used as inputs by other outputs are rebuilt first.
    feeds = {o for o in outputs for spec in outputs.values() if o in expand_inputs(base, spec.get('inputs', []))}
    todo = sorted((o for o, (s, _) in res.items() if everything or s != 'ok'), key=lambda o: o not in feeds)
    report, host = [], hardware() if todo else {}
    for out in todo:
        spec = outputs[out]
        t0 = time.monotonic()
        r = subprocess.run(spec['cmd'], shell=True, cwd=base, capture_output=True, text=True)
        seconds = round(time.monotonic() - t0, 3)
        if r.returncode or not (base / out).exists():
            report.append((out, 'FAILED', (r.stderr or r.stdout).strip().splitlines()[-1:] or ['no output written']))
            continue
        lock[out] = {'inputs': {i: sha(base / i) for i in expand_inputs(base, spec.get('inputs', [])) if (base / i).exists()},
                     'output': sha(base / out), 'cmd': spec['cmd'], 'commit': git_commit(base),
                     'made': datetime.now().isoformat(timespec='seconds'), 'seconds': seconds, 'host': host}
        report.append((out, 'built', []))
    (agentex_dir(base) / 'artifacts.lock.json').write_text(json.dumps(lock, indent=1))
    return report


def untracked_includes(paper, base, outputs):
    """Figures/tables the paper includes that no manifest entry produces."""
    produced = {Path(os.path.normpath(base / o)).with_suffix('') for o in outputs}
    out = []
    for f in Path(paper).rglob('*.tex'):
        text = re.sub(r'(?<!\\)%.*', '', f.read_text(errors='replace'))
        for m in re.finditer(r'\\(?:includegraphics(?:\[[^\]]*\])?|input)\{([^}]+)\}', text):
            target = Path(os.path.normpath(Path(paper) / m[1])).with_suffix('')
            if target not in produced and 'results' not in m[1] and not m[1].startswith('sections'):
                out.append(m[1])
    return sorted(set(out))


# ------------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('sources', nargs='+')
    b.add_argument('-o', '--out', required=True)
    b.add_argument('--decimals', type=int, default=4, help='round floats to this many places (display rounding belongs in \\num)')
    a = sub.add_parser('audit')
    a.add_argument('paper')
    a.add_argument('--registry')
    t = sub.add_parser('table')
    t.add_argument('csv')
    t.add_argument('-o', '--out', required=True)
    t.add_argument('--decimals', type=int, default=2)
    t.add_argument('--bold-max', default='')
    t.add_argument('--bold-min', default='')
    t.add_argument('--pm', action='store_true', help='merge X/X_std column pairs into "mean ± std"')
    for name in ('stale', 'make'):
        s = sub.add_parser(name)
        s.add_argument('--manifest', default='agentex-artifacts.json')
        if name == 'stale':
            s.add_argument('--paper', help='also list included figures/tables with no recorded producer')
        else:
            s.add_argument('--all', action='store_true')
    args = ap.parse_args(argv)

    if args.cmd == 'build':
        values, changed = build(args.sources, args.out, args.decimals)
        print(f'{len(values)} values -> {args.out}' + (f'; changed since last build: {", ".join(changed)}' if changed else ''))
        if changed:
            print('run `results.py audit` to find stale numbers typed into the paper')
        return 0
    if args.cmd == 'audit':
        reg, findings = audit(args.paper, args.registry)
        if not reg:
            print('no registry found (a .tex containing \\@namedef{agx@res@...}); run `results.py build` first')
        for kind, f, line, tok, msg in sorted(findings, key=lambda x: ('STALE', 'UNDEFINED', 'HARD-CODED').index(x[0])):
            print(f'{kind:10s} {f}:{line}  {tok}  {msg}')
        counts = {k: sum(x[0] == k for x in findings) for k in ('STALE', 'UNDEFINED', 'HARD-CODED')}
        summary = ' · '.join(f'{k.lower()} {n}' for k, n in counts.items())
        print(summary + (f'  (registry: {reg})' if reg else ''))
        root = project_root(args.paper)
        write_status(root, 'numbers', 'fail' if counts['STALE'] or counts['UNDEFINED'] else 'warn' if findings else 'ok',
                     summary if reg else 'no registry found: run results.py build', {k.lower(): n for k, n in counts.items()},
                     [(f'{os.path.relpath(Path(args.paper).resolve() / f, root)}:{line}', f'{kind} {tok}: {msg}')
                      for kind, f, line, tok, msg in findings])
        return 1 if findings else 0
    if args.cmd == 'table':
        split = lambda s: {x.strip() for x in s.split(',') if x.strip()}
        table(args.csv, args.out, args.decimals, split(args.bold_max), split(args.bold_min), args.pm)
        print(f'wrote {args.out}')
        return 0
    if not Path(args.manifest).exists():
        print(f'no manifest at {args.manifest}; see `results.py --help` for the format')
        return 2
    if args.cmd == 'stale':
        base, outputs = load_manifest(args.manifest)
        res, _ = status(base, outputs)
        items = []
        for out, (st, msg) in sorted(res.items(), key=lambda kv: kv[1][0] == 'ok'):
            print(f'{st.upper():10s} {out}  {msg}')
            items.append((out, f'{st}: {msg}'))
        if args.paper:
            for u in untracked_includes(args.paper, base, outputs):
                print(f'NO-SOURCE  {u}  included in the paper, but no manifest entry produces it')
                items.append((u, 'no-source: included in the paper, but no manifest entry produces it'))
        states = [i[1].split(':')[0] for i in items]
        counts = {s: states.count(s) for s in dict.fromkeys(states)}
        write_status(base, 'provenance', severity(states), ' · '.join(f'{s} {n}' for s, n in counts.items()) or 'no outputs',
                     counts, [i for i in items if not i[1].startswith('ok:')])
        return 0 if all(s == 'ok' for s, _ in res.values()) else 1
    report = make(args.manifest, args.all)
    for out, st, err in report:
        print(f'{st:7s} {out}' + (f'  {err[0]}' if err else ''))
    print(f'{sum(s == "built" for _, s, _ in report)} built, {sum(s == "FAILED" for _, s, _ in report)} failed')
    return 1 if any(s == 'FAILED' for _, s, _ in report) else 0


if __name__ == '__main__':
    sys.exit(main())
