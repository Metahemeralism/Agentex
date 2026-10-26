"""Run: python3 -m unittest discover skills/latex-documents/scripts"""
import json
import tempfile
import unittest
from pathlib import Path

from mail_merge import load_records, main, merge, parse, tex_escape

TEMPLATE = r"""\documentclass{article}\graphicspath{{../}}
\begin{document}
Dear {{name}}, ref {{id}}. {{{sig}}}
{{#phd}}Dr.~{{name}}{{/phd}}{{^phd}}Not a doctor.{{/phd}}
\begin{itemize}{{#items}}\item {{.}}{{/items}}\end{itemize}
{{#addr}}{{addr.city}}{{/addr}}
\end{document}
"""


class MailMergeTest(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(tex_escape('R&D 50% <$5> a_b #1 ~^\\'),
                         r'R\&D 50\% \textless{}\$5\textgreater{} a\_b \#1 \textasciitilde{}\textasciicircum{}\textbackslash{}')

    def test_merge(self):
        recs = [{'name': 'Ada & Co', 'id': '7', 'sig': r'\textbf{A}', 'phd': 'yes', 'items': ['x_1', 'y'],
                 'addr': {'city': 'London'}},
                {'name': 'Bob', 'id': '8', 'sig': '', 'phd': 'no', 'items': []}]
        files, errors = merge(TEMPLATE, recs, 'letter', '{{name}}-{{id}}')
        self.assertEqual(errors, [])
        (n1, t1), (n2, t2) = files
        self.assertEqual((n1, n2), ('Ada_Co-7.tex', 'Bob-8.tex'))
        self.assertIn(r'Dear Ada \& Co, ref 7. \textbf{A}', t1)
        self.assertIn(r'Dr.~Ada \& Co', t1)
        self.assertIn(r'\item x\_1\item y', t1)
        self.assertIn('London', t1)
        self.assertIn(r'\graphicspath{{../}}', t1)  # LaTeX double braces are left alone
        self.assertIn('Not a doctor.', t2)
        self.assertNotIn('Dr.', t2)

    def test_missing_and_duplicates(self):
        files, errors = merge('{{name}} {{zip}}', [{'name': 'A', 'zip': '1'}, {'name': 'B'}], 's')
        self.assertEqual(errors, ['record 2: no value for zip'])
        _, errors = merge('{{name}}', [{'name': 'A'}, {'name': 'A'}], 's', '{{name}}')
        self.assertIn('already used', errors[0])

    def test_bad_sections(self):
        with self.assertRaisesRegex(ValueError, 'unclosed'):
            parse('{{#a}}x')
        with self.assertRaisesRegex(ValueError, 'closes'):
            parse('{{#a}}x{{/b}}')

    def test_shipped_template_merges_with_its_example_data(self):
        tpl = (Path(__file__).resolve().parent.parent / 'templates' / 'mail-merge-letter.tex').read_text()
        header, row = [l.lstrip('% ') for l in tpl.splitlines() if l.startswith('%   name,') or l.startswith('%   John')]
        files, errors = merge(tpl, [dict(zip(header.split(','), row.split(',')))], 'letter')
        self.assertEqual(errors, [])
        self.assertIn('Senior Engineer', files[0][1])

    def test_cli_writes_nothing_on_error(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 't.tex').write_text('{{name}} {{zip}}')
            (d / 'data.csv').write_text('﻿name,zip\nA,1\nB,\n')
            self.assertEqual(load_records(d / 'data.csv')[1], {'name': 'B', 'zip': ''})
            self.assertEqual(main([str(d / 't.tex'), str(d / 'data.csv')]), 0)
            self.assertEqual(sorted(p.name for p in (d / 'merged').iterdir()), ['t-001.tex', 't-002.tex'])
            (d / 'data.json').write_text(json.dumps({'records': [{'name': 'C'}]}))
            self.assertEqual(main([str(d / 't.tex'), str(d / 'data.json'), '-o', str(d / 'bad')]), 1)
            self.assertFalse((d / 'bad').exists())


if __name__ == '__main__':
    unittest.main()
