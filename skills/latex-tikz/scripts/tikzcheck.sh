#!/usr/bin/env bash
# Compile one standalone figure and print only what matters: the first errors (never the
# whole log), a warning count, and a small PNG preview to look at.
# Usage: tikzcheck.sh path/to/fig.tex [dpi]
#   dpi defaults to 100: enough to judge layout while the image stays a few hundred tokens.
set -u
tex=${1:?usage: tikzcheck.sh fig.tex [dpi]}
dpi=${2:-100}
cd "$(dirname "$tex")" || exit 2
base=$(basename "$tex" .tex)

if command -v latexmk >/dev/null 2>&1; then
  latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error -silent "$base.tex" >/dev/null 2>&1
elif command -v tectonic >/dev/null 2>&1; then
  tectonic --keep-logs "$base.tex" >/dev/null 2>&1
else
  echo "no TeX engine: install TeX Live / MacTeX, or tectonic (brew install tectonic)"; exit 2
fi
status=$?

# latexmkrc may redirect output (e.g. $out_dir = 'build').
log=$(ls -t "$base.log" build/"$base.log" 2>/dev/null | head -1)
pdf=$(ls -t "$base.pdf" build/"$base.pdf" 2>/dev/null | head -1)

if [ $status -ne 0 ] || [ -z "$pdf" ]; then
  echo "FAILED $base.tex"
  [ -n "$log" ] && grep -m3 -A3 -E '^!|^[^ ]*\.tex:[0-9]+: ' "$log"
  exit 1
fi

warns=$( [ -n "$log" ] && grep -cE '^(Overfull|Underfull) \\[hv]box|Warning' "$log" || echo 0)
out="${TMPDIR:-/tmp}/agentex-preview"; mkdir -p "$out"
png="$out/$base.png"
if command -v pdftoppm >/dev/null 2>&1; then
  pdftoppm -png -r "$dpi" -singlefile "$pdf" "${png%.png}"
elif command -v sips >/dev/null 2>&1; then
  sips -s format png "$pdf" --out "$png" >/dev/null 2>&1
else
  png="(no renderer; open $pdf)"
fi
echo "OK $pdf | warnings: $warns | preview: $png"
