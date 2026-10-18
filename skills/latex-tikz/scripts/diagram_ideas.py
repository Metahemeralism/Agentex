#!/usr/bin/env python3
"""Suggest diagrams a project's code could support, high-level and component-level.

Usage: diagram_ideas.py [project_dir] [--max 12] [--budget 3500]

Static analysis only: Python files and notebooks are parsed with `ast`, nothing is run.
Each idea names the TikZ pattern to start from (assets/pattern-<name>.tex) and the file:line
evidence, so the agent reads only those lines before drawing. Detects: entry-point pipelines,
artefact flow between scripts (files written/read), internal module architecture, object
composition, neural-network modules (layers, residuals), training and iterative loops,
time-stepping schemes, probabilistic models (sample/plate), einsum contractions, state enums,
class hierarchies and results files. Stdlib only.
"""
import argparse
import ast
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {'.git', '.venv', 'venv', 'env', 'node_modules', 'build', 'dist', '__pycache__', '.agentex',
             'arxiv_submission', 'site-packages', '.ipynb_checkpoints', '.tox', '.mypy_cache', 'paper'}
NN_BASES = {'Module', 'Model', 'Layer', 'LightningModule'}
DL_IMPORTS = ('torch', 'tensorflow', 'keras', 'jax', 'flax', 'equinox', 'haiku', 'lightning', 'pytorch_lightning')
ATTN = re.compile(r'attention|transformer|multihead', re.I)
CONV = re.compile(r'conv|pool', re.I)
WRITE_CALLS = {'savefig', 'to_csv', 'to_parquet', 'to_json', 'save', 'savez', 'savez_compressed', 'dump',
               'write_text', 'write_bytes', 'to_pickle', 'save_pretrained', 'to_netcdf', 'imwrite'}
READ_CALLS = {'read_csv', 'read_parquet', 'read_json', 'load', 'loadtxt', 'genfromtxt', 'read_text', 'read_pickle',
              'open_dataset', 'imread', 'from_pretrained', 'read_excel'}
STATE_NAME = re.compile(r'state|status|phase|mode|stage', re.I)
RESULT_DIRS = re.compile(r'(^|/)(results?|outputs?|logs?|metrics|runs|experiments)(/|$)', re.I)


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f'{base}.{node.attr}' if base else node.attr
    if isinstance(node, ast.Call):
        return dotted(node.func)
    return ''


def first_str(call):
    for a in call.args[:1]:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
        if isinstance(a, ast.JoinedStr):  # f"results/{name}.csv" -> results/*.csv
            return ''.join(v.value if isinstance(v, ast.Constant) else '*' for v in a.values)
    return None


def evaluation_order(node):
    """Post-order walk: inner calls before the call that wraps them, statements in order,
    so self.head(self.body(self.stem(x))) yields stem, body, head (the order they run)."""
    for child in ast.iter_child_nodes(node):
        yield from evaluation_order(child)
    yield node


def collapse(seq):
    """['Conv2d', 'Conv2d', 'ReLU'] -> ['Conv2d x2', 'ReLU']"""
    out = []
    for s in seq:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([s, 1])
    return [s if n == 1 else f'{s} x{n}' for s, n in out]


class Source:
    def __init__(self, path, rel, code, cell_starts=None):
        self.path, self.rel, self.code, self.cell_starts = path, rel, code, cell_starts
        self.tree = ast.parse(code)

    def where(self, node):
        line = getattr(node, 'lineno', 1)
        if self.cell_starts is None:
            return f'{self.rel}:{line}'
        cell = max(i for i, s in enumerate(self.cell_starts) if s <= line)
        return f'{self.rel} cell {cell + 1}'


def notebook_code(path):
    try:
        nb = json.loads(path.read_text(errors='replace'))
    except ValueError:
        return None, None
    lines, starts = [], []
    for cell in nb.get('cells', []):
        if cell.get('cell_type') != 'code':
            continue
        starts.append(len(lines) + 1)
        src = cell.get('source', '')
        src = ''.join(src) if isinstance(src, list) else src
        lines += ['# ' + l if l.lstrip().startswith(('%', '!')) else l for l in src.splitlines()]  # magics
    return '\n'.join(lines), starts


def load_sources(root):
    srcs, skipped = [], 0
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root)
        if not p.is_file() or any(part in SKIP_DIRS or part.startswith('.') for part in rel.parts[:-1]):
            continue
        try:
            if p.suffix == '.py':
                srcs.append(Source(p, str(rel), p.read_text(errors='replace')))
            elif p.suffix == '.ipynb':
                code, starts = notebook_code(p)
                if code:
                    srcs.append(Source(p, str(rel), code, starts))
        except (SyntaxError, ValueError):
            skipped += 1
    return srcs, skipped


def idea(level, pattern, title, detail, evidence, weight=1):
    return {'level': level, 'pattern': pattern, 'title': title, 'detail': detail, 'evidence': evidence, 'weight': weight}


# ------------------------------------------------------------------ detectors

def nn_modules(srcs, project_funcs):
    ideas, nn_names, classes = [], set(), []
    for s in srcs:
        dl = any(isinstance(n, (ast.Import, ast.ImportFrom)) and any(
            (getattr(n, 'module', None) or a.name).startswith(DL_IMPORTS) for a in n.names) for n in ast.walk(s.tree))
        for c in [n for n in ast.walk(s.tree) if isinstance(n, ast.ClassDef)]:
            classes.append((s, c, dl))
    changed = True
    while changed:  # project classes inheriting from project NN classes count too
        changed = False
        for s, c, dl in classes:
            bases = [dotted(b) for b in c.bases]
            if c.name not in nn_names and any((b.split('.')[-1] in NN_BASES and (dl or '.' in b)) or b in nn_names for b in bases):
                nn_names.add(c.name)
                changed = True
    for s, c, dl in classes:
        if c.name not in nn_names:
            continue
        attrs, init_order, fwd_order, residual = {}, [], [], False
        for fn in [n for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if fn.name in ('__init__', 'setup', 'build'):
                for n in ast.walk(fn):
                    if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Call):
                        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                        for t in targets:
                            if isinstance(t, ast.Attribute) and dotted(t.value) == 'self':
                                layer = dotted(n.value).split('.')[-1]
                                if layer in ('Sequential', 'ModuleList'):
                                    inner = [dotted(a).split('.')[-1] for a in n.value.args if isinstance(a, ast.Call)]
                                    layer = f'{layer}[{", ".join(collapse(inner))}]' if inner else layer
                                attrs[t.attr] = layer
                                init_order.append(layer)
            if fn.name in ('forward', '__call__', 'call'):
                for n in evaluation_order(fn):
                    if isinstance(n, ast.Call):
                        name = dotted(n.func)
                        if name.startswith('self.') and name[5:] in attrs:
                            fwd_order.append(attrs[name[5:]])
                        elif isinstance(n.func, ast.Call) and dotted(n.func).split('.')[0] in ('nn', 'hk', 'eqx'):
                            fwd_order.append(dotted(n.func).split('.')[-1])  # flax compact: nn.Dense(...)(x)
                        elif name.split('.')[0] in ('F', 'jax', 'torch') and name.split('.')[-1] in ('relu', 'gelu', 'softmax', 'dropout', 'tanh', 'sigmoid'):
                            fwd_order.append(name.split('.')[-1])
                    if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add) or \
                            isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and isinstance(n.left, ast.Name) and isinstance(n.right, (ast.Call, ast.Name)):
                        residual = True
        seq = fwd_order or init_order
        if not seq:
            continue
        subs = [l for l in seq if any(re.search(rf'\b{re.escape(nm)}\b', l) for nm in nn_names - {c.name})]
        everything = ' '.join(seq) + ' ' + c.name
        pattern = 'transformer' if ATTN.search(everything) else 'cnn' if CONV.search(everything) else \
            'mlp' if all(re.search(r'linear|dense|relu|gelu|tanh|sigmoid|dropout|norm', l, re.I) for l in seq) else 'cnn'
        detail = ' -> '.join(collapse(seq)) + (' (+ residual)' if residual else '')
        level = 'high' if subs else 'component'
        title = f'{"Model overview" if subs else "Architecture"} of {c.name}'
        ideas.append(idea(level, pattern, title, detail, s.where(c), weight=len(seq) + 3 * len(subs)))
    return ideas, nn_names


def loops(srcs):
    ideas = []
    for s in srcs:
        for fn in [n for n in ast.walk(s.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            loop_nodes = [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))]
            if not loop_nodes:
                continue
            calls = [dotted(n).split('.')[-1] for n in ast.walk(fn) if isinstance(n, ast.Call)]
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            if {'backward', 'step'} & set(calls) or {'apply_updates', 'apply_gradients', 'value_and_grad', 'grad'} & set(calls):
                steps = []
                for key, label in (('zero_grad', 'zero grads'), ('loss', 'loss'), ('criterion', 'loss'), ('backward', 'backprop'),
                                   ('value_and_grad', 'gradients'), ('step', 'optimizer step'), ('apply_updates', 'update params'),
                                   ('eval', 'evaluate'), ('validate', 'validate'), ('save', 'checkpoint')):
                    if any(key in c.lower() for c in calls) and label not in steps:
                        steps.append(label)
                if any(isinstance(n, ast.Break) for n in ast.walk(fn)):
                    steps.append('early stop')
                depth = 'nested epochs/batches' if any(isinstance(m, (ast.For, ast.While)) for l in loop_nodes for m in ast.walk(l) if m is not l) else 'single loop'
                ideas.append(idea('component', 'flowchart', f'Training loop {fn.name}()', f'{" -> ".join(steps)}; {depth}', s.where(fn), 4 + len(steps)))
                continue
            conv = {n for n in names if re.search(r'tol|eps|converg|max_iter|n_iter|residual', n, re.I)}
            if any(isinstance(l, ast.While) for l in loop_nodes) and conv:
                ideas.append(idea('component', 'flowchart', f'Iterative algorithm {fn.name}()',
                                  f'loop until {", ".join(sorted(conv)[:3])}', s.where(fn), 4))
                continue
            for l in loop_nodes:  # X[t + 1] = f(X[t]): a time-stepping scheme
                for n in ast.walk(l):
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.BinOp)
                                                         and isinstance(t.slice.op, ast.Add) for t in n.targets) or \
                            isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Tuple)
                                                              and any(isinstance(e, ast.BinOp) for e in t.slice.elts) for t in n.targets):
                        state = sorted({dotted(t.value) for t in n.targets if isinstance(t, ast.Subscript)})
                        ideas.append(idea('component', 'flowchart', f'Time-stepping scheme in {fn.name}()',
                                          f'updates {", ".join(state)}[t+1] from step t', s.where(fn), 5))
                        break
                else:
                    continue
                break
    return ideas


def pipelines(srcs, project_funcs):
    ideas = []
    for s in srcs:
        bodies = []
        for n in s.tree.body:
            if isinstance(n, ast.If) and 'main' in ast.unparse(n.test):
                bodies.append(('__main__', n.body, n))
            if isinstance(n, ast.FunctionDef) and n.name in ('main', 'run', 'pipeline', 'run_experiment', 'run_all'):
                bodies.append((f'{n.name}()', n.body, n))
        for label, body, node in bodies:
            steps = []
            for stmt in body:
                for c in [x for x in ast.walk(stmt) if isinstance(x, ast.Call)]:
                    name = dotted(c.func).split('.')[-1]
                    if name in project_funcs and name not in steps and name != label.rstrip('()'):
                        steps.append(name)
            if len(steps) >= 2:
                ideas.append(idea('high', 'pipeline', f'End-to-end pipeline ({s.rel})', ' -> '.join(steps[:8]), s.where(node), 10 + len(steps)))
    return ideas


def artefact_flow(srcs):
    writes, reads = defaultdict(set), defaultdict(set)
    for s in srcs:
        for c in [n for n in ast.walk(s.tree) if isinstance(n, ast.Call)]:
            name = dotted(c.func).split('.')[-1]
            path = first_str(c)
            if not path or not re.search(r'\.\w{2,7}$', path) or len(path) > 120:
                if name == 'open' and len(c.args) >= 1:
                    path = first_str(c)
                    mode = c.args[1].value if len(c.args) > 1 and isinstance(c.args[1], ast.Constant) else 'r'
                    if path and re.search(r'\.\w{2,7}$', path):
                        (writes if any(m in str(mode) for m in 'wa') else reads)[s.rel].add(path)
                continue
            if name in WRITE_CALLS:
                writes[s.rel].add(path)
            elif name in READ_CALLS or name == 'open':
                reads[s.rel].add(path)
    files = set().union(*writes.values(), *reads.values()) if (writes or reads) else set()
    linked = {f for f in files if any(f in w for w in writes.values()) and any(f in r for r in reads.values())}
    scripts = set(writes) | set(reads)
    if len(scripts) >= 2 and (linked or len(files) >= 4):
        chain = []
        for sc in sorted(scripts, key=lambda x: (not reads.get(x), x)):
            ins, outs = sorted(reads.get(sc, ())), sorted(writes.get(sc, ()))
            chain.append(f'{", ".join(ins[:2]) + " => " if ins else ""}{sc}{" => " + ", ".join(outs[:3]) if outs else ""}')
        return [idea('high', 'pipeline', 'Artefact flow between scripts', ' | '.join(chain[:6]),
                     f'{len(scripts)} scripts, {len(files)} files ({len(linked)} passed between scripts)', 9 + 2 * len(linked))]
    return []


def architecture(srcs):
    mods = {Path(s.rel).with_suffix('').as_posix().replace('/', '.'): s for s in srcs if s.cell_starts is None}
    short = defaultdict(set)
    for m in mods:
        parts = m.split('.')
        for i in range(len(parts)):
            short['.'.join(parts[i:])].add(m)
    edges = set()
    for m, s in mods.items():
        for n in ast.walk(s.tree):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                [n.module or ''] + [f'{n.module}.{a.name}' if n.module else a.name for a in n.names] if isinstance(n, ast.ImportFrom) else []
            for nm in names:
                for target in short.get(nm, ()):
                    if target != m:
                        edges.add((m.split('.')[-1], target.split('.')[-1]))
    nodes = {a for e in edges for a in e}
    if len(nodes) >= 3 and len(edges) >= 2:
        return [idea('high', 'pipeline', 'Codebase architecture (internal imports)',
                     ', '.join(f'{a} -> {b}' for a, b in sorted(edges)[:10]) + (' ...' if len(edges) > 10 else ''),
                     f'{len(nodes)} modules, {len(edges)} import edges', 5 + len(edges))]
    return []


def composition_and_hierarchy(srcs, nn_names):
    classes = {}
    for s in srcs:
        for c in [n for n in ast.walk(s.tree) if isinstance(n, ast.ClassDef)]:
            classes.setdefault(c.name, (s, c))
    uses, children, ideas = defaultdict(set), defaultdict(list), []
    for name, (s, c) in classes.items():
        for b in c.bases:
            if dotted(b).split('.')[-1] in classes and name not in nn_names:
                children[dotted(b).split('.')[-1]].append(name)
        for n in ast.walk(c):
            ref = dotted(n.func).split('.')[-1] if isinstance(n, ast.Call) else \
                dotted(n.annotation).split('.')[-1] if isinstance(n, ast.AnnAssign) else None
            if ref and ref in classes and ref != name:
                uses[name].add(ref)
    nodes = {a for a in uses} | {b for v in uses.values() for b in v}
    if len(nodes) >= 3 and not (nodes <= nn_names):
        root = max(uses, key=lambda k: len(uses[k]))
        ideas.append(idea('high', 'pipeline', f'Core objects: how {root} is composed',
                          '; '.join(f'{a} uses {", ".join(sorted(b))}' for a, b in sorted(uses.items())[:6]),
                          classes[root][0].where(classes[root][1]), 6 + len(nodes)))
    for base, kids in children.items():
        if len(kids) >= 2:
            s, c = classes[base]
            ideas.append(idea('component', 'tree', f'Class hierarchy of {base}', f'{base} -> {", ".join(sorted(kids)[:8])}', s.where(c), 3 + len(kids)))
    return ideas


def models_and_math(srcs):
    ideas = []
    for s in srcs:
        for fn in [n for n in ast.walk(s.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            latent, observed, plates, einsums = [], [], [], []
            for c in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
                name = dotted(c.func)
                label = first_str(c)
                last = name.split('.')[-1]
                if last == 'sample' and label:
                    (observed if any(k.arg in ('obs', 'observed') for k in c.keywords) else latent).append(label)
                elif re.match(r'^(pm|pymc|pymc3)\.[A-Z]', name) and label and not last.startswith(('Model', 'Data')):
                    (observed if any(k.arg in ('observed', 'obs') for k in c.keywords) else latent).append(label)
                elif last == 'plate' and label:
                    plates.append(label)
                elif last == 'einsum' and label:
                    einsums.append(label)
            if latent or observed:
                ideas.append(idea('component', 'pgm', f'Graphical model {fn.name}()',
                                  f'latent: {", ".join(latent[:6]) or "-"}; observed: {", ".join(observed[:4]) or "-"}'
                                  + (f'; plates: {", ".join(plates)}' if plates else ''), s.where(fn), 6 + len(latent) + len(observed)))
            if einsums:
                ideas.append(idea('component', 'matrix', f'Tensor shapes in {fn.name}()', '; '.join(f"einsum '{e}'" for e in einsums[:3]), s.where(fn), 3 + len(einsums)))
    return ideas


def state_enums(srcs):
    ideas = []
    for s in srcs:
        for c in [n for n in ast.walk(s.tree) if isinstance(n, ast.ClassDef)]:
            if any(dotted(b).split('.')[-1] in ('Enum', 'IntEnum', 'StrEnum', 'Flag') for b in c.bases) and STATE_NAME.search(c.name):
                members = [t.id for n in c.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
                if len(members) >= 3:
                    ideas.append(idea('component', 'fsm', f'State machine {c.name}', ', '.join(members[:8]), s.where(c), 4 + len(members)))
    return ideas


def results_files(root):
    ideas = []
    for p in sorted(root.rglob('*.csv')):
        rel = p.relative_to(root).as_posix()
        if any(part in SKIP_DIRS or part.startswith('.') for part in p.relative_to(root).parts[:-1]) or not RESULT_DIRS.search(rel):
            continue
        try:
            header = next(csv.reader(p.open(newline='', errors='replace')))
        except (StopIteration, OSError, csv.Error):
            continue
        ideas.append(idea('component', 'plot', f'Plot of {rel}', 'columns: ' + ', '.join(header[:8]), rel, 3))
        if len(ideas) >= 2:
            break
    return ideas


# ------------------------------------------------------------------ main

def suggest(root, max_ideas=12):
    root = Path(root).resolve()
    srcs, skipped = load_sources(root)
    project_funcs = {n.name for s in srcs for n in ast.walk(s.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    nn, nn_names = nn_modules(srcs, project_funcs)
    project_classes = {n.name for s in srcs for n in ast.walk(s.tree) if isinstance(n, ast.ClassDef)}
    found = pipelines(srcs, project_funcs | project_classes) + artefact_flow(srcs) + architecture(srcs) + \
        composition_and_hierarchy(srcs, nn_names) + nn + loops(srcs) + models_and_math(srcs) + state_enums(srcs) + results_files(root)
    seen, ideas = set(), []
    for i in sorted(found, key=lambda x: (x['level'] != 'high', -x['weight'])):
        if (i['title'], i['detail']) not in seen:
            seen.add((i['title'], i['detail']))
            ideas.append(i)
    high = [i for i in ideas if i['level'] == 'high'][:max(3, max_ideas // 3)]
    comp = [i for i in ideas if i['level'] == 'component'][:max_ideas - len(high)]
    others = sorted({p.suffix for p in root.rglob('*') if p.suffix in ('.m', '.jl', '.R', '.r', '.cpp', '.c', '.rs', '.go', '.f90', '.java')
                     and not any(part in SKIP_DIRS for part in p.relative_to(root).parts)})
    return high, comp, len(srcs), skipped, others


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project', nargs='?', default='.', type=Path)
    ap.add_argument('--max', type=int, default=12, help='max ideas (default 12)')
    ap.add_argument('--budget', type=int, default=3500, help='max characters printed')
    args = ap.parse_args(argv)
    high, comp, n, skipped, others = suggest(args.project, args.max)
    lines = [f'Diagram ideas for {args.project} ({n} Python files/notebooks parsed'
             + (f', {skipped} unparseable' if skipped else '') + ')']
    for tag, group in (('HIGH-LEVEL', high), ('COMPONENT', comp)):
        if group:
            lines.append(tag)
            prefix = tag[0]
            lines += [f' {prefix}{k} [{i["pattern"]}] {i["title"]}: {i["detail"]}  <- {i["evidence"]}' for k, i in enumerate(group, 1)]
    if not high and not comp:
        lines.append('no structure detected automatically; read the README and entry points and propose ideas by hand')
    if others:
        lines.append(f'not analysed (non-Python sources: {" ".join(others)}): read those entry points by hand')
    out = ''
    for l in lines:
        if len(out) + len(l) > args.budget:
            out += '... (truncated; raise --budget)\n'
            break
        out += l + '\n'
    print(out, end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
