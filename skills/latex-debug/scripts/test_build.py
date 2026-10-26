"""Run: python3 -m unittest discover skills/latex-debug/scripts"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build


class EngineTest(unittest.TestCase):
    def test_engine_for(self):
        self.assertEqual(build.engine_for('\\documentclass{article}\n\\usepackage{amsmath}'), 'pdflatex')
        self.assertEqual(build.engine_for('\\usepackage[no-math]{fontspec}'), 'xelatex')
        self.assertEqual(build.engine_for('\\usepackage{amsmath, unicode-math}'), 'xelatex')
        self.assertEqual(build.engine_for('\\usepackage{luacode}'), 'lualatex')
        self.assertEqual(build.engine_for('% !TEX program = lualatex\n\\usepackage{fontspec}'), 'lualatex')
        self.assertEqual(build.engine_for('% \\usepackage{fontspec}\n'), 'pdflatex')  # commented out

    def test_compile_cmd(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / 'cv.tex'
            main.write_text('\\documentclass{article}\\usepackage{fontspec}\\begin{document}x\\end{document}')
            which = lambda tool: '/bin/' + tool if tool == 'latexmk' else None
            with mock.patch('shutil.which', which), mock.patch.object(build, 'has_latexmkrc', lambda _: True):
                self.assertEqual(build.compile_cmd(main)[:2], ['latexmk', '-xelatex'])  # source beats latexmkrc
                main.write_text('\\documentclass{article}\\begin{document}x\\end{document}')
                self.assertNotIn('-pdf', build.compile_cmd(main))  # latexmkrc chooses
                pdfa = build.compile_cmd(main, pdfa=True)
                self.assertIn('-jobname=cv-pdfa', pdfa)
                self.assertTrue(any(a.startswith('-usepretex=\\DocumentMetadata') for a in pdfa))
            with mock.patch('shutil.which', lambda tool: '/bin/tectonic' if tool == 'tectonic' else None):
                self.assertEqual(build.compile_cmd(main)[0], 'tectonic')
                self.assertIsNone(build.compile_cmd(main, pdfa=True))
            with mock.patch('shutil.which', lambda tool: None):
                self.assertIsNone(build.compile_cmd(main))

    def test_wrapper_follows_input(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'cv.tex').write_text('\\documentclass{article}\\usepackage{fontspec}\\begin{document}x\\end{document}')
            key = Path(d) / 'cv-key.tex'
            key.write_text('\\AtBeginDocument{\\printanswers}\\input{cv}\n')
            self.assertEqual(build.engine_for(build.source_text(key)), 'xelatex')

    def test_page_range(self):
        self.assertEqual(build.page_range('1', 5), (1, 1))
        self.assertEqual(build.page_range('2-9', 5), (2, 5))
        self.assertEqual(build.page_range('all', 3), (1, 3))

    def test_clean(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / 'a.tex'
            main.write_text('x')
            for ext in ('.aux', '.log', '.pdf'):
                (Path(d) / ('a' + ext)).write_text('x')
            with mock.patch('shutil.which', lambda tool: None):
                self.assertEqual(sorted(build.clean(main)), ['a.aux', 'a.log'])
            self.assertTrue((Path(d) / 'a.pdf').exists())


if __name__ == '__main__':
    unittest.main()
