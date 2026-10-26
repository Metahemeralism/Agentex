"""Run: python3 -m unittest discover skills/latex-pdf/scripts"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pdftool

PDFTK_DUMP = """---
FieldType: Text
FieldName: Name
FieldValue:
---
FieldType: Button
FieldName: Agree
FieldStateOption: Off
FieldStateOption: Yes
"""
QPDF_JSON = {'acroform': {'fields': [
    {'fullname': 'Name', 'istext': True, 'value': 'Ada', 'choices': [], 'pageposfrom1': 1},
    {'fullname': 'Size', 'ischoice': True, 'value': None, 'choices': ['S', 'M'], 'pageposfrom1': 2}]}}


def tiny_pdf(path, pages=1):
    """A valid, uncompressed US-letter PDF with `pages` blank pages (xdvipdfmx needs /Resources and /Contents)."""
    kids = ' '.join(f'{4 + i} 0 R' for i in range(pages))
    objs = ['<< /Type /Catalog /Pages 2 0 R >>', f'<< /Type /Pages /Kids [{kids}] /Count {pages} >>',
            '<< /Length 0 >>\nstream\n\nendstream']
    objs += ['<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> /Contents 3 0 R >>'] * pages
    out, offsets = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n{o}\nendobj\n'.encode()
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode()
    out += b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    out += f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    Path(path).write_bytes(out)


class PdftoolTest(unittest.TestCase):
    def test_pages(self):
        self.assertEqual(pdftool.parse_pages('1-3,5', 9), [1, 2, 3, 5])
        self.assertEqual(pdftool.parse_pages('7-', 9), [7, 8, 9])
        self.assertEqual(pdftool.parse_pages('even', 5), [2, 4])
        self.assertEqual(pdftool.parse_pages('last:2', 5), [4, 5])
        with self.assertRaisesRegex(ValueError, 'outside'):
            pdftool.parse_pages('4', 3)
        self.assertEqual(pdftool.ranges([1, 2, 3, 5, 7, 8]), '1-3,5,7-8')

    def test_page_count_fallback(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(pdftool, 'have', lambda t: False):
            tiny_pdf(Path(d) / 'a.pdf', 3)
            self.assertEqual(pdftool.page_count(Path(d) / 'a.pdf'), 3)

    def test_fields_and_values(self):
        fields = pdftool.parse_pdftk_fields(PDFTK_DUMP)
        self.assertEqual(fields[1], {'name': 'Agree', 'type': 'Button', 'options': ['Off', 'Yes']})
        self.assertEqual(pdftool.check_values(fields, {'Name': 'x', 'Agree': 'Yes'}), [])
        self.assertEqual(pdftool.check_values(fields, {'Nmae': 'x', 'Agree': 'True'}),
                         ['unknown field: Nmae', "Agree: 'True' is not one of ['Off', 'Yes']"])
        q = pdftool.parse_qpdf_fields(QPDF_JSON)
        self.assertEqual([(f['name'], f['type'], f['value'], f['page']) for f in q],
                         [('Name', 'Text', 'Ada', 1), ('Size', 'Choice', '', 2)])
        self.assertIn('<field name="A&amp;B"><value>x &lt; y</value></field>', pdftool.xfdf({'A&B': 'x < y'}))

    def test_overlay_checks(self):
        items = [{'page': 1, 'box': [0, 0, 100, 8], 'text': 'a', 'size': 10},
                 {'page': 1, 'box': [50, 0, 150, 20], 'text': 'b'},
                 {'page': 3, 'x': 1, 'y': 1, 'text': 'c'}, {'page': 1, 'text': 'd'}]
        self.assertEqual(pdftool.check_overlay(items, 2), [
            'item 1: box is 8pt tall, text is 10pt', 'item 2: box overlaps item 1', 'item 3: page 3 outside 1-2',
            'item 4: needs x and y, or box'])
        self.assertIn(r'\put(72,700)', pdftool.overlay_put({'x': 72, 'y': 700, 'text': '50% & up'}))
        self.assertIn(r'50\% \& up', pdftool.overlay_put({'x': 72, 'y': 700, 'text': '50% & up'}))

    def test_refuses_to_overwrite_input(self):
        with tempfile.TemporaryDirectory() as d:
            tiny_pdf(Path(d) / 'a.pdf')
            self.assertEqual(pdftool.main(['pages', f'{d}/a.pdf', '1', '-o', f'{d}/a.pdf']), 2)
            self.assertEqual(pdftool.main(['encrypt', f'{d}/a.pdf', '-o', f'{d}/b.pdf', '--password', '']), 1)

    @unittest.skipUnless(shutil.which('latexmk') or shutil.which('tectonic'), 'no TeX engine')
    def test_latex_fallback_overlay_and_merge(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tiny_pdf(d / 'a.pdf', 2)
            (d / 'spec.json').write_text('[{"page": 2, "x": 72, "y": 700, "text": "Ada"}]')
            self.assertEqual(pdftool.main(['overlay', str(d / 'a.pdf'), str(d / 'spec.json'), '-o', str(d / 'o.pdf')]), 0)
            real_have = pdftool.have
            with mock.patch.object(pdftool, 'have', lambda t: t in ('latexmk', 'tectonic') and real_have(t)):
                self.assertEqual(pdftool.main(['merge', str(d / 'm.pdf'), str(d / 'a.pdf'), str(d / 'o.pdf')]), 0)
                self.assertEqual(pdftool.page_count(d / 'm.pdf'), 4)  # stdlib count reads compressed object streams

    @unittest.skipUnless((shutil.which('latexmk') or shutil.which('tectonic')) and shutil.which('pdftotext'),
                         'needs a TeX engine and pdftotext')
    def test_overlay_lands_where_the_preview_said(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tiny_pdf(d / 'a.pdf')
            # a 200x30 px box at (100, 100) on a 100-dpi preview = 72x72 pt from the top-left corner
            (d / 'spec.json').write_text('{"dpi": 100, "items": [{"page": 1, "box": [100, 100, 300, 130], "text": "Ada"}]}')
            self.assertEqual(pdftool.main(['overlay', str(d / 'a.pdf'), str(d / 'spec.json'), '-o', str(d / 'o.pdf')]), 0)
            html = subprocess.run(['pdftotext', '-bbox', str(d / 'o.pdf'), '-'], capture_output=True, text=True).stdout
            m = re.search(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="([\d.]+)">Ada<', html)
            self.assertIsNotNone(m, html)
            x, top, bottom = map(float, m.groups())
            self.assertAlmostEqual(x, 74, delta=1.5)          # left edge + 2pt padding
            self.assertTrue(72 <= top and bottom <= 93.6, (top, bottom))  # inside the box (72..93.6 pt)


if __name__ == '__main__':
    unittest.main()
