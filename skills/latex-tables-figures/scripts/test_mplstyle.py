"""Tests for mplstyle.py. Uses a cached layout, so no TeX; matplotlib (if installed) loads the result in a subprocess.

Run: python3 -m unittest discover -s skills/latex-tables-figures/scripts -q
"""
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figcheck  # noqa: E402
import mplstyle  # noqa: E402

LAYOUT = {'textwidth': 469.0, 'columnwidth': 229.5, 'textheight': 550.0, 'normalsize': 10.0, 'small': 9.0,
          'footnotesize': 8.0}


def paper(d, cls='[twocolumn]{article}'):
    main = Path(d) / 'main.tex'
    main.write_text(f'\\documentclass{cls}\n\\begin{{document}}\nx\n\\end{{document}}\n')
    (figcheck.agentex_dir(d) / 'layout.json').write_text(json.dumps({figcheck.preamble_key(main): LAYOUT}))
    return main


def run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mplstyle.main([str(a) for a in argv])
    return code, buf.getvalue()


class MplStyle(unittest.TestCase):
    def test_column_style(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'paper.mplstyle'
            code, said = run(paper(d), '-o', out)
            self.assertEqual(code, 0, said)
            style = out.read_text()
            self.assertIn('figure.figsize: 3.18, 1.97', style)  # 229.5pt / 72.27
            for line in ('font.size: 9', 'xtick.labelsize: 8', 'legend.fontsize: 8', 'pdf.fonttype: 42',
                         'ps.fonttype: 42', 'savefig.bbox: tight', 'legend.frameon: False', 'mathtext.fontset: cm'):
                self.assertIn(line, style)
            self.assertIn("cycler('color', ['0072B2'", style)
            body = [ln for ln in style.splitlines() if not ln.startswith('#')]
            self.assertFalse(any('#' in ln for ln in body), 'a # in a value starts a comment in .mplstyle files')
            self.assertIn('plt.style.use', said)

    def test_text_width_and_times(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'wide.mplstyle'
            self.assertEqual(run(paper(d, '[conference]{IEEEtran}'), '-o', out, '--text')[0], 0)
            style = out.read_text()
            self.assertIn('figure.figsize: 6.49, 2.27', style)
            self.assertIn('mathtext.fontset: stix', style)

    def test_no_layout(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(mplstyle, 'measure', return_value=(None, 'unmeasured: no latexmk/tectonic')):
            code, said = run(paper(d), '-o', Path(d) / 'x.mplstyle')
            self.assertEqual(code, 2)
            self.assertIn('no latexmk/tectonic', said)
            self.assertFalse((Path(d) / 'x.mplstyle').exists())

    @unittest.skipUnless(importlib.util.find_spec('matplotlib'), 'needs matplotlib')
    def test_matplotlib_accepts_it(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'paper.mplstyle'
            run(paper(d), '-o', out)
            probe = ('import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt; '
                     f'plt.style.use({str(out)!r}); r = plt.rcParams; '
                     'print(list(r["figure.figsize"]), r["pdf.fonttype"], r["axes.prop_cycle"].by_key()["color"][0])')
            got = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, timeout=120)
            self.assertEqual(got.stdout.split(), ['[3.18,', '1.97]', '42', '#0072B2'], got.stderr[-500:])


if __name__ == '__main__':
    unittest.main()
