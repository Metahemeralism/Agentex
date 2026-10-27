"""Run: python3 -m unittest discover skills/latex-arxiv/scripts"""
import json
import unittest

import refresh_bindings

LIB = 'static BINDINGS = &[\n' + ''.join(f'  ("pkg{i}", "sty", package::pkg{i}_sty::load_definitions),\n' for i in range(120)) + \
      '  ("tikz-cd", "sty", package::tikz_cd_sty::load_definitions),\n  ("Article", "cls", x),\n  ("t1", "fontmap", y),\n];\n'


class SnapshotTest(unittest.TestCase):
    def fake(self, url):
        if 'api.github.com' in url:
            return json.dumps({'sha': 'abc123def4567890', 'commit': {'committer': {'date': '2026-08-23T21:06:09Z'}}})
        self.assertIn('/abc123def4567890/', url)  # tables are read at the pinned commit
        return LIB

    def test_snapshot(self):
        text = refresh_bindings.snapshot(fetch=self.fake)
        lines = text.splitlines()
        self.assertTrue(all(l.startswith('#') for l in lines[:3]))
        self.assertIn('commit abc123def456 of 2026-08-23', lines[1])
        body = lines[3:]
        self.assertIn('tikz-cd.sty', body)
        self.assertIn('Article.cls', body)
        self.assertNotIn('t1.fontmap', body)
        self.assertEqual(len(body), 122)

    def test_format_change_is_an_error(self):
        with self.assertRaises(ValueError):
            refresh_bindings.snapshot(fetch=lambda url: json.dumps({'sha': 's', 'commit': {'committer': {'date': 'd'}}})
                                      if 'api.' in url else '')


if __name__ == '__main__':
    unittest.main()
