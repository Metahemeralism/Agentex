#!/usr/bin/env python3
"""AgenTeX compile loop.

  --init (SessionStart): record when LaTeX sources were last touched, so later builds only happen
                         after real edits.
  (Stop)               : if .tex/.bib/.sty/.cls/.bst files changed since the last build, compile the
                         main document(s). On errors, or on undefined references/citations that were
                         not there before, block the stop and hand Claude a short log digest so it fixes
                         the build before the user sees it. Gives up after 3 attempts in a row.
Needs latexmk or tectonic on PATH (otherwise does nothing). Disable with AGENTEX_COMPILE_HOOK=0.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / 'skills' / 'latex-debug' / 'scripts'))
from texlog import digest  # noqa: E402

SRC = {'.tex', '.bib', '.sty', '.cls', '.bst'}
SKIP_DIRS = {'.git', '.agentex', 'arxiv_submission', 'build', 'out', 'node_modules', '__pycache__', 'venv', '.venv'}
MAX_DEPTH, MAX_BLOCKS, BUILD_TIMEOUT = 4, 3, 150
NEW_PROBLEM = re.compile(r'^(undefined reference|undefined citation|multiply-defined label) \(\d+\): (.*)$')


def sources(root):
    for d, dirs, files in os.walk(root):
        rel_depth = len(Path(d).relative_to(root).parts)
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(('.', '_minted')) and rel_depth < MAX_DEPTH]
        for f in files:
            if Path(f).suffix in SRC:
                yield Path(d) / f


def main_files(files):
    out = []
    for p in files:
        if p.suffix != '.tex':
            continue
        head = p.read_text(encoding='utf-8', errors='replace')[:20000]
        if re.search(r'^\s*\\documentclass', head, re.M) and '\\begin{document}' in head \
                and not re.search(r'\\documentclass\s*(\[[^\]]*\])?\s*\{standalone\}', head):
            out.append(p)
    return sorted(out)


def state_path(root):
    return root / '.agentex' / 'build-state.json'


def load_state(root):
    try:
        return json.loads(state_path(root).read_text())
    except (OSError, ValueError):
        return {}


def save_state(root, state):
    d = root / '.agentex'
    d.mkdir(exist_ok=True)
    if not (d / '.gitignore').exists():
        (d / '.gitignore').write_text('*\n')
    state_path(root).write_text(json.dumps(state, indent=1))


def build(main):
    """Compile; return the log text, or None if no engine / timeout."""
    has_rc = any(p.exists() for p in (main.parent / 'latexmkrc', main.parent / '.latexmkrc', Path.home() / '.latexmkrc'))
    if shutil.which('latexmk'):
        # A latexmkrc chooses the engine (e.g. lualatex); only force pdflatex when there is none.
        cmd = ['latexmk', *([] if has_rc else ['-pdf']), '-interaction=nonstopmode', '-halt-on-error', '-file-line-error', main.name]
    elif shutil.which('tectonic'):
        cmd = ['tectonic', '--keep-logs', main.name]
    else:
        return None
    try:
        subprocess.run(cmd, cwd=main.parent, capture_output=True, timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    logs = [p for p in (main.with_suffix('.log'), *(main.parent / d / (main.stem + '.log') for d in ('build', 'out', '_build')))
            if p.exists()]
    return max(logs, key=lambda p: p.stat().st_mtime).read_text(encoding='utf-8', errors='replace') if logs else None


def problems_of(report):
    return {f'{m[1]}: {item.strip()}' for line in report.splitlines() if (m := NEW_PROBLEM.match(line))
            for item in m[2].split(', ') if not item.startswith('...')}


def run(root, init=False, stop_hook_active=False, build_fn=build):
    """-> (exit_code, message). Separated from main() for tests."""
    files = list(sources(root))
    mains = main_files(files)
    if not mains:
        return 0, ''
    newest = max(p.stat().st_mtime for p in files)
    state = load_state(root)
    if init:
        state['stamp'] = newest
        save_state(root, state)
        return 0, ''
    if newest <= state.get('stamp', 0):
        return 0, ''  # no LaTeX source changed since the last build
    reports, blocking, problems = [], False, {}
    for m in mains[:3]:
        log = build_fn(m)
        if log is None:
            continue
        report, has_errors = digest(log)
        rel = str(m.relative_to(root))
        problems[rel] = sorted(problems_of(report))
        new = set(problems[rel]) - set(state.get('problems', {}).get(rel, []))
        if has_errors or (new and rel in state.get('problems', {})):  # first build only sets the baseline
            blocking = True
            reports.append(f'== {rel}\n{report}' + (f'\nNEW since last build: {"; ".join(sorted(new))}' if new else ''))
    state.update(stamp=max(p.stat().st_mtime for p in sources(root)), problems={**state.get('problems', {}), **problems})
    if not blocking:
        state['blocks'] = 0
        save_state(root, state)
        return 0, ''
    state['blocks'] = state.get('blocks', 0) + 1 if stop_hook_active else 1
    save_state(root, state)
    if state['blocks'] > MAX_BLOCKS:
        return 0, json.dumps({'systemMessage': f'AgenTeX: the LaTeX build is still failing after {MAX_BLOCKS} fix attempts; '
                                               'see the .log or run latex-debug/scripts/texlog.py.'})
    return 2, ('AgenTeX compile check: your edits left the LaTeX build broken. Fix these before finishing '
               '(start with the first error; do not delete content to silence errors):\n' + '\n'.join(reports))


def main():
    if os.environ.get('AGENTEX_COMPILE_HOOK') == '0':
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    root = Path(data.get('cwd') or os.getcwd())
    try:
        code, msg = run(root, init='--init' in sys.argv, stop_hook_active=bool(data.get('stop_hook_active')))
    except Exception as e:  # never let a hook bug block the session
        print(f'AgenTeX compile loop skipped: {e}', file=sys.stderr)
        return 0
    if msg:
        print(msg, file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == '__main__':
    sys.exit(main())
