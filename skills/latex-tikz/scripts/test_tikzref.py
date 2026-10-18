"""Run: python3 -m unittest discover skills/latex-tikz/scripts"""
import unittest

from tikzref import load, search


class TikzrefTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = load()

    def test_index_shape(self):
        self.assertGreater(sum('c' in r for r in self.records), 1000)
        self.assertTrue(all(r['p'] and ('c' in r) != ('k' in r) for r in self.records))

    def test_relevant_hits(self):
        hit = search(self.records, 'brace decoration', n=1)[0]
        self.assertIn('decoration=brace', hit['c'].replace(' ', ''))
        self.assertTrue(all('fit' in r['c'] for r in search(self.records, 'fit', n=3, lib='library-fit')))
        keys = search([r for r in self.records if 'chains' in r['p']], 'join', n=5, keys=True)
        self.assertTrue(any(k['k'].startswith('/tikz/join') for k in keys))

    def test_shorter_wins_ties_and_no_match(self):
        self.assertEqual(search(self.records, 'zzqx-no-such-term'), [])


if __name__ == '__main__':
    unittest.main()
