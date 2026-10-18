"""Run: python3 -m unittest discover hooks"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cite_guard  # noqa: E402
import compile_loop  # noqa: E402
from cite_verify import fingerprint, parse_bib, save_cache  # noqa: E402  (path set by cite_guard)

BIB = '@article{good, title={Good Paper}, author={A, B}, year={2020}}\n@article{bad, title={Ghost}, author={C, D}, year={2021}}\n'
MAIN = '\\documentclass{article}\n\\begin{document}\nHello.\n\\end{document}\n'


class CiteGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'refs.bib').write_text(BIB)
        self.tex = self.root / 'main.tex'
        self.tex.write_text('\\cite{good}\n')
        es = {e['key']: e for e in parse_bib(BIB)}
        fp = {k: fingerprint(e) for k, e in es.items()}
        save_cache(self.root, {'version': 1, 'bibs': ['refs.bib'],
                               'entries': {fp['bad']: {'status': 'not-found', 'message': 'no match'}},
                               'keys': {'good': {'fp': fp['good'], 'status': 'verified'},
                                        'bad': {'fp': fp['bad'], 'status': 'not-found'}}})

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, old, new, path=None):
        return cite_guard.check({'tool_name': 'Edit', 'tool_input': {
            'file_path': str(path or self.tex), 'old_string': old, 'new_string': new}})

    def test_guard(self):
        self.assertIsNone(self.edit('x', 'see \\citep[p.~2]{good}'))              # verified
        self.assertIsNone(self.edit('\\cite{bad}', 'see \\cite{bad} again'))      # not newly added
        self.assertIsNone(self.edit('x', '\\cite{bad}', self.root / 'notes.md'))  # not a .tex file
        self.assertIn('bad: not-found (no match)', self.edit('x', '\\cite{good,bad}'))
        self.assertIn('nokey: no .bib entry', self.edit('x', '\\cite{nokey}'))
        self.assertIsNone(self.edit('x', '% \\cite{bad} commented out'))
        (self.root / 'refs.bib').write_text(BIB.replace('Good Paper', 'Better Paper'))
        self.assertIn('entry changed', self.edit('x', '\\cite{good}'))
        msg = cite_guard.check({'tool_name': 'Write', 'tool_input': {'file_path': str(self.tex),
                                                                       'content': '\\cite{good} \\cite{bad}'}})
        self.assertIn('bad', msg)


class CompileLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.main = self.root / 'main.tex'
        self.main.write_text(MAIN)
        self.builds = 0
        self.log = 'clean'

    def tearDown(self):
        self.tmp.cleanup()

    def fake_build(self, main):
        self.builds += 1
        return self.log

    def touch(self):
        t = time.time() + 10 + self.builds
        os.utime(self.main, (t, t))

    def stop(self, active=False):
        return compile_loop.run(self.root, stop_hook_active=active, build_fn=self.fake_build)

    def test_loop(self):
        compile_loop.run(self.root, init=True)
        self.assertEqual(self.stop(), (0, ''))
        self.assertEqual(self.builds, 0)  # nothing changed: no build

        self.touch()
        self.log = "LaTeX Warning: Reference `fig:old' on page 1 undefined on input line 3."
        self.assertEqual(self.stop()[0], 0)  # first build sets the baseline, pre-existing problem tolerated

        self.touch()
        self.log += "\nLaTeX Warning: Citation `new2024' on page 1 undefined on input line 4."
        code, msg = self.stop()
        self.assertEqual(code, 2)
        self.assertIn('NEW since last build: undefined citation: new2024', msg)

        self.log = '! Undefined control sequence.\nl.3 \\foo'
        for attempt in range(1, 4):
            self.touch()
            self.assertEqual(self.stop(active=attempt > 1)[0], 2)
        self.touch()
        code, msg = self.stop(active=True)  # 4th consecutive failure: let the user take over
        self.assertEqual(code, 0)
        self.assertIn('still failing', json.loads(msg)['systemMessage'])

    def test_no_latex_project(self):
        self.main.unlink()
        self.assertEqual(compile_loop.run(self.root, build_fn=self.fake_build), (0, ''))
        self.assertFalse((self.root / '.agentex').exists())  # never litters non-LaTeX repos


if __name__ == '__main__':
    unittest.main()
