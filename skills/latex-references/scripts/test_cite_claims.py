"""Offline tests (HTTP mocked). Run: python3 -m unittest discover skills/latex-references/scripts"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cite_claims
import cite_verify

MAIN = r"""\documentclass{article}
\begin{document}
\section{Intro}
Transformers dispense with recurrence, e.g.\ in translation \citep{vaswani2017}. Residual
networks are \textbf{easy} to train \cite[p.~3]{he2016}.
% \cite{ghost} is commented out
\nocite{numpy}
\input{sec/more}
\end{document}
"""
MORE = r"""As shown by Smith et al.~\cite{smith2020}, deeper is better (Fig.~\ref{fig:a}).

Our own result \cite{lee2021} holds.
"""
BIB = r"""
@article{vaswani2017, title={Attention Is All You Need}, author={Vaswani, A.}, year={2017}, eprint={1706.03762}, archivePrefix={arXiv}}
@inproceedings{he2016, title={Deep Residual Learning}, author={He, K.}, year={2016}, doi={10.1/withabs}}
@article{smith2020, title={Deeper Is Better}, author={Smith, J.}, year={2020}, doi={10.1/noabs}}
@article{lee2021, title={An Unindexed Note}, author={Lee, K.}, year={2021}, abstract={We show \emph{the} result.}}
@software{numpy, title={NumPy}, author={{NumPy Developers}}, year={2024}}
"""
LONG = 'Residual learning eases training. ' * 50  # ~1,700 chars: cut in `next`
ATOM = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v7</id>'
        '<title>Attention Is All You Need</title><summary> We propose the Transformer,\n based solely on attention. </summary>'
        '<published>2017-06-12</published><author><name>Ashish Vaswani</name></author></entry></feed>')


def fake_http(calls):
    def http(url, accept='application/json', **kw):
        calls.append(url)
        if 'export.arxiv.org' in url:
            return ATOM
        if url.endswith('/works/10.1/withabs'):
            return json.dumps({'message': {'abstract': f'<jats:title>Abstract</jats:title><jats:p>{LONG}&amp; more</jats:p>'}})
        if url.endswith('/works/10.1/noabs'):
            return json.dumps({'message': {}})
        if 'openalex.org/works/doi:10.1/noabs' in url:
            return json.dumps({'abstract_inverted_index': {'Deeper': [0], 'nets': [1, 3], 'beat': [2]}})
        if 'openalex.org/works?' in url:
            return json.dumps({'results': [{'title': 'Something Else Entirely', 'abstract_inverted_index': {'No': [0]}}]})
        return None
    return http


class ClaimsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'sec').mkdir()
        (self.root / 'main.tex').write_text(MAIN)
        (self.root / 'sec' / 'more.tex').write_text(MORE)
        (self.root / 'orphan.tex').write_text('Not part of the paper \\cite{orphan}.')
        (self.root / 'refs.bib').write_text(BIB)
        self.calls = []
        patches = [mock.patch.object(cite_verify, 'http', fake_http(self.calls)), mock.patch.object(cite_verify.time, 'sleep')]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def extract(self):
        with contextlib.redirect_stderr(io.StringIO()):
            return cite_claims.extract(self.root)

    def claims(self):
        return json.loads((self.root / '.agentex' / 'claims.json').read_text())['claims']

    def by_key(self):
        return {tuple(c['keys']): (cid, c) for cid, c in self.claims().items()}

    def test_sentences(self):
        self.extract()
        got = {k: (c['where'], c['sentence']) for k, (_, c) in self.by_key().items()}
        self.assertEqual(got, {
            ('vaswani2017',): ('main.tex:4', 'Transformers dispense with recurrence, e.g. in translation [vaswani2017].'),
            ('he2016',): ('main.tex:5', 'Residual networks are easy to train [he2016].'),
            ('smith2020',): ('sec/more.tex:1', 'As shown by Smith et al. [smith2020], deeper is better (Fig. [ref]).'),
            ('lee2021',): ('sec/more.tex:3', 'Our own result [lee2021] holds.')})  # no ghost, numpy (\nocite) or orphan

    def test_abstract_helpers(self):
        self.assertEqual(cite_claims.inverted({'b': [1], 'a': [0, 2]}), 'a b a')
        self.assertEqual(cite_claims.jats('<jats:title>Abstract</jats:title><jats:p>X &amp; Y</jats:p>'), 'X & Y')

    def test_workflow(self):
        out = self.extract()
        self.assertIn('4 cited claims in 2 files', out)
        store = json.loads((self.root / '.agentex' / 'abstracts.json').read_text())['abstracts']
        self.assertEqual({k: v['source'] for k, v in store.items()},
                         {'vaswani2017': 'arxiv', 'he2016': 'crossref', 'smith2020': 'openalex', 'lee2021': 'bib'})
        self.assertEqual(store['smith2020']['abstract'], 'Deeper nets beat nets')
        self.assertEqual(store['lee2021']['abstract'], 'We show the result.')  # title search hit was a different work
        self.assertTrue(any('api.openalex.org/works?' in u for u in self.calls))

        nxt = cite_claims.next_items(self.root, n=2)
        self.assertIn('2 of 4 pending', nxt)
        self.assertIn('- vaswani2017 (arxiv): We propose the Transformer, based solely on attention.', nxt)
        he = next(line for line in nxt.splitlines() if line.startswith('- he2016'))
        self.assertTrue(he.endswith(' …') and len(he) < cite_claims.ABSTRACT_CHARS + 30)

        ids = self.by_key()
        sid, _ = ids[('smith2020',)]
        self.assertIn('recorded contradicted', cite_claims.record(self.root, [sid], 'contradicted', 'abstract says shallower'))
        cite_claims.record(self.root, [ids[('he2016',)][0], ids[('vaswani2017',)][0]], 'supported')
        cite_claims.record(self.root, [ids[('lee2021',)][0]], 'not-in-abstract')
        with self.assertRaises(SystemExit):
            cite_claims.record(self.root, ['cdeadbeef'], 'supported')

        text, contradicted = cite_claims.report(self.root)
        self.assertEqual(contradicted, 1)
        self.assertIn('CONTRADICTED     sec/more.tex:1  [smith2020]', text)
        self.assertIn('abstract says shallower', text)
        self.assertIn('NOT-IN-ABSTRACT  sec/more.tex:3', text)
        st = json.loads((self.root / '.agentex' / 'status' / 'cite-claims.json').read_text())
        self.assertEqual((st['tool'], st['status'], st['counts']['contradicted'], st['counts']['pending']), ('cite-claims', 'fail', 1, 0))
        self.assertEqual([i['where'] for i in st['items']], ['sec/more.tex:1', 'sec/more.tex:3'])

        # Re-extract: verdicts survive, abstracts are cached (no requests); an edited sentence is pending again.
        n = len(self.calls)
        (self.root / 'sec' / 'more.tex').write_text(MORE.replace('Our own', 'Our new'))
        self.assertIn('3 keep their verdicts', self.extract())
        self.assertEqual(len(self.calls), n)
        self.assertEqual(self.by_key()[('smith2020',)][1]['verdict'], 'contradicted')
        self.assertIsNone(self.by_key()[('lee2021',)][1]['verdict'])
        self.assertEqual((self.root / 'main.tex').read_text(), MAIN)  # never edits the paper

    def test_cli(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cite_claims.main(['extract', str(self.root)]), 0)
            self.assertEqual(cite_claims.main(['next', '--dir', str(self.root), '--n', '1']), 0)
            self.assertEqual(cite_claims.main(['report', '--dir', str(self.root)]), 0)
        self.assertIn('1 of 4 pending', out.getvalue())
        self.assertIn('pending 4', out.getvalue())


if __name__ == '__main__':
    unittest.main()
