# tikz-manual.jsonl: provenance and licence

`tikz-manual.jsonl` contains code examples and key/command signatures extracted unmodified
from the PGF/TikZ manual by Till Tantau and the PGF/TikZ team, as published in HTML form at
https://tikz.dev (HTML conversion by Dominik Peters).

The PGF/TikZ documentation is dual-licensed under the **LaTeX Project Public License 1.3c**
and the **GNU Free Documentation License 1.2**. This file is distributed under LPPL 1.3c
(https://www.latex-project.org/lppl/lppl-1-3c/). It is **not** covered by AgenTeX's MIT licence.

Rebuild it with `scripts/build_index.py` (fetches the manual pages and re-extracts the examples).
Each record carries the page it came from, e.g. `{"p": "library-fit", ...}` → https://tikz.dev/library-fit.
