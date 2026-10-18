"""Offline tests (no network). Run: python3 -m unittest discover skills/latex-research-check/scripts"""
import tempfile
import unittest

from related import from_tex, keywords, merge, rank


def rec(title, source, doi='', arxiv='', abstract='', cites=0, venue=''):
    return {'title': title, 'year': 2024, 'venue': venue, 'cites': cites, 'doi': doi, 'arxiv': arxiv,
            'url': '', 'abstract': abstract, 'source': source}


class RelatedTest(unittest.TestCase):
    def test_merge_dedupes_across_sources(self):
        merged = merge([rec('Graph Networks for Weather', 'openalex', doi='10.1/ABC', cites=50, venue='Science'),
                        rec('Graph networks for weather!', 'arxiv', arxiv='2212.12794', abstract='long abstract', venue='arXiv'),
                        rec('Unrelated', 's2')])
        self.assertEqual(len(merged), 2)
        m = merged[0]
        self.assertEqual(m['sources'], {'openalex', 'arxiv'})
        self.assertEqual((m['arxiv'], m['abstract'], m['venue'], m['cites']), ('2212.12794', 'long abstract', 'Science', 50))

    def test_rank_prefers_similar_text(self):
        papers = [dict(rec('Protein folding with transformers', 'x', abstract='protein structure prediction'), sources=set()),
                  dict(rec('Graph neural networks for medium-range weather forecasting', 'x',
                           abstract='message passing on a mesh predicts atmospheric state'), sources=set())]
        top = rank('We forecast global weather with a graph neural network using message passing', papers)[0]
        self.assertIn('weather', top['title'])
        self.assertGreater(top['score'], 0.2)

    def test_from_tex_and_keywords(self):
        with tempfile.NamedTemporaryFile('w', suffix='.tex', delete=False) as f:
            f.write('\\title{Fast \\emph{Sparse} Attention}\n% \\title{old}\n\\begin{abstract}Sparse attention '
                    'reduces attention cost; sparse kernels make attention fast.\\end{abstract}')
        title, abstract = from_tex(f.name)
        self.assertEqual(title, 'Fast Sparse Attention')
        self.assertEqual(keywords(abstract, 2), ['attention', 'sparse'])


if __name__ == '__main__':
    unittest.main()
