// Pure frame logic for the AgenTeX band: no engine calls, so it is unit-testable.
// The motif is TeX's lowered E: it drops into place on first run and bobs while work runs.

export const BLUE = '#56B4E9' // "Agen", the logo's Okabe-Ito sky blue
export const WELCOME_FRAMES = 48 // x 90 ms = about 4.3 s
const SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

export type Seg = { text: string; color?: string; bold?: boolean; dim?: boolean }
export type Row = Seg[]

// Which shell commands are AgenTeX work, and what to call them while they run. First match wins.
// Generic script names (claims.py, repro.py, issues.py) count only from an AgenTeX skill's scripts folder.
const LABELS: [RegExp, string][] = [
  [/cite_claims\.py/, 'checking cited claims against their sources'],
  [/cite_verify\.py/, 'verifying citations'],
  [/latex-[\w-]+\/scripts\/preflight\.py/, 'checking submission rules'],
  [/disclosure\.py/, 'drafting the LLM-use disclosure'],
  [/settings_audit\.py/, 'looking for undisclosed hyperparameters'],
  [/latex-[\w-]+\/scripts\/claims\.py/, 'checking claims against the code'],
  [/latex-[\w-]+\/scripts\/repro\.py\s+smoke\b/, 'reproducing results in a clean checkout'],
  [/latex-[\w-]+\/scripts\/repro\.py/, 'building the reproduction table'],
  [/figcheck\.py/, 'checking figures'],
  [/mplstyle\.py/, 'styling plots for print'],
  [/html_check\.py/, 'checking the arXiv HTML'],
  [/latex-[\w-]+\/scripts\/issues\.py\s+guard\b/, 'guarding edits'],
  [/latex-[\w-]+\/scripts\/issues\.py/, 'tracking review issues'],
  [/rebuttal\.py/, 'drafting the rebuttal'],
  [/results\.py\s+(audit|stale)\b/, 'checking numbers against the code'],
  [/results\.py\s+make\b/, 'rebuilding stale figures'],
  [/results\.py/, 'syncing results'],
  [/arxiv_pack\.py/, 'packaging for arXiv'],
  [/tikzcheck\.sh/, 'rendering figure'],
  [/diagram_ideas\.py/, 'reading your code for diagram ideas'],
  [/related\.py/, 'searching prior work'],
  [/overlap\.py/, 'screening for overlap'],
  [/check_refs\.py/, 'checking references'],
  [/texmap\.py/, 'mapping the project'],
  [/texstats\.py/, 'counting words'],
  [/latex-debug\/scripts\/build\.py|build\.py\b.*\.tex\b/, 'typesetting'],
  [/pdftool\.py/, 'working on the PDF'],
  [/mail_merge\.py/, 'merging documents'],
  [/check_fragments\.py/, 'checking converted pages'],
  [/\blatexdiff/, 'marking changes between versions'],
  [/\bpandoc\b/, 'converting the document'],
  [/\b(latexmk|tectonic|pdflatex|lualatex|xelatex)\b/, 'typesetting'],
]

export function labelFor(command: string): string | null {
  for (const [re, label] of LABELS) if (re.test(command)) return label
  return null
}

/** "AgenT X" over "     E": `shown` letters of AgenTEX typed so far; E up or dropped. */
export function logo(shown: number, eDown: boolean): [Row, Row] {
  const has = (i: number) => shown > i
  const e = has(5) ? 'E' : ' '
  return [
    [
      { text: 'Agen'.slice(0, Math.min(shown, 4)).padEnd(4), color: BLUE, bold: true },
      { text: (has(4) ? 'T' : ' ') + (eDown ? ' ' : e) + (has(6) ? 'X' : ' '), bold: true },
    ],
    [{ text: '     ' }, { text: eDown ? e : ' ', bold: true }, { text: ' ' }],
  ]
}

export function welcomeRows(n: number): Row[] {
  const [top, bottom] = logo(Math.min(n + 1, 7), n >= 9) // type it out, then drop the E
  if (n < 11) return [top, bottom]
  return [
    [...top, { text: '  installed ✓', bold: true }],
    [...bottom, { text: '  cite guard and compile loop on · /agentex shows paper health', dim: true }],
  ]
}

export function activityRows(frame: number, label: string): Row[] {
  const [top, bottom] = logo(7, Math.floor(frame / 5) % 2 === 0) // E bobs every 0.5 s
  return [
    [...top, { text: `  ${SPIN[frame % SPIN.length]} ${label}`, color: BLUE }, { text: `  ${Math.floor(frame / 10)}s`, dim: true }],
    bottom,
  ]
}
