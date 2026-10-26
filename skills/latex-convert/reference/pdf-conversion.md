# PDF-to-LaTeX Conversion Pipeline

## Overview

Convert PDFs of any type (handwritten notes, printed reports, legal contracts, math lectures) to LaTeX using a scaling strategy based on document size, with document-type profiles for accurate conversion.

## Step 1: Determine Document Type

Scan a few representative pages and select the matching conversion profile:

| Content Type | Profile | Key Indicators |
|---|---|---|
| Math / science | `profiles/math-notes.md` | Equations, theorems, proofs, Greek symbols, integrals |
| Business | `profiles/business-document.md` | Data tables, bullet points, meeting notes, financial figures |
| Legal | `profiles/legal-document.md` | Numbered clauses, "WHEREAS", signature blocks, articles/sections |
| General | `profiles/general-notes.md` | Informal notes, mixed content, journals, letters |

Each profile provides a suggested preamble, structural patterns to recognize, worker hints, and pitfalls.

## Step 2: Prepare Images

```bash
python3 <skill>/../latex-pdf/scripts/pdftool.py preview input.pdf --pages all --max-px 2000 -o tmp/pages
```

This writes `input-p001.png`, `input-p002.png`, … with the longest side at 2000 px (vision-model limits).

## Step 3: Apply Scaling Strategy

In the original project's test (15 pages converted at batch sizes 3–15), 7 pages per batch gave the fewest
errors and the best structure recognition. Past ~10 pages a single pass loses track of open environments.

| PDF size | Strategy |
|---|---|
| 1–10 pages | one pass |
| 11–20 pages | two halves |
| 21+ pages | batches of 7 pages, `ceil(N/7)` batches; the last takes the remainder |

Batches are independent, so they can run as parallel agents when the user agrees; otherwise run them in order.

## Step 4: Create Shared Preamble

Before launching workers, one agent scans 3-5 representative pages to build the preamble:

1. Read the selected profile's suggested preamble as a starting point
2. **For math-notes profile**: Default to **beautiful mode** -- copy the preamble from `latex-documents/templates/lecture-notes.tex` (everything before `\begin{document}`). This gives you tcolorbox theorem environments, TikZ graph styles, Palatino font, and microtype. Only use plain mode if the user explicitly requests it.
3. Scan pages to identify additional packages or custom commands needed beyond the profile's base
4. Write `tmp/preamble.tex` with everything from `\documentclass` through the last `\newcommand`
5. Do NOT include `\begin{document}` -- that goes in the assembly step

## Step 5: Convert Each Batch

Each batch writes body-only LaTeX to `tmp/batch_SSS_EEE.tex` (e.g. `tmp/batch_001_007.tex`). When batches run
as parallel agents, give each one this prompt; when you convert them yourself, follow the same rules.

**Worker prompt template**:
```
Convert pages [START]-[END] of the document to LaTeX body content.

Read the preamble at [path/preamble.tex] for available commands and environments.
Read the conversion profile at [path/profile.md] for structural patterns and hints.
Read page images: [path/input-pXXX.png] through [path/input-pYYY.png]

CONTEXT: You are continuing from [section/content context from previous batch].
The document is a [type: math notes / business report / legal contract / general notes].

OUTPUT: Write ONLY to [path/batch_XXX_YYY.tex]

RULES:
- Output ONLY body content (no \documentclass, \usepackage, \begin{document})
- Use custom commands from preamble
- Follow the structural patterns described in the profile
- Be faithful to the original content
- Close ALL open environments before the end of your output
- Be CONCISE -- write the LaTeX, nothing else

CRITICAL LATEX CONSTRAINTS (violation = compilation failure):

1. UNDEFINED COMMANDS -- use only commands defined in the preamble or a loaded package:
   - \sout and \circled exist only if the preamble defines them (beautiful mode does; see 5)
   - no \pentagon, \hexagon or other invented symbols (draw shapes with TikZ instead)
   - any command you are not certain exists: check the preamble first.

2. TIKZ SYNTAX:
   - EVERY \node, \draw, \path command MUST end with semicolon ;
   - EVERY \node MUST have label text in braces: \node[vertex] (v1) at (0,0) {$v_1$};
   - Empty labels still need braces: \node[vertex] (v1) at (0,0) {};
   - ALL TikZ commands MUST be inside \begin{tikzpicture}...\end{tikzpicture}
   - Use POLAR coordinates for circular layouts: (60:1.5cm) not ({cos(60)},{sin(60)})
   - edge/dedge/hedge are EDGE styles: use \draw[edge], NEVER \node[edge]

3. ENVIRONMENT NESTING:
   - Do NOT use \begin{table}[H] or \begin{figure}[H] inside tcolorbox environments (theorem, example, definition, etc.)
   - Use \begin{tabular} directly inside boxes (no table wrapper needed)
   - Do NOT put \begin{tabular} inside align* or equation* environments
   - \begin{proof} inside \begin{example} is allowed, but you MUST close proof BEFORE closing example

4. ENUMERATE/ITEMIZE:
   - Use \begin{enumerate} without inline label options (labels are pre-configured in preamble)
   - First level: (i), (ii), (iii); second level: (a), (b), (c)
   - If you need a specific label, use: \begin{enumerate}[label=(\alph*)]

5. COMMANDS AVAILABLE IN PREAMBLE (beautiful mode):
   - Number sets: \R, \N, \Z, \Q, \C
   - Graph theory: \V, \E, \deg, \diam, \dist, \Aut, \chr
   - Delimiters: \abs{}, \norm{}, \floor{}, \ceil{}
   - Circled numbers: \circled{1}, \circled{2}
   - Strikethrough: \sout{text} (ulem loaded), \cancel{expr} (in math)
```

## Step 6: Validate Batch Outputs

Before assembling, run the validation script on each batch file to catch errors early:

```bash
python3 <skill>/scripts/check_fragments.py tmp/batch_*.tex --preamble tmp/preamble.tex
```

This checks for:
- Balanced `\begin{}`/`\end{}` environments
- Undefined commands not present in preamble
- `\begin{table}[H]` or `\begin{figure}[H]` inside tcolorbox environments
- TikZ commands (`\node`, `\draw`) outside `\begin{tikzpicture}`
- Missing node labels (TikZ `\node` without `{};`)

Fix any reported errors in the batch files BEFORE assembling.

## Step 7: Assemble and Compile

After all workers complete and validation passes:

```bash
# 1. Build the full document
cat tmp/preamble.tex > outputs/document.tex
echo '' >> outputs/document.tex
echo '\begin{document}' >> outputs/document.tex
echo '\maketitle' >> outputs/document.tex       # if title/author set in preamble
echo '\tableofcontents' >> outputs/document.tex  # if document has sections
echo '\newpage' >> outputs/document.tex
for f in $(ls tmp/batch_*.tex | sort); do
  echo "" >> outputs/document.tex
  echo "% === $(basename $f) ===" >> outputs/document.tex
  cat "$f" >> outputs/document.tex
done
echo '' >> outputs/document.tex
echo '\end{document}' >> outputs/document.tex

# 2. Compile
python3 <skill>/../latex-debug/scripts/build.py outputs/document.tex --preview outputs --pages all
```

### If compilation fails:

1. Read the digest `build.py` prints (never the whole `.log`)
2. Common fixes:
   - **Mismatched `\begin`/`\end`**: Find and close orphaned environments
   - **Misplaced `&`**: Ensure `&` only appears inside tabular/align environments
   - **Undefined commands**: Add missing `\newcommand` to preamble or remove the command usage
   - **Package conflicts**: Remove `hyperref` if `\set@color` errors appear
   - **Missing `$`**: Find unclosed inline math
   - **`\newcommand` conflict**: Use `\renewcommand` if overriding a built-in command (e.g., `\deg`)
   - **CT@row@color errors**: Caused by `\begin{tabular}` inside math environments -- move tabular outside
   - **"Not in outer par mode"**: Caused by `\begin{table}[H]` inside tcolorbox -- remove the `table` wrapper
   - **TikZ "Undefined control sequence"**: TikZ commands outside `\begin{tikzpicture}` -- find and wrap them
3. Fix errors in the `.tex` file and recompile

## Common Pitfalls (All Document Types)

1. **Do NOT use `sed` to clean control characters**. Regex `[^[:print:][:space:]]` strips `\b`, `\t`, `\n`, `\e` which destroys `\begin`, `\tableofcontents`, `\newpage`, `\end`.

2. **Do NOT use `hyperref` in converted documents**. Causes `\set@color` / `\@pdfcolorstack` errors with theorem environments and colored text.

3. **Always compile from a clean directory** if the compile script has issues with stale aux files.

4. **Workers must be CONCISE**. Agents that add verbose comments or explanations waste context window and may overflow.

5. **Close environments at batch boundaries**. If a proof/theorem/table spans the end of a batch, close it and add a comment: `% continues in next batch`.

6. **Select the correct profile**. A math profile on a business document will produce unnecessary theorem environments. A business profile on math notes will miss structural patterns.
