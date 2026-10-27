#!/usr/bin/env python3
"""Find experiment settings in the code that the paper never discloses, or discloses with another value.

  settings_audit.py <code_dir> <paper_dir_or_main.tex> [--limit 20] [--root DIR]

Reads settings from JSON, YAML (common subset), INI, TOML (Python 3.11+ tomllib), argparse defaults,
dataclass/config-class fields, module constants and literal keyword arguments of known ML calls
(AdamW(lr=...), DataLoader(batch_size=...)) via `ast`; code is never executed. Then reads the paper
(\\input tree, comments stripped, \\res{} values from a results.py registry) and classifies each setting:
  MISMATCH     the paper names the setting with a different value
  UNDISCLOSED  the setting appears nowhere in the paper (a "paper omission")
  NO-VALUE     the paper names the setting but never gives its value
  DISCLOSED    the value sits next to the name or a synonym (1e-3 = 0.001 = $10^{-3}$, 0.1 = 10\\%)
Noise (paths, logging, devices, I/O workers) is ignored. Status: <root>/.agentex/status/settings.json.
Exit 1 on any MISMATCH or UNDISCLOSED. Stdlib only.
"""
import argparse
import ast
import bisect
import configparser
import json
import math
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11: TOML configs are skipped with a note
    tomllib = None

SKIP_DIRS = {'node_modules', '__pycache__', 'venv', 'env', 'build', 'dist', 'site-packages', 'results', 'outputs',
             'logs', 'runs', 'wandb', 'mlruns', 'checkpoints', 'data', 'datasets', 'figures', 'tests', 'test', 'docs',
             'paper', 'arxiv_submission'}
SKIP_FILES = {'package.json', 'package-lock.json', 'tsconfig.json', 'pyproject.toml', 'setup.cfg', 'tox.ini', 'pytest.ini',
              'mypy.ini', 'environment.yml', 'environment.yaml', 'docker-compose.yml', 'mkdocs.yml', 'codecov.yml',
              'agentex-artifacts.json', 'CITATION.cff', 'setup.py', 'conftest.py'}
CONFIG_EXT = {'.json', '.yaml', '.yml', '.toml', '.ini', '.cfg'}
MAX_BYTES = 200_000  # larger JSON/YAML files are data, not configuration

OPTIMIZERS = {'sgd': r'sgd|stochastic\s+gradient\s+descent', 'adamw': 'adamw', 'adam': 'adam', 'rmsprop': 'rmsprop',
              'adagrad': 'adagrad', 'adadelta': 'adadelta', 'adamax': 'adamax', 'nadam': 'nadam', 'radam': 'radam',
              'lbfgs': r'l-?bfgs', 'adafactor': 'adafactor', 'lion': 'lion', 'lamb': 'lamb', 'muon': 'muon'}
# (canonical name, importance 1-10, code identifiers (full match), paper wording); first code match wins
CANON = [(n, w, re.compile(c), re.compile(p)) for n, w, c, p in [
    ('dropout', 7, r'\w*dropout\w*|drop_(?:rate|prob)|p_drop', r'drop[\s-]?out(?:\s+(?:rate|probability))?'),
    ('learning rate', 10, r'(?:base_|init_|initial_|peak_|max_)?(?:lr|learning_rate)0?', r'learning[\s-]+rates?|(?<!\w)lr\b|(?<!\w)eta\b'),
    ('batch size', 10, r'(?:train_|per_device_train_|global_|mini_)?batch_size|bs|batch',
     r'(?:mini-?)?batch[\s-]+sizes?|mini-?batch(?:es)?(?:\s+of)?|batch(?:es)?\s+of'),
    ('epochs', 10, r'(?:num_|n_|max_|num_train_|train_)?epochs?', r'epochs?\b'),
    ('warmup', 8, r'(?:num_)?warm_?up(?:_steps|_ratio|_epochs|_iters|_proportion)?',
     r'warm[\s-]?up(?:\s+(?:steps|ratio|epochs|iterations|period|phase))?'),
    ('training steps', 9, r'(?:max|num|total|train|num_train|n)_(?:steps|iters|iterations|updates)|max_iter|n_iter|iterations',
     r'(?:training\s+|gradient\s+|optimi[sz]ation\s+)?(?:steps|iterations|updates)\b'),
    ('optimizer', 10, r'optimi[sz]er(?:_name|_type)?|optim|opt', r'(?<!\w)(?:%s)\b' % '|'.join(OPTIMIZERS.values())),
    ('weight decay', 9, r'weight_decay|wd|l2(?:_reg|_penalty|_lambda)?|lambda_l2',
     r'weight[\s-]+decay|(?<!\w)l_?2(?:[\s-]+(?:penalty|regulari[sz]\w*|norm))?\b'),
    ('seed', 8, r'(?:random_|global_|manual_)?seeds?|random_state', r'(?:random\s+)?seeds?\b|random[\s_]state'),
    ('data split', 9, r'(?:test|val|valid|validation|train|dev|holdout)_(?:size|split|ratio|frac|fraction|pct)|split_ratio|validation_split',
     r'(?:train(?:ing)?|test|validation|val|dev|held[\s-]?out)\s+(?:sets?|splits?|size|fraction|portion)|splits?\b'),
    ('folds', 8, r'(?:n_|num_|k_)?(?:splits|folds)|k_?fold|cv', r'folds?\b|cross[\s-]+validation'),
    ('gradient clipping', 8, r'(?:grad|gradient)_clip\w*|clip_grad\w*|max_grad_norm|gradient_clip_val|clip_(?:norm|value)|max_norm|grad_norm_clip',
     r'(?:gradient|grad\.?)(?:\s+norm)?\s+clipp?\w*|clipp?\w*\s+(?:the\s+)?gradients?(?:\s+norms?)?|max(?:imum)?\s+(?:gradient|grad\.?)\s+norm'),
    ('label smoothing', 7, r'label_smoothing(?:_factor)?|smoothing', r'label[\s-]+smoothing'),
    ('scheduler', 7, r'(?:lr_)?schedul(?:er|e)(?:_type|_name)?|lr_policy',
     r'schedul\w*|cosine(?:\s+anneal\w*)?|one[\s-]?cycle|(?:linear|step|exponential|polynomial)\s+decay|plateau'),
    ('betas', 6, r'(?:adam_)?(?:betas|beta_?[12])|b[12]', r'(?<!\w)betas?(?:_?[12])?\b'),
    ('momentum', 6, r'momentum', r'momentum'),
    ('gradient accumulation', 6, r'(?:grad|gradient)_accum\w*|accum(?:ulate)?_\w+|accumulation_steps', r'(?:gradient\s+)?accumulat\w*'),
    ('sequence length', 6, r'max_(?:seq_|source_|target_|input_)?(?:len|length)|seq_len(?:gth)?|block_size|context_len(?:gth)?',
     r'(?:max(?:imum)?\.?\s+)?(?:sequence|context|input)\s+length|block\s+size'),
    ('hidden size', 6, r'hidden_(?:size|dim|units)|d_model|n_embd|embed(?:ding)?_(?:dim|size)',
     r'hidden\s+(?:size|dim\w*|units?|width)|(?<!\w)d_model|model\s+dimension\w*|embedding\s+(?:size|dim\w*)'),
    ('layers', 6, r'(?:num_|n_)?(?:hidden_)?layers|n_layer|depth|num_blocks', r'layers?\b|depth\b'),
    ('attention heads', 6, r'(?:num_|n_)?(?:attention_)?heads|n_head', r'(?:attention\s+)?heads?\b'),
    ('temperature', 5, r'temperature|temp|tau', r'temperature|(?<!\w)tau\b'),
    ('early stopping', 5, r'(?:early_stopping_)?patience', r'patience|early[\s-]+stopping'),
    ('ema', 5, r'ema(?:_decay|_rate)?', r'(?<!\w)ema\b|exponential(?:ly)?\s+moving\s+average'),
    ('mixed precision', 5, r'fp16|bf16|amp|use_amp|mixed_precision|precision',
     r'mixed[\s-]+precision|(?<!\w)(?:fp|bf)16\b|b?float16|half[\s-]+precision|(?<!\w)amp\b'),
    ('epsilon', 4, r'(?:adam_)?eps(?:ilon)?', r'(?<!\w)epsilon\b'),
]]
STRING_CANON = {'optimizer', 'scheduler', 'mixed precision'}
NOISE = re.compile(r'(?:\w*_)?(?:path|paths|dir|dirs|directory|file|files|filename|fname|root|log|logs|logging|logger|verbose|'
                   r'verbosity|debug|print|save|saving|ckpt|checkpoint|checkpointing|device|devices|gpu|gpus|cuda|cpu|accelerator|'
                   r'workers|pin_memory|port|host|url|uri|wandb|tensorboard|mlflow|comet|project|entity|run_name|exp_name|'
                   r'experiment|tag|tags|cache|tqdm|progress|interval|every|freq|frequency|local_rank|world_size|distributed|'
                   r'backend|ddp|nccl|timeout|version|resume|profile|profiler|nproc|threads|n_jobs|jobs|prefetch_factor|'
                   r'persistent_workers|shuffle|drop_last|plot|fig|figsize|dpi|color|font|fontsize|email|user|password|token|'
                   r'secret|api_key|hydra|defaults|batch_first|inplace|bias|non_blocking|return_dict|report_to|do_train|do_eval|'
                   r'overwrite_output_dir|remove_unused_columns)(?:_\w*)?')
GENERIC_KEYS = {'name', 'type', 'value', 'kind', 'class', 'target', 'cls', 'id', 'default'}
DATA_FILTER = re.compile(r'(?:min|max)_\w+|\w*filter\w*|\w*threshold\w*|\w*subsample\w*|(?:max_|num_|n_)?(?:train_|eval_)?samples|dedup\w*|\w*_frac(?:tion)?')
ML_CALLS = {'DataLoader', 'TrainingArguments', 'Seq2SeqTrainingArguments', 'Trainer', 'EarlyStopping', 'train_test_split',
            'KFold', 'StratifiedKFold', 'GroupKFold', 'Dropout', 'CrossEntropyLoss', 'LoraConfig', 'generate',
            'TransformerEncoderLayer', 'TransformerDecoderLayer', 'Transformer', 'MultiheadAttention', 'LSTM', 'GRU',
            'LogisticRegression', 'RandomForestClassifier', 'RandomForestRegressor', 'GradientBoostingClassifier',
            'GradientBoostingRegressor', 'XGBClassifier', 'XGBRegressor', 'LGBMClassifier', 'LGBMRegressor', 'SVC', 'SVR',
            'MLPClassifier', 'MLPRegressor', 'KMeans', 'PCA', 'Ridge', 'Lasso', 'ElasticNet', 'clip_grad_norm_'}
POSITIONAL = {'Dropout': (0, 'dropout'), 'clip_grad_norm_': (1, 'max_grad_norm'), 'clip_grad_value_': (1, 'clip_value'),
              'manual_seed': (0, 'seed'), 'manual_seed_all': (0, 'seed'), 'seed': (0, 'seed'), 'set_seed': (0, 'seed'),
              'seed_everything': (0, 'seed')}
CONFIG_CLASS = re.compile(r'(?:Config|Args|Arguments|Params|Hparams|HParams|Settings|Hyperparameters)$')
SCHED_WORDS = [('cosine', 'cosine'), ('cycle', r'one[\s-]?cycle'), ('plateau', 'plateau'), ('exponential', 'exponential'),
               ('poly', 'polynomial'), ('linear', 'linear'), ('step', r'step(?:\s+decay|[\s-]+(?:lr|schedule))|multi[\s-]?step'),
               ('constant', 'constant')]
FILLER = {'num', 'n', 'nb', 'number', 'of', 'use', 'is', 'do', 'enable', 'total', 'k'}
ABBREV = {'min': r'min(?:imum)?', 'max': r'max(?:imum)?', 'dim': r'dim(?:ension)?', 'len': r'len(?:gth)?', 'prob': r'prob(?:ability)?',
          'aug': r'aug(?:ment)?', 'emb': r'emb(?:edding)?', 'reg': r'reg(?:ulari[sz]ation)?', 'coef': r'coef(?:ficient)?'}

# ---------------------------------------------------------------- shared plumbing (claims.py imports these)

INPUT = re.compile(r'\\(?:input|include|subfile)\s*\{([^}]+)\}')
MAIN = re.compile(r'^\s*\\documentclass\s*(?:\[[^\]]*\])?\s*\{(?!standalone)', re.M)
REG_DEF = re.compile(r'\\@namedef\{agx@res@([^}]*)\}\{([^}]*)\}')  # results.py registry format
NUM = re.compile(r'(?<![\w.])(-?(?:\d{1,3}(?:,\d{3})+|\d*\.\d+|\d+)(?:e[-+]?\d+)?)(?:([kmb])(?!\w)|(?!\w))(\s*%)?')
BOUNDARY = re.compile(r'\.\s|\n\s*\n|;')
GREEK = re.compile(r'\\(?:var)?(eta|beta|epsilon|lambda|tau|alpha|gamma|mu|rho|ell)(?![a-zA-Z])')
REFS = re.compile(r'\\(?:[a-zA-Z]*ref|label|[a-zA-Z]*cite[a-zA-Z]*|url|href|includegraphics|input|include)\*?(?:\[[^\]]*\])*\{[^}]*\}')


def find_root(explicit=None):
    """--root, else the nearest folder (from cwd up) that already has .agentex/, else cwd."""
    if explicit:
        return Path(explicit).resolve()
    cwd = Path.cwd().resolve()
    return next((d for d in [cwd, *cwd.parents] if (d / '.agentex').is_dir()), cwd)


def agentex_dir(root):
    d = Path(root) / '.agentex'
    d.mkdir(parents=True, exist_ok=True)
    if not (d / '.gitignore').exists():
        (d / '.gitignore').write_text('*\n')
    return d


def atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def write_status(root, tool, status, summary, counts, items):
    """<root>/.agentex/status/<tool>.json, the contract the dashboard reads."""
    d = agentex_dir(root) / 'status'
    d.mkdir(exist_ok=True)
    atomic_write(d / f'{tool}.json', json.dumps({
        'tool': tool, 'status': status, 'summary': summary[:100], 'counts': counts,
        'items': [{'where': w, 'message': m} for w, m in items[:20]],
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}, indent=1))


def rel(p, root):
    try:
        return Path(p).resolve().relative_to(root).as_posix()
    except ValueError:
        return Path(p).as_posix()


def strip_comments(text):
    return re.sub(r'(?<!\\)%.*', '', text)


def paper_files(paper):
    """-> ([(path, comment-stripped text)] along the \\input tree, results registry {key: value})."""
    paper = Path(paper)
    base = paper if paper.is_dir() else paper.parent
    texs = sorted(p for p in base.rglob('*.tex') if not {'.git', '.agentex', 'arxiv_submission'} & set(p.relative_to(base).parts))
    text_of = {p.resolve(): strip_comments(p.read_text(encoding='utf-8', errors='replace')) for p in texs}
    if paper.is_file():
        text_of.setdefault(paper.resolve(), strip_comments(paper.read_text(encoding='utf-8', errors='replace')))
    registry = {k: v for t in text_of.values() if 'agx@res@' in t for k, v in REG_DEF.findall(t)}
    if paper.is_file():
        mains = [paper.resolve()]
    else:
        mains = ([p for p, t in text_of.items() if MAIN.search(t) and '\\begin{document}' in t]
                 or sorted(p for p, t in text_of.items() if not re.search(r'\\documentclass[^{]*\{standalone\}', t)))
    order, seen = [], set()

    def visit(p, main_dir):
        p = p.resolve()
        if p in seen or not p.is_file():
            return
        seen.add(p)
        text = text_of.get(p) or strip_comments(p.read_text(encoding='utf-8', errors='replace'))
        if 'agx@res@' in text:
            return  # the registry itself is definitions, not prose
        order.append((p, text))
        for m in INPUT.finditer(text):
            q = Path(m[1].strip())
            q = q if q.suffix else q.with_suffix('.tex')
            visit(main_dir / q if (main_dir / q).exists() else p.parent / q, main_dir)
    for m in mains:
        visit(m, m.parent)
    return order, registry


def plain(text, registry=None):
    """LaTeX -> lowercase text for matching: \\res values filled in, 3\\times10^{-4} -> 3e-4, \\% -> %,
    greek -> words, other commands and braces dropped. Newlines are kept so offsets map to lines."""
    reg = registry or {}

    def res(m):
        v = reg.get(m[2])
        if v is None or not m[1]:
            return m[0] if v is None else v
        try:
            return '%g' % (float(v) * 100)
        except ValueError:
            return v
    t = re.sub(r'\\res(pct)?\{([^}]*)\}', res, text)
    t = re.sub(r'\\\\(?:\[[^\]]*\])?', ' ; ', t)  # table row ends separate values like sentence ends do
    t = REFS.sub(' ', t)
    t = re.sub(r'\\(num|SI|qty|numrange)\s*\[[^\]]*\]', r'\\\1', t)
    t = t.replace('\\%', '%').replace('\\percent', '%').replace('\\_', '_').replace('{,}', ',').replace('\u2212', '-')
    t = re.sub(r'(?<=\d)\\[,!:]\s?(?=\d)', '', t)  # 50\,000
    t = re.sub(r'\$|(?<!\\)\\[()\[\]]', ' ', t)
    t = re.sub(r'(\d+(?:\.\d+)?)\s*(?:\\times|\\cdot|\u00d7)\s*\{?\s*10\s*\}?\s*\^\s*\{?\s*([-+]?\d+)\s*\}?', r'\1e\2', t)
    t = re.sub(r'(?<![\w.])10\s*\^\s*\{?\s*([-+]?\d+)\s*\}?', r'1e\1', t)
    t = GREEK.sub(lambda m: ' ' + ('l' if m[1] == 'ell' else m[1]), t)
    t = re.sub(r'\\[a-zA-Z@]+\*?', ' ', t)
    return re.sub(r'[{}]', '', re.sub(r'\}\s*\{', ' ', t)).lower()  # \cmd{5}{1} is 5 and 1, not 51


def num_value(m):
    """NUM match -> (value, is_percent); 50k -> 50000."""
    return float(m[1].replace(',', '')) * {'k': 1e3, 'm': 1e6, 'b': 1e9}.get(m[2], 1), bool(m[3])


def norm_name(s):
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', str(s).strip())
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


@lru_cache(maxsize=None)
def canon_of(name):
    return next(((n, w) for n, w, code, _ in CANON if code.fullmatch(name)), (None, 0))


# ---------------------------------------------------------------- code side

def coerce(s):
    """'3e-4' -> 0.0003, 'true' -> True, 'null' -> None; other strings unchanged."""
    if not isinstance(s, str):
        return s
    low = s.strip().lower()
    if low in ('true', 'yes', 'on', 'false', 'no', 'off'):
        return low in ('true', 'yes', 'on')
    if low in ('null', 'none', '~', ''):
        return None
    for conv in (int, float):
        try:
            return conv(low)
        except ValueError:
            pass
    return s.strip()


def yaml_value(s):
    s = re.sub(r'^[&!]\S+\s*', '', s.strip())  # anchors and tags
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in '"\'' else coerce(s)


def yaml_uncomment(line):
    quote = None
    for i, c in enumerate(line):
        if quote:
            quote = None if c == quote else quote
        elif c in '"\'':
            quote = c
        elif c == '#' and (i == 0 or line[i - 1] in ' \t'):
            return line[:i]
    return line


YAML_KEY = re.compile(r'''^("[^"]*"|'[^']*'|[^\s'"#][^:]*?)\s*:(?:\s+(.*))?$''')


def parse_yaml(text):
    """Common config subset of YAML -> [(path, value, line)]: nested mappings, scalars, block and flow lists.
    shortcut: no aliases/merge keys, multi-line strings or multi-line flow lists; use JSON/TOML if a config needs them."""
    out, seqs, counters, stack, block = [], {}, {}, [(-1, (), False)], None
    for n, raw in enumerate(text.splitlines(), 1):
        line = yaml_uncomment(raw).rstrip()
        body = line.strip()
        if not body or body in ('---', '...') or body.startswith('%'):
            continue
        ind = len(line) - len(line.lstrip())
        if block is not None and ind > block:
            continue  # inside a | or > block scalar
        block = None
        if body == '-' or body.startswith('- '):
            while stack[-1][0] > ind or (stack[-1][0] == ind and stack[-1][2]):
                stack.pop()
            parent, item = stack[-1][1], body[1:].lstrip()
            if not YAML_KEY.match(item):
                if item:
                    seqs.setdefault(parent, (n, []))[1].append(yaml_value(item))
                continue
            counters[parent] = counters.get(parent, -1) + 1
            stack.append((ind, parent + (str(counters[parent]),), True))
            ind, body = ind + len(body) - len(item), item  # a mapping inside the list item
        m = YAML_KEY.match(body)
        if not m:
            continue
        while stack[-1][0] >= ind:
            stack.pop()
        path, val = stack[-1][1] + (m[1].strip('"\''),), (m[2] or '').strip()
        if not val:
            stack.append((ind, path, False))
        elif val[0] in '|>':
            block = ind
        elif val[0] in '[{':
            inner = val[1:-1]
            items = [v.strip() for v in inner.split(',') if v.strip()] if val[-1] in ']}' and not re.search(r'[\[{]', inner) else []
            if val[0] == '[':
                out.append((path, [yaml_value(v) for v in items], n))
            else:
                out += [(path + (k.strip().strip('"\''),), yaml_value(v), n) for k, _, v in (i.partition(':') for i in items)]
        else:
            out.append((path, yaml_value(val), n))
    return out + [(p, vals, n) for p, (n, vals) in seqs.items()]


def flatten(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten(v, path + (str(k),))
    elif isinstance(obj, list) and not any(isinstance(v, (dict, list)) for v in obj):
        yield path, obj
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from flatten(v, path + (str(i),))
    else:
        yield path, obj


def located(text, leaves):
    """Attach line numbers by finding each leaf's key in file order (json, tomllib and configparser keep it)."""
    pos = 0
    for path, v in leaves:
        keys = [k for k in path if not k.isdigit()]
        if keys:
            m = re.compile(r'(?:^|[\s{,.])["\']?%s["\']?\s*[:=]' % re.escape(keys[-1]), re.M).search(text, pos)
            pos = m.end() if m else pos
        yield path, v, text.count('\n', 0, pos) + 1


def ini_dict(text):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read_string(text)
    d = {'DEFAULT': dict(cp.defaults())} if cp.defaults() else {}
    d.update({s: {k: v for k, v in cp.items(s) if k not in cp.defaults()} for s in cp.sections()})
    return d


def clean_value(v):
    v = coerce(v)
    if isinstance(v, bool):
        return True if v else None  # a disabled feature needs no disclosure
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        return v if len(v) <= 40 and not re.search(r'[/\\]|\.\w{2,4}$', v) else None
    if isinstance(v, (list, tuple)):
        atoms = [coerce(x) for x in v]
        ok = 0 < len(atoms) <= 8 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in atoms)
        return tuple(atoms) if ok else None
    return None


def make_setting(parts, value, file, line, label=None):
    parts = [norm_name(p) for p in parts if not str(p).isdigit()]
    while len(parts) > 1 and parts[-1] in GENERIC_KEYS:
        parts.pop()  # optimizer: {name: adamw} is the optimizer setting
    parts = [p for p in parts if p]
    value = clean_value(value)
    if not parts or value is None or any(NOISE.fullmatch(p) for p in parts) or len(parts[-1]) < 2:
        return None
    name = parts[-1]
    canon, weight = canon_of(name)
    if isinstance(value, str) and canon not in STRING_CANON:
        return None
    if canon is None:
        weight = 8 if DATA_FILTER.fullmatch(name) else 3
    return {'name': name, 'canon': canon or name, 'weight': weight, 'value': value,
            'label': label or '.'.join(parts), 'file': file, 'line': line}


def opt_key(name):
    k = re.sub(r'8bit|paged|fused|[^a-z]', '', str(name).rsplit('.', 1)[-1].lower())
    return k if k in OPTIMIZERS else None


def is_scheduler(fn):
    return bool(re.fullmatch(r'\w*(?:LR|Plateau|WarmRestarts)|get_\w*schedule\w*', fn or ''))


def callee(func):
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''


def lit(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def py_settings(text, p):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    out = []

    def add(parts, value, line, label=None):
        out.append(make_setting(parts, value, p, line, label))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = callee(node.func)
            if fn == 'add_argument':
                flags = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                default = next((k.value for k in node.keywords if k.arg == 'default'), None)
                if flags and default is not None:
                    flag = next((f for f in flags if f.startswith('--')), flags[0])
                    add([flag.lstrip('-')], lit(default), node.lineno, flag)
                continue
            take_all = fn in ML_CALLS or is_scheduler(fn) or (opt_key(fn) and fn[:1].isupper())
            if opt_key(fn) and fn[:1].isupper():
                add(['optimizer'], fn, node.lineno, f'{fn}(...)')
            if is_scheduler(fn):
                add(['scheduler'], fn, node.lineno, f'{fn}(...)')
            if fn in POSITIONAL and len(node.args) > POSITIONAL[fn][0]:
                i, name = POSITIONAL[fn]
                add([name], lit(node.args[i]), node.lineno, f'{fn}({name})')
            for k in node.keywords:
                if k.arg and (take_all or canon_of(norm_name(k.arg))[0]):
                    add([k.arg], lit(k.value), k.value.lineno, f'{fn}({k.arg}=)')
        elif isinstance(node, ast.ClassDef) and (CONFIG_CLASS.search(node.name)
                                                 or any('dataclass' in ast.dump(d) for d in node.decorator_list)):
            for st in node.body:
                target = st.target if isinstance(st, ast.AnnAssign) else st.targets[0] if isinstance(st, ast.Assign) else None
                value = st.value if isinstance(st, (ast.AnnAssign, ast.Assign)) else None
                if isinstance(value, ast.Call) and callee(value.func) == 'field':
                    value = next((k.value for k in value.keywords if k.arg == 'default'), None)
                if isinstance(target, ast.Name) and value is not None:
                    add([target.id], lit(value), st.lineno, f'{node.name}.{target.id}')
    for st in tree.body:  # module constants such as LR = 3e-4
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            name = st.targets[0].id
            if name.isupper() and canon_of(norm_name(name))[0]:
                add([name], lit(st.value), st.lineno, name)
    return [s for s in out if s]


def collect(code_dir, notes):
    found = []
    for dirpath, dirnames, filenames in os.walk(code_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.'))
        for f in sorted(filenames):
            p = Path(dirpath) / f
            ext = p.suffix.lower()
            if f in SKIP_FILES or f.startswith('test_') or f.endswith('_test.py') or ext not in CONFIG_EXT | {'.py'}:
                continue
            if p.stat().st_size > (5 * MAX_BYTES if ext == '.py' else MAX_BYTES):
                continue
            text = p.read_text(encoding='utf-8', errors='replace')
            if ext == '.py':
                found += py_settings(text, p)
                continue
            if ext == '.toml' and tomllib is None:
                notes.add('TOML configs skipped: needs Python 3.11+ (tomllib)')
                continue
            try:
                if ext in ('.yaml', '.yml'):
                    leaves = parse_yaml(text)
                else:
                    obj = json.loads(text) if ext == '.json' else tomllib.loads(text) if ext == '.toml' else ini_dict(text)
                    leaves = list(located(text, flatten(obj))) if isinstance(obj, dict) else []
            except (ValueError, configparser.Error):
                notes.add(f'unparsable config skipped: {f}')
                continue
            found += [s for s in (make_setting(path, v, p, n) for path, v, n in leaves) if s]
    return found


# ---------------------------------------------------------------- paper side

def paper_pattern(key, setting):
    canon = next((rx for n, _, _, rx in CANON if n == key), None)
    if canon:
        return canon
    toks = [t for t in setting['name'].split('_') if t not in FILLER]
    if not toks or (len(toks) == 1 and len(toks[0]) < 4):
        return re.compile(r'(?<!\w)%s(?!\w)' % re.escape(setting['name']))
    parts = [ABBREV.get(t, re.escape(t[:-1] if len(t) > 4 and t.endswith('s') else t)) + r'\w*' for t in toks]
    return re.compile(r'(?<!\w)' + r'[\s_-]+'.join(parts))


def same(code, paper, pct):
    close = lambda a, b: math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return close(code, paper) or (pct and close(code, paper / 100))


def fmtv(v):
    if v is True:
        return 'true'
    if isinstance(v, tuple):
        return '(' + ', '.join(fmtv(x) for x in v) + ')'
    return '%g' % v if isinstance(v, (int, float)) else str(v)


def audit(code_dir, paper, root):
    notes = set()
    groups = defaultdict(list)
    for s in collect(code_dir, notes):
        groups[s['canon']].append(s)
    files, registry = paper_files(paper)
    docs = [(rel(p, root), plain(t, registry)) for p, t in files]
    pats = {k: paper_pattern(k, ss[0]) for k, ss in groups.items()}
    hits, vals = defaultdict(list), defaultdict(list)
    for di, (name, doc) in enumerate(docs):
        spans = sorted(((m.start(), m.end(), k) for k, rx in pats.items() for m in rx.finditer(doc) if m.end() > m.start()),
                       key=lambda s: (s[0], s[0] - s[1]))
        kept, end = [], -1
        for s in spans:  # overlapping mentions: the earlier, longer one wins ("warmup steps" is not "steps")
            if s[0] >= end:
                kept.append(s)
                end = s[1]
        cuts = [m.start() for m in BOUNDARY.finditer(doc)]
        starts = [s for s, _, _ in kept]
        for s, e, k in kept:
            hits[k].append((di, s, e))
        for m in NUM.finditer(doc):
            # each number belongs to the nearest mention in its sentence/table row (after the name preferred)
            seg, i, best = bisect.bisect(cuts, m.start()), bisect.bisect(starts, m.start()), None
            for s, e, k in kept[max(0, i - 2): i + 2]:
                if bisect.bisect(cuts, s) != seg or s <= m.start() < e:
                    continue
                if m.start() < s and re.search(r'[,(:=]', doc[m.end():s]):
                    continue  # "lr 3e-4, weight decay": the 3e-4 is not the weight decay's
                d = m.start() - e if m.start() >= e else (s - m.end()) * 1.5
                if 0 <= d <= 80 and (best is None or d < best[0]):
                    best = (d, k)
            if best:
                vals[best[1]].append(num_value(m) + (f'{name}:{doc.count(chr(10), 0, m.start()) + 1}',))

    def segment(di, pos):
        doc = docs[di][1]
        lo = max((m.end() for m in BOUNDARY.finditer(doc, 0, pos)), default=0)
        hi = BOUNDARY.search(doc, pos)
        return doc[lo:hi.start() if hi else len(doc)]

    def where(di, pos):
        return f'{docs[di][0]}:{docs[di][1].count(chr(10), 0, pos) + 1}'

    rows = []
    for key, ss in groups.items():
        mentioned, found = hits[key], vals[key]
        paper_opts = {next((o for o, rx in OPTIMIZERS.items() if re.fullmatch(rx, docs[di][1][s:e])), None)
                      for di, s, e in mentioned} - {None} if key == 'optimizer' else set()

        def disclosed(st):
            v = st['value']
            if v is True or key == 'mixed precision':
                return bool(mentioned)
            if isinstance(v, str):
                if key == 'optimizer' and opt_key(v):
                    return opt_key(v) in paper_opts
                rx = next((r for w, r in SCHED_WORDS if w in v.lower()), re.escape(v.lower()))
                return any(re.search(r'(?<!\w)' + rx, segment(di, s)) for di, s, _ in mentioned)
            return all(any(same(a, p, pct) for p, pct, _ in found) for a in (v if isinstance(v, tuple) else (v,)))
        ok = [st for st in ss if disclosed(st)]
        numeric = any(not isinstance(st['value'], (str, bool)) for st in ss)
        main = (ok or ss)[0]
        others = [s for s in ss if s['value'] != main['value'] and s not in ok]
        others = list({fmtv(s['value']): s for s in others}.values())[:2]
        if ok:
            status, detail = 'DISCLOSED', ''
        elif paper_opts or (numeric and found and key != 'mixed precision'):
            seen = sorted(paper_opts) if paper_opts else list(dict.fromkeys(fmtv(p * 100 if pct else p) + ('%' if pct else '') for p, pct, _ in found))
            status, detail = 'MISMATCH', f'paper: {", ".join(seen[:3])} ({found[0][2] if found else where(*mentioned[0][:2])})'
        elif mentioned:
            status, detail = 'NO-VALUE', f'named at {where(*mentioned[0][:2])}, value not given'
        else:
            status, detail = 'UNDISCLOSED', ''
        if others:
            detail += ('; ' if detail else '') + 'also ' + ', '.join(f'{fmtv(s["value"])} at {rel(s["file"], root)}:{s["line"]}' for s in others)
        rows.append((status, max(s['weight'] for s in ss), key, main, detail))
    order = ['MISMATCH', 'UNDISCLOSED', 'NO-VALUE', 'DISCLOSED']
    rows.sort(key=lambda r: (order.index(r[0]), -r[1], r[2]))
    return rows, notes, len(docs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('code_dir')
    ap.add_argument('paper', help='paper folder or main .tex')
    ap.add_argument('--limit', type=int, default=20, help='rows to print (0 = all); counts always cover everything')
    ap.add_argument('--root', help='project folder for .agentex/status (default: nearest with .agentex/, else cwd)')
    args = ap.parse_args(argv)
    root = find_root(args.root)
    if not Path(args.code_dir).is_dir() or not Path(args.paper).exists():
        print('usage: settings_audit.py <code_dir> <paper_dir_or_main.tex>  (one of them does not exist)')
        return 2
    rows, notes, n_docs = audit(args.code_dir, args.paper, root)
    counts = {s.lower(): sum(r[0] == s for r in rows) for s in ('MISMATCH', 'UNDISCLOSED', 'NO-VALUE', 'DISCLOSED')}
    shown = [r for r in rows if r[0] != 'DISCLOSED' or r[4]]  # disclosed, but the code also has another value
    lines = [(f'{rel(m["file"], root)}:{m["line"]}', f'{st} {m["label"]}={fmtv(m["value"])}' + (f'  · {d}' if d else ''))
             for st, _, _, m, d in shown]
    for w, msg in lines[:args.limit or None]:
        st, rest = msg.split(' ', 1)
        print(f'{st:11s} {rest.split("  · ")[0]}  {w}' + ('  · ' + rest.split('  · ', 1)[1] if '  · ' in rest else ''))
    if args.limit and len(lines) > args.limit:
        print(f'... {len(lines) - args.limit} more (--limit 0 shows all)')
    for n in sorted(notes):
        print(f'note: {n}')
    summary = (f'{len(rows)} settings in code: {counts["mismatch"]} mismatch, {counts["undisclosed"]} undisclosed, '
               f'{counts["no-value"]} no value, {counts["disclosed"]} disclosed')
    print(summary + f'  ({n_docs} paper files)')
    status = 'fail' if counts['mismatch'] else 'warn' if counts['undisclosed'] or counts['no-value'] else 'ok'
    write_status(root, 'settings', status, summary, {k.replace('-', '_'): v for k, v in counts.items()}, lines)
    return 1 if counts['mismatch'] or counts['undisclosed'] else 0


if __name__ == '__main__':
    sys.exit(main())
