# Third-party material

These files come from **latex-document-skill** (https://github.com/ndpvt-web/latex-document-skill, MIT), adapted for AgenTeX:

- `templates/*.tex`: copied, then fixed so every one compiles with tectonic/XeTeX as well as pdfLaTeX: `book`/`thesis` (amssymb and amsthm vs newpxmath clashes), `lecture-notes`/`book`/`thesis` (microtype options XeTeX rejects), `lab-report` (`\pdfoutput` broke hyperref under XeTeX), `letter` (nested overlay picture misplaced the logo; banner too short), `mail-merge-letter` (header rewritten for AgenTeX's merge syntax). The resume templates gained a guarded `glyphtounicode` line so pdfLaTeX output extracts cleanly for ATS parsers
- `reference/cheatsheets.md`: condensed from the original `references/cheatsheet-guide.md`
- `scripts/mail_merge.py` is AgenTeX's own (stdlib, no Jinja2)

## Licence

Copyright (c) the latex-document-skill authors (https://github.com/ndpvt-web/latex-document-skill)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
USE OR OTHER DEALINGS IN THE SOFTWARE.
