"""Offline tests with fake lookups. Run: python3 -m unittest discover skills/latex-references/scripts"""
import tempfile
import unittest
from pathlib import Path

from cite_verify import arxiv_id, parse_bib, rec, run, verify_entry

BIB = r"""
@string{neurips = "Advances in Neural Information Processing Systems"}
@comment{ignored @article{fake, title={x}} }
@inproceedings{he2016,
  author = {He, Kaiming and Zhang, Xiangyu and Ren, Shaoqing and Sun, Jian},
  title = {Deep Residual Learning for Image Recognition},
  booktitle = {CVPR}, year = 2016, doi = {10.1109/CVPR.2016.90}}
@article{kingma2015,
  author = "Kingma, Diederik P. and Ba, Jimmy",
  title = "{Adam}: A Method for Efficient Optimization",
  journal = {arXiv preprint arXiv:1412.6980}, year = {2015}}
@inproceedings{vaswani2017,
  author = {Ashish Vaswani and Noam Shazeer and others},
  title = {Attention Is All You Need},
  booktitle = neurips # " 30", year = {2017}, eprint = {1706.03762}, archivePrefix = {arXiv}}
@article{ghost2023,
  author = {Smith, John and Doe, Jane},
  title = {Quantum Gradient Folding for Universal Self-Supervised Reasoning},
  journal = {Journal of Imaginary Results}, year = {2023}}
@article{wrongdoi,
  author = {M{\"u}ller, Anna},
  title = {Sparse Attention Kernels},
  journal = {J. Sparse}, year = {2021}, doi = {10.9999/other}}
@misc{he2016dup, author = {He, Kaiming}, title = {Deep residual learning for image recognition}, year = {2016}}
@software{numpy, title = {NumPy}, author = {{NumPy Developers}}, year = {2024}}
"""

TEX = r"\cite{he2016,kingma2015} \citep{vaswani2017} \parencite{ghost2023, wrongdoi} \cite{numpy} \cite{nokey}"


class FakeLookups:
    calls = 0

    def doi(self, doi):
        self.calls += 1
        return {'10.1109/CVPR.2016.90': rec('Deep Residual Learning for Image Recognition', ['he', 'zhang', 'ren', 'sun'], 2016,
                                             'CVPR', '10.1109/CVPR.2016.90', source='crossref'),
                '10.9999/other': rec('A Completely Unrelated Paper on Soil Chemistry', ['brown'], 2019, source='crossref')}.get(doi)

    def arxiv(self, aid):
        self.calls += 1
        return {'1706.03762': rec('Attention Is All You Need', ['vaswani', 'shazeer', 'parmar'], 2017, '', '', '1706.03762', 'arxiv'),
                '1412.6980': rec('Adam: A Method for Stochastic Optimization', ['kingma', 'ba'], 2014, '', '', '1412.6980', 'arxiv')}.get(aid)

    def s2_arxiv(self, aid):
        self.calls += 1
        return {'1706.03762': rec('Attention is All you Need', ['vaswani'], 2017, 'Neural Information Processing Systems',
                                  '', aid, 'semantic-scholar', bibtex='@inproceedings{X, title={Attention is All you Need}}'),
                '1412.6980': rec('Adam: A Method for Stochastic Optimization', ['kingma', 'ba'], 2014,
                                 'International Conference on Learning Representations', '', aid, 'semantic-scholar')}.get(aid)

    def dblp(self, title):
        self.calls += 1
        if 'attention is all you need' in title.lower():
            return [rec('Attention is All you Need', ['vaswani', 'shazeer'], 2017, 'NIPS', '', '', 'dblp', dblp_key='conf/nips/X17')]
        if 'sparse attention kernels' in title.lower():
            return [rec('Sparse Attention Kernels', ['muller'], 2021, 'J. Sparse', '10.1/real', source='dblp')]
        return []

    def crossref_search(self, title, author=''):
        self.calls += 1
        return []

    def openalex(self, title):
        self.calls += 1
        return []


class ParseTest(unittest.TestCase):
    def test_parse(self):
        es = {e['key']: e for e in parse_bib(BIB)}
        self.assertNotIn('fake', es)  # inside @comment
        self.assertEqual(es['vaswani2017']['fields']['booktitle'], 'Advances in Neural Information Processing Systems 30')
        self.assertEqual(es['he2016']['fields']['year'], '2016')
        self.assertEqual(es['kingma2015']['fields']['title'], '{Adam}: A Method for Efficient Optimization')
        self.assertEqual(arxiv_id(es['kingma2015']['fields']), '1412.6980')
        self.assertEqual(arxiv_id(es['vaswani2017']['fields']), '1706.03762')


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.es = {e['key']: e for e in parse_bib(BIB)}
        self.L = FakeLookups()

    def status(self, key):
        return verify_entry(self.es[key], self.L)

    def test_classification(self):
        self.assertEqual(self.status('he2016')['status'], 'verified')
        r = self.status('kingma2015')  # "Frankenstein": real paper, wrong title
        self.assertEqual(r['status'], 'mismatch')
        self.assertIn('Stochastic Optimization', r['message'])
        self.assertIn('Learning Representations', r['message'])  # and points to the published version
        r = self.status('vaswani2017')
        self.assertEqual(r['status'], 'published')
        self.assertIn('Neural Information Processing Systems', r['message'])
        self.assertTrue(r['record']['bibtex'])  # suggestion source for venues without DOIs
        self.assertEqual(self.status('ghost2023')['status'], 'not-found')
        r = self.status('wrongdoi')  # DOI points elsewhere, but the title exists
        self.assertEqual(r['status'], 'bad-doi')
        self.assertIn('different work', r['message'])
        self.assertEqual(self.status('numpy')['status'], 'unverifiable')

    def test_run_cache_and_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'refs.bib').write_text(BIB)
            (root / 'main.tex').write_text('\\addbibresource{refs.bib}\n' + TEX + '\n\\cite{he2016dup}')
            _, _, results, dups = run(root, L=self.L)
            self.assertEqual(results['nokey']['status'], 'missing')
            self.assertEqual({(a, b) for a, b, _ in dups}, {('he2016', 'he2016dup')})
            n = self.L.calls
            _, _, again, _ = run(root, L=self.L)
            self.assertEqual(self.L.calls - n, 3)  # cache hit for all but not-found ghost2023 (dblp, crossref, openalex)
            self.assertEqual(again['he2016']['status'], 'verified')
            self.assertTrue((root / '.agentex' / 'cite-cache.json').exists())


if __name__ == '__main__':
    unittest.main()
