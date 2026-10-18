#!/usr/bin/env python3
"""Lint LaTeX cross-references and citations across a project.

Usage: python3 check_refs.py <project_dir> [--bib file.bib ...]

Reports undefined/duplicate labels, unused labels, citations missing from
the .bib files, duplicate bib keys and unused bib entries. Stdlib only.
Exit code 1 if any *errors* (undefined refs, missing cites, duplicates).
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

REF_CMDS = r"(?:ref|eqref|pageref|autoref|nameref|cref|Cref|crefrange|Crefrange|cpageref|vref|Vref)"
CITE_CMDS = (
    r"(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|parencite|textcite|"
    r"autocite|footcite|fullcite|smartcite|supercite|nocite|Cite|Citep|Citet|"
    r"Parencite|Textcite|Autocite)\*?"
)
# \cmd[opt][opt]{key1,key2}
REF_RE = re.compile(r"\\" + REF_CMDS + r"\*?\s*\{([^}]*)\}")
CITE_RE = re.compile(r"\\" + CITE_CMDS + r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}")
LABEL_RE = re.compile(r"\\label\s*\{([^}]*)\}")
BIBKEY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,")
BIBFILE_RE = re.compile(r"\\(?:addbibresource|bibliography)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


def strip_comments(text):
    # Drop everything after an unescaped %; keeps line numbers intact.
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in text.splitlines())


def scan(regex, text, path):
    """Yield (key, 'file:line') for every comma-separated key the regex captures."""
    for m in regex.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        for key in m.group(1).split(","):
            if key.strip():
                yield key.strip(), f"{path}:{line}"


def analyse(root, extra_bibs=()):
    labels, refs, cites, bibkeys = (defaultdict(list) for _ in range(4))
    bib_files = {Path(b) for b in extra_bibs}

    for tex in sorted(root.rglob("*.tex")):
        text = strip_comments(tex.read_text(encoding="utf-8", errors="replace"))
        rel = tex.relative_to(root)
        for k, loc in scan(LABEL_RE, text, rel):
            labels[k].append(loc)
        for k, loc in scan(REF_RE, text, rel):
            refs[k].append(loc)
        for k, loc in scan(CITE_RE, text, rel):
            cites[k].append(loc)
        for m in BIBFILE_RE.finditer(text):
            for name in m.group(1).split(","):
                name = name.strip()
                p = (tex.parent / name)
                bib_files.add(p if p.suffix == ".bib" else p.with_suffix(".bib"))

    if not bib_files:
        bib_files = set(root.rglob("*.bib"))
    for bib in sorted(bib_files):
        if not bib.exists():
            print(f"warning: bibliography file not found: {bib}", file=sys.stderr)
            continue
        text = bib.read_text(encoding="utf-8", errors="replace")
        for m in BIBKEY_RE.finditer(text):
            if m.group(1).lower() in {"string", "preamble", "comment"}:
                continue
            line = text.count("\n", 0, m.start()) + 1
            bibkeys[m.group(2)].append(f"{bib.name}:{line}")

    nocite_all = "*" in cites
    return {
        "errors": {
            "undefined reference": {k: v for k, v in refs.items() if k not in labels},
            "duplicate label": {k: v for k, v in labels.items() if len(v) > 1},
            "citation not in .bib": {k: v for k, v in cites.items() if k != "*" and k not in bibkeys},
            "duplicate bib key": {k: v for k, v in bibkeys.items() if len(v) > 1},
        },
        "warnings": {
            "label never referenced": {k: v for k, v in labels.items() if k not in refs},
            "bib entry never cited": {} if nocite_all else {k: v for k, v in bibkeys.items() if k not in cites},
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--bib", nargs="*", default=[], help="extra .bib files (default: auto-detect)")
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        ap.error(f"not a directory: {args.project_dir}")

    report = analyse(args.project_dir, args.bib)
    n_errors = 0
    for severity in ("errors", "warnings"):
        for issue, items in report[severity].items():
            if not items:
                continue
            if severity == "errors":
                n_errors += len(items)
            print(f"\n[{severity[:-1].upper()}] {issue} ({len(items)})")
            for key, locs in sorted(items.items()):
                print(f"  {key:30s} {', '.join(locs)}")
    print(f"\n{n_errors} error(s).")
    return 1 if n_errors else 0


if __name__ == "__main__":
    sys.exit(main())
