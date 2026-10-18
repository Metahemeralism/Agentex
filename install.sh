#!/usr/bin/env bash
# AgenTeX installer: installs the Claude Code plugin while a small typesetting animation plays
# (TeX's E drops into place). Plain output when not run in a terminal.
#
#   curl -fsSL https://raw.githubusercontent.com/Metahemeralism/AgenTeX/main/install.sh | bash
#   bash install.sh [marketplace-source]     # default Metahemeralism/AgenTeX; a local path works too
set -u

SOURCE="${1:-Metahemeralism/AgenTeX}"
if ! command -v claude >/dev/null 2>&1; then
  echo "AgenTeX needs Claude Code first: https://claude.com/claude-code" >&2
  exit 1
fi

log="$(mktemp)"
claude plugin install agentex --marketplace "$SOURCE" >"$log" 2>&1 &
pid=$!

animate=0
{ [ -t 1 ] || [ "${AGENTEX_FORCE_ANIMATION:-}" = 1 ]; } && animate=1
if [ -n "${NO_COLOR:-}" ]; then BLUE='' BOLD='' DIM='' OFF=''
else
  BOLD=$'\033[1m' DIM=$'\033[2m' OFF=$'\033[0m'
  case "${COLORTERM:-}" in truecolor|24bit) BLUE=$'\033[38;2;86;180;233m' ;; *) BLUE=$'\033[38;5;74m' ;; esac
fi
if locale charmap 2>/dev/null | grep -qi utf; then SPIN=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏) TICK='✓'
else SPIN=('|' '/' '-' '\') TICK='ok'; fi

# Two rows: "AgenT X" over "     E" once the E has dropped (TeX's lowered E).
draw() { # draw <letters shown 0-7> <E dropped 0|1> <text after the logo> <text on the second row>
  local n=$1 down=$2 agen="Agen" t=' ' e=' ' x=' ' low=' '
  agen="${agen:0:$(( n < 4 ? n : 4 ))}"
  (( n > 4 )) && t='T'
  if (( n > 5 )); then if (( down )); then low='E'; else e='E'; fi; fi
  (( n > 6 )) && x='X'
  printf '\r  %s%s%-4s%s%s%s%s%s%s  %s\033[K\n' "$BLUE" "$BOLD" "$agen" "$OFF" "$BOLD" "$t" "$e" "$x" "$OFF" "$3"
  printf '\r       %s%s%s  %s%s%s\033[K\n' "$BOLD" "$low" "$OFF" "$DIM" "$4" "$OFF"
  printf '\033[2A'
}

if (( animate )); then
  printf '\033[?25l'                       # hide the cursor while drawing
  trap 'printf "\033[?25h\n\n"' EXIT
  printf '\n\n\033[2A'
  i=0
  while :; do                               # play at least the drop (~1.2 s), then until install ends
    if (( i < 7 )); then draw $(( i + 1 )) 0 '' ''
    else
      s="${SPIN[$(( i % ${#SPIN[@]} ))]}"
      draw 7 $(( i >= 9 && (i / 5) % 2 == 0 )) "${BLUE}${s} installing the plugin${OFF}" "14 skills · cite guard · compile loop"
    fi
    (( i >= 12 )) && ! kill -0 "$pid" 2>/dev/null && break
    i=$(( i + 1 ))
    sleep 0.1
  done
fi

wait "$pid"
status=$?
if (( status == 0 )); then
  if (( animate )); then
    draw 7 1 "${BOLD}installed ${TICK}${OFF}" "restart Claude Code, then try: suggest diagrams for this repo"
    printf '\033[2B'
  else
    echo "AgenTeX installed. Restart Claude Code, then try: suggest diagrams for this repo"
  fi
else
  (( animate )) && { draw 7 1 "install failed" ""; printf '\033[2B'; }
  echo
  cat "$log" >&2
fi
rm -f "$log"
exit "$status"
