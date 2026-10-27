"""Run: python3 -m unittest discover -s skills/latex-submit/scripts"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preflight  # noqa: E402
from cite_verify import fingerprint, parse_bib, save_cache  # noqa: E402  (path set by preflight)

BIB = ('@inproceedings{good, title={A Real Paper}, author={Ann Smith}, year={2020}, booktitle={X}}\n'
       '@article{ghost, title={A Made Up Paper}, author={Bo Jones}, year={2021}, journal={Y}}\n')
VENUE = {'id': 'test', 'name': 'Test', 'checked': date.today().isoformat(), 'sources': ['https://example.org'],
         'verified': True, 'double_blind': False, 'pages': {'submission': None, 'uncounted': []}, 'required': []}


def tiny_pdf(pages):
    """A valid PDF (unembedded Helvetica) with one text line per entry of each page."""
    objs = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for lines in pages:
        stream = 'BT /F1 12 Tf 14 TL 72 720 Td ' + ' T* '.join(f'({l}) Tj' for l in lines) + ' ET'
        objs.append(f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream')
        objs.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> '
                    f'/Contents {len(objs)} 0 R >>')
        kids.append(len(objs))
    objs[1] = f'<< /Type /Pages /Kids [{" ".join(f"{k} 0 R" for k in kids)}] /Count {len(kids)} >>'
    out, offsets = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n{o}\nendobj\n'.encode()
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode() + b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    return out + f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()


def page(*lines):
    return '\n'.join(lines) + '\n'


class Project:
    """A throwaway paper folder with a cite cache and a fake PDF newer than the sources."""

    def __init__(self, tex, files=None, cache=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / '.git').mkdir()  # stop upward searches here
        self.main = self.root / 'main.tex'
        self.main.write_text(tex)
        (self.root / 'refs.bib').write_text(BIB)
        for name, text in (files or {}).items():
            (self.root / name).write_text(text)
        es = {e['key']: e for e in parse_bib(BIB)}
        fp = {k: fingerprint(e) for k, e in es.items()}
        statuses = cache or {'good': 'verified', 'ghost': 'not-found'}
        save_cache(self.root, {'version': 1, 'bibs': ['refs.bib'],
                               'entries': {fp[k]: {'status': s, 'message': 'no match'} for k, s in statuses.items()},
                               'keys': {k: {'fp': fp[k], 'status': s} for k, s in statuses.items()}})
        pdf = self.root / 'main.pdf'
        pdf.write_bytes(b'%PDF-1.4 fake')
        later = time.time() + 5
        os.utime(pdf, (later, later))

    def run(self, venue, mode='submission', pages=None, meta=None, type3=(), **kw):
        with mock.patch.object(preflight, 'pdf_pages', return_value=pages or [page('Intro', 'text'), page('References')]), \
                mock.patch.object(preflight, 'pdf_meta', return_value=meta or {'Fonts': '3, all embedded'}), \
                mock.patch.object(preflight, 'type3_fonts', return_value=list(type3)):
            res, _ = preflight.run(self.main, venue, mode, **kw)
        return res

    def close(self):
        self.tmp.cleanup()


def by_level(res, level):
    return ' | '.join(r.msg for r in res if r.level == level)


class BodyPagesTest(unittest.TestCase):
    def test_counts_pages_before_references(self):
        hdr = 'Under review as a conference paper at ICLR 2026'
        pages = [page(hdr, f'body {i}', str(i + 1)) for i in range(9)] + [page(hdr, 'REFERENCES', 'A. Smith', '10')]
        self.assertEqual(preflight.body_pages(pages), (9, 'REFERENCES'))  # heading at the top of p10: 9 pages
        pages[9] = page(hdr, 'spill-over text', '7 References', '10')
        self.assertEqual(preflight.body_pages(pages), (10, '7 References'))  # body text precedes it on p10
        pages[9] = page(hdr, 'Acknowledgments', 'thanks', 'References', '10')
        self.assertEqual(preflight.body_pages(pages, ['Acknowledgments'])[0], 9)  # venue does not count acks
        self.assertIsNone(preflight.body_pages([page('no heading here')]))

    def test_check_pages(self):
        v = dict(VENUE, pages={'submission': 2, 'camera-ready': 3, 'uncounted': []})
        three = [page('a'), page('b'), page('c', 'References')]
        self.assertEqual(preflight.check_pages(three, v, 'submission')[0].level, 'FAIL')
        self.assertEqual(preflight.check_pages(three, v, 'camera-ready')[0].level, 'PASS')
        self.assertEqual(preflight.check_pages(three, v, 'submission', limit=4)[0].level, 'PASS')
        self.assertEqual(preflight.check_pages([page('a')] * 3, v, 'submission')[0].level, 'FAIL')  # no heading, 3 > 2


@unittest.skipUnless(shutil.which('pdftotext') and shutil.which('pdffonts'), 'needs poppler')
class PopplerTest(unittest.TestCase):
    def test_real_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / 'p.pdf'
            pdf.write_bytes(tiny_pdf([['Introduction', 'We study things.'], ['Results'], ['References', 'A. Smith 2020']]))
            pages = preflight.pdf_pages(pdf)
            self.assertEqual(len(pages), 3)
            self.assertEqual(preflight.body_pages(pages), (2, 'References'))
            res = preflight.check_fonts(preflight.pdf_meta(pdf), preflight.type3_fonts(pdf))
            self.assertIn('Helvetica', by_level(res, 'FAIL'))  # base-14 font, not embedded


class NeuripsSubmissionTest(unittest.TestCase):
    TEX = ('\\documentclass{article}\n\\usepackage[final]{neurips_2026}\n\\author{Alice Smith\\thanks{Funded by X.}}\n'
           '\\begin{document}\nAs in our previous work \\cite{good}, see github.com/alice/repo. TODO: rerun\n'
           '\\cite{ghost} \\ref{sec:nowhere}\n\\begin{verbatim}\n\\usepackage{neurips_2026} \\guide{x}\n\\end{verbatim}\n'
           '\\bibliography{refs}\n\\end{document}\n')

    def setUp(self):
        self.p = Project(self.TEX, {'neurips_2026.sty': '% tweaked margins\n'})
        self.venue = preflight.load_venue('neurips-2026')

    def tearDown(self):
        self.p.close()

    def test_failures(self):
        pages = [page(f'body {i}') for i in range(10)] + [page('more body', 'Acknowledgments', 'References')]
        res = self.p.run(self.venue, pages=pages, meta={'Author': 'Alice Smith', 'Fonts': '9; NOT embedded: Arial'},
                         type3=['DejaVuSans'])
        fails, warns = by_level(res, 'FAIL'), by_level(res, 'WARN')
        for want in ('main body is 11 pages', 'fonts not embedded: Arial',
                     'differs from the official file', 'camera-ready/preprint mode', 'PDF metadata Author',
                     'acknowledgements are visible', 'NeurIPS Paper Checklist: missing', 'citation ghost: not-found',
                     'undefined reference: sec:nowhere', 'leftover placeholder TODO'):
            self.assertIn(want, fails)
        for want in ('Type 3', '\\thanks', 'github.com/alice', 'our previous'):
            self.assertIn(want, warns)
        self.assertNotIn('\\guide', fails)  # inside verbatim
        self.assertIn('LLM-use disclosure not required', by_level(res, 'PASS'))

    def test_main_prints_and_writes_status(self):
        out = io.StringIO()
        with mock.patch.object(preflight, 'pdf_pages', return_value=[page('x', 'References')]), \
                mock.patch.object(preflight, 'pdf_meta', return_value={}), \
                mock.patch.object(preflight, 'type3_fonts', return_value=[]), redirect_stdout(out):
            code = preflight.main([str(self.p.main), '--venue', 'neurips-2026'])
        self.assertEqual(code, 1)
        text = out.getvalue()
        self.assertRegex(text, r'(?m)^ANONYMITY$')
        self.assertIn('fix: \\usepackage{neurips_2026}', text)
        st = json.loads((self.p.root / '.agentex' / 'status' / 'preflight.json').read_text())
        self.assertEqual(set(st), {'tool', 'status', 'summary', 'counts', 'items', 'updated'})
        self.assertEqual((st['tool'], st['status']), ('preflight', 'fail'))
        self.assertLessEqual(len(st['summary']), 100)
        self.assertLessEqual(len(st['items']), 20)
        self.assertTrue(all(set(i) == {'where', 'message'} for i in st['items']))
        self.assertRegex(st['updated'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')


class CleanAndBuildTest(unittest.TestCase):
    TEX = ('\\documentclass{article}\n\\author{Ann Smith}\n\\begin{document}\n\\section{Intro}\\label{s}\n'
           'See \\ref{s} and \\cite{good}.\n\\bibliography{refs}\n\\end{document}\n')

    def test_clean_paper_passes(self):
        p = Project(self.TEX, cache={'good': 'verified'})
        try:
            out = io.StringIO()
            with mock.patch.object(preflight, 'pdf_pages', return_value=[page('Intro'), page('References')]), \
                    mock.patch.object(preflight, 'pdf_meta', return_value={'Fonts': '3, all embedded'}), \
                    mock.patch.object(preflight, 'type3_fonts', return_value=[]), redirect_stdout(out):
                code = preflight.main([str(p.main), '--venue', 'arxiv'])
            self.assertEqual(code, 0, out.getvalue())
            self.assertEqual(json.loads((p.root / '.agentex' / 'status' / 'preflight.json').read_text())['status'], 'ok')
        finally:
            p.close()

    def test_builds_only_without_pdf(self):
        p = Project(self.TEX, cache={'good': 'verified'})
        try:
            (p.root / 'main.pdf').unlink()
            done = mock.Mock(stdout='FAILED main.tex\n! Undefined control sequence.\n', returncode=1)
            with mock.patch.object(preflight.subprocess, 'run', return_value=done) as run:
                res = p.run(VENUE)
            self.assertIn('build.py', ' '.join(run.call_args[0][0]))
            self.assertIn('no PDF: the build failed', by_level(res, 'FAIL'))
            with mock.patch.object(preflight.subprocess, 'run') as run:
                res = p.run(VENUE, build=False)
            run.assert_not_called()
        finally:
            p.close()


class VenueRulesTest(unittest.TestCase):
    def test_acm_camera_ready(self):
        tex = ('\\documentclass[manuscript,anonymous]{acmart}\n\\usepackage{tikz}\n\\usepackage{booktabs,amsmath}\n'
               '\\setcopyright{none}\n\\author{Ann Smith}\n\\begin{document}\n\\begin{figure}\\includegraphics{fig.pdf}'
               '\\end{figure}\n\\begin{figure}\\Description{ok}\\end{figure}\n\\end{document}\n')
        p = Project(tex, {'fig.pdf': 'x'})
        try:
            res = p.run(preflight.load_venue('acm-sigconf'), 'camera-ready')
            fails, warns = by_level(res, 'FAIL'), by_level(res, 'WARN')
            for want in ('still in anonymous review mode', '\\setcopyright from the ACM rights form: missing',
                         '\\acmDOI: missing', 'manuscript class option present', 'figure without \\Description',
                         'package tikz is not on the TAPS'):
                self.assertIn(want, fails)
            self.assertIn('package booktabs is already loaded by acmart', warns)
            self.assertNotIn('amsmath', fails + warns)
            self.assertEqual(sum('Description' in r.msg for r in res if r.level == 'FAIL'), 1)
        finally:
            p.close()

    def test_ieee_pdf_rules(self):
        p = Project('\\documentclass[conference]{IEEEtran}\n\\usepackage{hyperref}\n\\author{A}\n\\begin{document}\n\\end{document}\n')
        try:
            res = p.run(preflight.load_venue('ieee-conference'), 'camera-ready', meta={'PDF version': '2.0'})
            self.assertIn('PDF version 2.0', by_level(res, 'FAIL'))
            self.assertIn('hyperref adds links', by_level(res, 'WARN'))
        finally:
            p.close()

    def test_llm_disclosure(self):
        tex = ('\\documentclass{article}\n\\usepackage{iclr2026_conference}\n\\begin{document}\nText.\n%s\n\\end{document}\n')
        iclr, arr = preflight.load_venue('iclr-2026'), preflight.load_venue('arr-2026')
        p = Project(tex % '')
        try:
            self.assertIn('no LLM-use disclosure found', by_level(p.run(iclr), 'WARN'))
            (p.root / '.agentex' / 'activity.jsonl').write_text(json.dumps({'file': 'main.tex', 'added_lines': 30}) + '\n')
            self.assertIn('agent logged 1 edits (+30 lines)', by_level(p.run(iclr), 'FAIL'))
            self.assertIn('Responsible NLP Checklist', by_level(p.run(arr), 'WARN'))  # a form at submission time
            self.assertIn('Limitations section: missing', by_level(p.run(arr), 'FAIL'))
            p.main.write_text(tex % '\\section*{LLM Usage}\nWe used an LLM to polish the text.')
            self.assertIn('LLM-use disclosure present', by_level(p.run(iclr), 'PASS'))
            p.main.write_text(tex % '\\section*{Acknowledgments}\nClaude (Anthropic) drafted Section 2.\n\\section{Appendix}')
            self.assertIn('LLM-use disclosure present', by_level(p.run(iclr), 'PASS'))
            p.main.write_text(tex % 'We fine-tune large language models.\n\\section*{Acknowledgments}\nWe thank Bo.')
            self.assertIn('agent logged', by_level(p.run(iclr), 'FAIL'))  # LLMs as a topic is not a disclosure
        finally:
            p.close()

    def test_venue_files(self):
        allowed = {'id', 'name', 'checked', 'sources', 'verified', 'double_blind', 'pages', 'style', 'named_if', 'switch',
                   'no_acks_in_submission', 'required', 'forbidden', 'llm_disclosure', 'figure_description', 'taps',
                   'pdf_version', 'no_links', 'notes', 'unverified'}
        files = sorted(preflight.VENUES.glob('*.json'))
        self.assertGreaterEqual(len(files), 9)
        for f in files:
            v = json.loads(f.read_text())
            self.assertEqual(v['id'], f.stem)
            self.assertLessEqual(set(v), allowed, f.name)
            date.fromisoformat(v['checked'])
            self.assertTrue(v['sources'] or not v['verified'], f.name)
            self.assertTrue(all(u.startswith('https://') for u in v['sources']), f.name)
            self.assertLessEqual(set(v['pages']), {'submission', 'camera-ready', 'uncounted'})
            if v.get('style', {}).get('sha256'):
                self.assertRegex(v['style']['sha256'], r'^[0-9a-f]{64}$')
            for r in v.get('required', []) + v.get('forbidden', []):
                re.compile(r['pattern'])
                self.assertLessEqual(set(r['modes']), set(preflight.MODES))
            if v.get('named_if'):
                re.compile(v['named_if'])
                self.assertTrue(v['switch']['submission'] and v['switch']['camera-ready'])

    def test_named_if_patterns(self):
        cases = {'neurips-2026': ('\\usepackage[main, final]{neurips_2026}', '\\usepackage{neurips_2026}'),
                 'iclr-2026': ('\\iclrfinalcopy', '\\usepackage{iclr2026_conference}'),
                 'icml-2026': ('\\usepackage[accepted]{icml2026}', '\\usepackage{icml2026}'),
                 'arr-2026': ('\\usepackage[final]{acl}', '\\usepackage[review]{acl}'),
                 'cvpr-2026': ('\\usepackage{cvpr}', '\\usepackage[review]{cvpr}'),
                 'acm-sigconf': ('\\documentclass[sigconf]{acmart}', '\\documentclass[sigconf,review,anonymous]{acmart}')}
        for vid, (named, anon) in cases.items():
            rx = preflight.load_venue(vid)['named_if']
            self.assertRegex(named, rx, vid)
            self.assertNotRegex(anon, rx, vid)


if __name__ == '__main__':
    unittest.main()
