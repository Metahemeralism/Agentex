"""Tests for figcheck.py. Fixtures (PDF, PNG, JPEG) are written with the stdlib; poppler and TeX runs are guarded.

Run: python3 -m unittest discover -s skills/latex-tables-figures/scripts -q
"""
import json
import random
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figcheck  # noqa: E402

LAYOUT = {'textwidth': 469.0, 'columnwidth': 229.5, 'textheight': 550.0, 'normalsize': 10.0, 'small': 9.0,
          'footnotesize': 8.0}  # article, twocolumn, 10pt (as tectonic measures it)


def make_pdf(content, w=460.8, h=345.6, compress=True):
    """One-page PDF with Helvetica (base-14, so not embedded) and the given content stream."""
    stream = zlib.compress(content) if compress else content
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.1f %.1f] /Contents 4 0 R '
            b'/Resources << /Font << /F1 5 0 R >> >> >>' % (w, h),
            b'<< /Length %d%s >>\nstream\n' % (len(stream), b' /Filter /FlateDecode' if compress else b'')
            + stream + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = b'%PDF-1.4\n', []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % i + obj + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offsets)
    return out + b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n' % (len(objs) + 1, xref) + b'%%EOF\n'


def make_png(w, h, dpi=None, software=None, noisy=False):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    rng = random.Random(0)
    row = lambda: bytes(rng.getrandbits(8) for _ in range(w * 3)) if noisy else bytes(w * 3)  # noqa: E731
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    if software:
        png += chunk(b'tEXt', b'Software\0' + software)
    if dpi:
        ppm = round(dpi / 0.0254)
        png += chunk(b'pHYs', struct.pack('>IIB', ppm, ppm, 1))
    return png + chunk(b'IDAT', zlib.compress(b''.join(b'\0' + row() for _ in range(h)))) + chunk(b'IEND', b'')


JPEG = (b'\xff\xd8' + b'\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x01\x2c\x01\x2c\x00\x00'   # 300 dpi
        + b'\xff\xc0\x00\x11\x08\x00\x64\x00\xc8\x03' + bytes(9) + b'\xff\xd9')         # 200 x 100 px
PDFFONTS = """name                                 type              encoding         emb sub uni object ID
------------------------------------ ----------------- ---------------- --- --- --- ---------
BMQQDV+DejaVuSans                    Type 3            Custom           yes yes no      15  0
Helvetica                            Type 1            Standard         no  no  no       5  0
IHAIZV+LMRoman6-Regular-Identity-H   CID Type 0C       Identity-H       yes yes yes      4  0
"""


class Parsers(unittest.TestCase):
    def test_dim(self):
        self.assertAlmostEqual(figcheck.dim('0.5\\linewidth', LAYOUT, 200), 100)
        self.assertEqual(figcheck.dim('\\columnwidth', LAYOUT, None), 229.5)
        self.assertAlmostEqual(figcheck.dim('.8\\textwidth', LAYOUT, None), 375.2)
        self.assertAlmostEqual(figcheck.dim('3.4in', {}, None), 245.718)
        self.assertAlmostEqual(figcheck.dim('8cm', {}, None), 227.62, places=2)
        self.assertIsNone(figcheck.dim('\\linewidth', {}, None))  # unmeasured layout
        self.assertIsNone(figcheck.dim('\\figwidth', LAYOUT, 200))
        self.assertIsNone(figcheck.dim('\\linewidth-2em', LAYOUT, 200))

    def test_linewidth_follows_environments(self):
        text = ('\\begin{figure*}\\begin{subfigure}[t]{0.48\\linewidth}X\\end{subfigure}\\end{figure*}'
                '\\begin{figure}Y\\begin{minipage}[b]{0.3\\textwidth}Z\\end{minipage}\\end{figure}'
                '\\begin{wrapfigure}[8]{r}{0.4\\columnwidth}W\\end{wrapfigure}V')
        width = lambda ch: figcheck.line_width(figcheck.context(text, text.index(ch)), LAYOUT)  # noqa: E731
        self.assertAlmostEqual(width('X'), 0.48 * 469)  # subfigure of a two-column-spanning float
        self.assertEqual(width('Y'), 229.5)
        self.assertAlmostEqual(width('Z'), 0.3 * 469)
        self.assertAlmostEqual(width('W'), 0.4 * 229.5)
        self.assertEqual(width('V'), 229.5)  # all closed again

    def test_keyvals(self):
        kv = figcheck.keyvals('width=0.5\\linewidth, alt={A plot, with [brackets]}, keepaspectratio')
        self.assertEqual(kv, {'width': '0.5\\linewidth', 'alt': 'A plot, with [brackets]', 'keepaspectratio': 'true'})

    def test_png_and_jpeg_headers(self):
        w, h, dpi, software, ratio = figcheck.png_info(make_png(64, 32, dpi=150, software=b'Matplotlib version3.9'))
        self.assertEqual((w, h, software), (64, 32, 'Matplotlib version3.9'))
        self.assertAlmostEqual(dpi, 150, delta=0.1)
        self.assertLess(ratio, 0.08)
        self.assertGreater(figcheck.png_info(make_png(64, 64, noisy=True))[4], 0.5)  # photo-like noise
        self.assertIsNone(figcheck.png_info(make_png(8, 8))[2])
        self.assertEqual(figcheck.jpeg_info(JPEG), (200, 100, 300))

    def test_pdffonts(self):
        rows = figcheck.parse_pdffonts(PDFFONTS)
        self.assertEqual(rows[0], ('BMQQDV+DejaVuSans', 'Type 3', True))
        self.assertEqual(rows[1], ('Helvetica', 'Type 1', False))
        self.assertEqual(rows[2][1], 'CID Type 0C')

    def test_text_sizes_follow_matrices(self):
        content = (b'q 2 0 0 2 10 10 cm BT /F1 5 Tf 0 0 Td (Hi \\(x\\)) Tj ET Q '
                   b'BT /F1 1 Tf 0 12 -12 0 50 50 Tm [(rot) -250 (ated)] TJ ET '
                   b'BT /F1 9.96 Tf (plain) Tj ET')
        self.assertEqual(figcheck.text_sizes(make_pdf(content)), [10.0, 12.0, 9.96])
        self.assertEqual(figcheck.text_sizes(make_pdf(content, compress=False)), [10.0, 12.0, 9.96])
        self.assertEqual(figcheck.text_sizes(make_pdf(b'0 0 m 10 10 l S')), [])  # outlines only

    def test_preamble_key_tracks_the_preamble_only(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / 'main.tex'
            main.write_text('\\documentclass{article}\n\\begin{document}\nA\n\\end{document}\n')
            k = figcheck.preamble_key(main)
            main.write_text('\\documentclass{article}\n\\begin{document}\nB changed\n\\end{document}\n')
            self.assertEqual(figcheck.preamble_key(main), k)
            main.write_text('\\documentclass[twocolumn]{article}\n\\begin{document}\nB\n\\end{document}\n')
            self.assertNotEqual(figcheck.preamble_key(main), k)


MAIN = r"""\documentclass[twocolumn]{article}
\usepackage{graphicx}
\graphicspath{{figs/}}
\newcommand{\fig}[1]{\includegraphics{#1}}
\begin{document}
\begin{figure}
  \includegraphics[width=\columnwidth]{plot}% matplotlib's default 6.4in figure
\end{figure}
\begin{figure*}
  \includegraphics[width=\linewidth, alt={A photo}]{photo.png}
\end{figure*}
\includegraphics[scale=0.5]{scan}
\includegraphics{gone}
\end{document}
"""


def project(d, layout=LAYOUT):
    root = Path(d)
    (root / 'figs').mkdir()
    (root / 'main.tex').write_text(MAIN)
    (root / 'figs' / 'plot.pdf').write_bytes(make_pdf(b'BT /F1 10 Tf (0.2) Tj ET BT /F1 12 Tf (Loss) Tj ET'))
    (root / 'figs' / 'photo.png').write_bytes(make_png(640, 480, dpi=100))
    (root / 'figs' / 'scan.jpg').write_bytes(JPEG)
    if layout:
        cache = figcheck.agentex_dir(root) / 'layout.json'
        cache.write_text(json.dumps({figcheck.preamble_key(root / 'main.tex'): layout}))
    return root / 'main.tex'


class Check(unittest.TestCase):
    def run_check(self, main, **kw):
        with mock.patch.object(figcheck, 'pdf_page_size', return_value=(460.8, 345.6)), \
                mock.patch.object(figcheck, 'pdf_fonts', return_value=[('DejaVuSans', 'Type 3', True)]):
            return figcheck.check(main, **kw)

    def test_report_and_status(self):
        with tempfile.TemporaryDirectory() as d:
            main = project(d)
            code, out = self.run_check(main, compile_=False)
            text = '\n'.join(out)
            self.assertEqual(code, 1, text)  # a missing figure fails
            self.assertIn('(twocolumn, cached)', out[0])
            plot = next(line for line in out if 'figs/plot.pdf' in line)
            self.assertRegex(plot, r'230pt\s+0\.50\s+5\.0pt')  # 10pt ticks print at 5pt in a column
            self.assertIn('plot at 3.18in wide', plot)
            self.assertIn('Type 3', plot)
            photo = next(line for line in out if 'photo.png' in line)
            self.assertIn('469pt', photo)  # figure* spans the text width
            self.assertIn('99 dpi', photo)
            self.assertIn('plot saved as PNG', photo)
            scan = next(line for line in out if 'scan.jpg' in line)
            self.assertRegex(scan, r'24pt\s+0\.50')  # 200px at 300 dpi, halved
            self.assertTrue(scan.endswith(' ok'), scan)  # 300 dpi shown at half size is 600 dpi effective
            self.assertIn('file not found', text)
            self.assertIn('alt text: 3/4', text)
            self.assertNotIn('#1', text)

            status = json.loads((Path(d) / '.agentex' / 'status' / 'figures.json').read_text())
            self.assertEqual(set(status), {'tool', 'status', 'summary', 'counts', 'items', 'updated'})
            self.assertEqual((status['tool'], status['status']), ('figures', 'fail'))
            self.assertLessEqual(len(status['summary']), 100)
            self.assertEqual(status['counts']['figures'], 4)
            self.assertEqual(status['counts']['no_alt'], 3)
            self.assertEqual(status['counts']['missing'], 1)
            self.assertTrue(all(set(i) == {'where', 'message'} for i in status['items']))
            self.assertIn('main.tex:7', [i['where'] for i in status['items']])
            self.assertTrue(status['updated'].endswith('+00:00'))
            self.assertEqual((Path(d) / '.agentex' / '.gitignore').read_text(), '*\n')

    def test_no_compile_without_cache_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_check(project(d, layout=None), compile_=False)
            self.assertIn('unmeasured', out[0])
            self.assertIn("can't resolve width=\\columnwidth (layout unmeasured)", '\n'.join(out))
            status = json.loads((Path(d) / '.agentex' / 'status' / 'figures.json').read_text())
            self.assertIn('layout unmeasured', status['summary'])

    @unittest.skipUnless(shutil.which('pdfinfo') and shutil.which('pdffonts'), 'needs poppler')
    def test_real_poppler_on_stdlib_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            main = project(d)
            code, out = figcheck.check(main, compile_=False)
            plot = next(line for line in out if 'figs/plot.pdf' in line)
            self.assertRegex(plot, r'0\.50\s+5\.0pt')
            self.assertIn('fonts not embedded (Helvetica)', plot)


@unittest.skipUnless(shutil.which('tectonic') or shutil.which('latexmk'), 'needs a TeX engine')
class Measure(unittest.TestCase):
    def test_measures_and_caches_layout(self):
        with tempfile.TemporaryDirectory() as d:
            main = project(d, layout=None)
            layout, note = figcheck.measure(main)
            self.assertTrue(note.startswith('measured'), note)
            self.assertEqual(layout['normalsize'], 10)
            self.assertAlmostEqual(layout['columnwidth'], (layout['textwidth'] - 10) / 2)  # \columnsep 10pt
            self.assertEqual(figcheck.measure(main, compile_=False), (layout, 'cached'))
            built = [p.name for p in Path(d).rglob('*') if p.suffix in ('.log', '.aux', '.xdv') or 'agx' in p.name]
            self.assertEqual(built, [])  # compiled in a scratch copy, never in the project


if __name__ == '__main__':
    unittest.main()
