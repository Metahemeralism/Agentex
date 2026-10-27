#!/usr/bin/env python3
"""Write a matplotlib style sized to this paper's measured layout, so figures go in at scale 1.

Usage: mplstyle.py main.tex -o paper.mplstyle [--column|--text]
  plt.style.use("paper.mplstyle")             # figsize = \\columnwidth (or \\textwidth), fonts = caption size
  fig.savefig("figures/loss.pdf")             # keep the style's figsize: don't resize or pass a scale
  \\includegraphics[width=\\columnwidth]{figures/loss}   # scale ~1, so fonts print at the size set here
Layout comes from figcheck.py's cache (.agentex/layout.json), compiling the preamble when needed. Stdlib only.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figcheck import measure, strip_comments  # noqa: E402

OKABE_ITO = ['0072B2', 'E69F00', '009E73', 'D55E00', 'CC79A7', '56B4E9', '000000', 'F0E442']  # yellow last: faint
TIMES = re.compile(r'\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*\b(?:times|mathptmx|newtxtext|txfonts|ptm)\b'
                   r'|\\documentclass\s*(?:\[[^\]]*\])?\s*\{IEEEtran\}')
RATIO = {'column': 0.62, 'text': 0.35}  # height/width: golden for a column; wide figures are usually a panel row


def font_sizes(layout):
    body = layout.get('normalsize', 10)
    return body, layout.get('small', body * 0.9), layout.get('footnotesize', body * 0.8)


def style(layout, span, times, source):
    width = layout[f'{span}width'] / 72.27  # TeX pt -> inches
    body, small, foot = font_sizes(layout)
    serif = ('Times New Roman, Times, Nimbus Roman, STIXGeneral, DejaVu Serif', 'stix') if times \
        else ('CMU Serif, Latin Modern Roman, DejaVu Serif', 'cm')
    return f"""# AgenTeX style for {source}: \\{span}width = {layout[f'{span}width']:g}pt ({width:.2f}in), body {body:g}pt
# plt.style.use("this.mplstyle"); fig.savefig("fig.pdf"); then \\includegraphics[width=\\{span}width]{{fig}}
figure.figsize: {width:.2f}, {width * RATIO[span]:.2f}
font.family: serif
font.serif: {serif[0]}
mathtext.fontset: {serif[1]}
font.size: {small:g}
axes.labelsize: {small:g}
axes.titlesize: {body:g}
figure.titlesize: {body:g}
xtick.labelsize: {foot:g}
ytick.labelsize: {foot:g}
legend.fontsize: {foot:g}
legend.frameon: False
axes.prop_cycle: cycler('color', {OKABE_ITO})
axes.linewidth: 0.6
axes.spines.top: False
axes.spines.right: False
xtick.major.width: 0.6
ytick.major.width: 0.6
xtick.major.size: 3
ytick.major.size: 3
lines.linewidth: 1.2
lines.markersize: 4
pdf.fonttype: 42
ps.fonttype: 42
savefig.bbox: tight
savefig.pad_inches: 0.02
savefig.dpi: 300
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tex', type=Path)
    ap.add_argument('-o', '--out', type=Path, required=True, help='style file to write, e.g. paper.mplstyle')
    span = ap.add_mutually_exclusive_group()
    span.add_argument('--column', dest='span', action='store_const', const='column', help='\\columnwidth (default)')
    span.add_argument('--text', dest='span', action='store_const', const='text', help='\\textwidth (figure*)')
    args = ap.parse_args(argv)
    main_tex = args.tex.resolve()
    if not main_tex.exists():
        print(f'not found: {args.tex}')
        return 2
    layout, note = measure(main_tex)
    if not layout:
        print(f'no layout for {args.tex}: {note}')
        return 2
    span = args.span or 'column'
    times = bool(TIMES.search(strip_comments(main_tex.read_text(encoding='utf-8', errors='replace'))))
    args.out.write_text(style(layout, span, times, main_tex.name))
    w, (_, small, foot) = layout[f'{span}width'] / 72.27, font_sizes(layout)
    print(f'wrote {args.out}: {w:.2f} x {w * RATIO[span]:.2f} in (\\{span}width, {note}), fonts {small:g}/{foot:g}pt, '
          f"{'Times' if times else 'Computer Modern'}-like serif, Okabe-Ito colours, pdf.fonttype 42")
    print(f'use: plt.style.use("{args.out}"); save without resizing; '
          f'\\includegraphics[width=\\{span}width]{{...}}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
