"""Plugin hygiene: skill frontmatter, lean bodies, no dead or orphaned files, counts in sync.

Run: python3 -m unittest discover -s tests
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted(p for p in (ROOT / 'skills').iterdir() if (p / 'SKILL.md').exists())
FRONT = re.compile(r'\A---\nname: (?P<name>.+)\ndescription: "(?P<desc>.+)"\n---\n', re.S)
OWN_PATH = re.compile(r'(?:<skill>/)?\b((?:scripts|templates|reference|assets)/[\w./-]+\.\w+)')
OTHER_PATH = re.compile(r'(?:<skill>/\.\./)?\b(latex-[a-z-]+)/((?:scripts|templates|reference|assets)/[\w./-]+\.\w+)')
MAX_DESC, MAX_BODY_LINES = 300, 500  # CLAUDE.md convention; Agent Skills guidance for SKILL.md bodies


def skill_md(skill):
    return (skill / 'SKILL.md').read_text(encoding='utf-8')


class PluginTest(unittest.TestCase):
    def test_frontmatter(self):
        for skill in SKILLS:
            m = FRONT.match(skill_md(skill))
            self.assertIsNotNone(m, f'{skill.name}: frontmatter must be name + one-line quoted description')
            self.assertEqual(m['name'], skill.name)
            self.assertRegex(m['name'], r'^[a-z0-9-]{1,64}$')
            desc = m['desc'].replace('\\\\', '\\')
            self.assertLessEqual(len(desc), MAX_DESC, f'{skill.name}: description is {len(desc)} chars')
            self.assertNotRegex(desc, r'<[a-zA-Z/]', f'{skill.name}: no XML-like tags in descriptions')

    def test_bodies_are_lean(self):
        for skill in SKILLS:
            self.assertLessEqual(skill_md(skill).count('\n'), MAX_BODY_LINES, skill.name)

    def test_mentioned_files_exist(self):
        for skill in SKILLS:
            text = skill_md(skill)
            # cross-skill paths first, then blank them so their tails are not read as this skill's own paths
            for other, rel in OTHER_PATH.findall(text):
                self.assertTrue((ROOT / 'skills' / other / rel).exists(), f'{skill.name}: {other}/{rel} does not exist')
            own = OTHER_PATH.sub(' ', text)
            # unprefixed paths inside code blocks may be the user's own files (e.g. a manifest example)
            prose = re.sub(r'```.*?```', ' ', own, flags=re.S)
            rels = re.findall(r'<skill>/((?:scripts|templates|reference|assets)/[\w./-]+\.\w+)', own) + OWN_PATH.findall(prose)
            for rel in rels:
                if '<' not in rel and '*' not in rel:
                    self.assertTrue((skill / rel).exists(), f'{skill.name}: {rel} does not exist')

    def test_no_orphaned_references(self):
        for skill in SKILLS:
            text = skill_md(skill)
            for ref in (skill / 'reference').rglob('*.md') if (skill / 'reference').exists() else []:
                if ref.name != 'NOTICE.md':
                    self.assertIn(ref.name, text, f'{skill.name}: {ref.relative_to(skill)} is never mentioned in SKILL.md')

    def test_counts_in_sync(self):
        n = len(SKILLS)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn(f'badge/skills-{n}-', readme)
        self.assertEqual(len(re.findall(r'^\| [^|]*\| \[`latex-[a-z-]+`\]', readme, re.M)), n, 'README skills table rows')
        self.assertIn(f'{n} skills', json.loads((ROOT / '.claude-plugin' / 'plugin.json').read_text())['description'])
        self.assertIn(f'{n} skills', (ROOT / 'install.sh').read_text())


if __name__ == '__main__':
    unittest.main()
