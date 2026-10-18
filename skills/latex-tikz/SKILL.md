---
name: latex-tikz
description: "Suggest and draw publication-quality TikZ/PGFPlots figures from a project's code: architectures, pipelines, flowcharts, graphical models, state machines, matrices, plots. Use for any diagram request, or when the user wants ideas for which figures to make."
---

# TikZ Diagrams

Goal: figures that are correct to the code, compile first time, match the paper's typography, print in greyscale, and cost few tokens to produce and revise.

## Suggest mode: read the code, offer diagram choices

Use this when the user asks for diagram ideas, asks for "a figure" without saying which, or starts a paper from a code repo.

1. **Scan, don't read everything:**
   ```bash
   python3 <skill>/scripts/diagram_ideas.py <repo>
   ```
   It parses the Python files and notebooks (no execution) and prints numbered ideas: **high-level** ones (end-to-end pipeline, artefact flow between scripts, module architecture, object composition, model overview) and **component** ones (a network's layers in run order, training loop, iterative solver, time-stepping scheme, graphical model, einsum shapes, state enum, class hierarchy, results plot). Each comes with its pattern and `file:line` evidence.
2. **Check and complete the list.** Read only the cited lines for the top ideas, drop wrong ones, and add what static analysis can't see. Always consider:
   - a *method overview / teaser* figure (the paper's Figure 1)
   - a *problem setup* figure
   - for non-Python code, or a sparse result, ideas from the README and entry points.
3. **Let the user choose one or many.** If the host has a multiple-choice question tool (Claude Code: `AskUserQuestion` with `multiSelect: true`), ask two questions in one call, **"High-level diagrams"** and **"Component diagrams"**, each with the 2–4 best ideas:
   - label: ≤ 5 words, e.g. "End-to-end pipeline"
   - description: what it shows, its source and a tiny flow sketch, e.g. "`train.py`: load_data → ResNet → train → evaluate"
   - name any extra ideas in your message so the user can request them via "Other".

   Without such a tool, print a numbered list (`H1…`, `C1…`) and ask for numbers, e.g. "H1, C2, C3".
4. **Build each chosen figure** with the workflow below, one file per figure (`paper/figures/<name>.tex`), running `tikzcheck.sh` on each. Finish with a table: figure → file → source code it depicts → preview checked.

## Workflow

1. **Restate the structure** in 2–4 lines: nodes, edges, grouping, flow direction. If drawing from code (`nn.Module`, pipeline, state machine), derive it *from the code* (layer order, tensor shapes, skips). Don't invent components.
2. **Start from the closest pattern; don't write from scratch.** Copy with `cp` (no tokens), then `Edit` only what differs:

   | Pattern (`assets/`) | Use for |
   |---|---|
   | `pattern-pipeline.tex` | block/system diagrams, data pipelines, feedback loops |
   | `pattern-flowchart.tex` | algorithms and decisions (top-to-bottom) |
   | `pattern-cnn.tex` | layered networks with shapes on one baseline, residuals |
   | `pattern-transformer.tex` | stacked blocks with residual paths, ×N grouping |
   | `pattern-mlp.tex` | fully connected neurons from size lists |
   | `pattern-pgm.tex` | Bayesian networks with plates |
   | `pattern-tree.tex` | decision trees, hierarchies |
   | `pattern-fsm.tex` | automata and Markov chains |
   | `pattern-matrix.tex` | matrices with delimiters and dimension braces |
   | `pattern-geometry.tex` | vectors, projections, angle marks |
   | `pattern-plot.tex` | pgfplots line plots with error bands |
   | `pattern-commutative.tex` | tikz-cd diagrams |

   ```bash
   cp <skill>/assets/agentex-tikz.sty paper/figures/   # once per project
   cp <skill>/assets/pattern-pipeline.tex paper/figures/pipeline.tex
   ```
3. **Use the shared styles** in `agentex-tikz.sty` (`\begin{tikzpicture}[ax]`): `box layer op term decision io store var obs param plate neuron flow skip aux dim note group hi hi2`. Define a local style only for something genuinely new. Don't put `[ax]` on pgfplots pictures, because its node font overrides tick and legend fonts.
4. **Need syntax you're unsure of? Search the manual offline** instead of guessing or fetching web pages:
   ```bash
   python3 <skill>/scripts/tikzref.py brace decoration       # top 3 official examples
   python3 <skill>/scripts/tikzref.py --keys chains join     # option signatures
   python3 <skill>/scripts/tikzref.py "matrix of math nodes" -l matrix -n 2
   ```
5. **Compile and look:**
   ```bash
   bash <skill>/scripts/tikzcheck.sh paper/figures/pipeline.tex
   ```
   It prints `OK | warnings | preview path`, or the first errors only. Read the **preview PNG** (100 dpi, a few hundred tokens), never the PDF or the log. Fix overlaps, then re-check.
6. **Embed:** `\input{figures/pipeline.tex}` content inside a `figure` (fonts then match the paper automatically), or `\includegraphics` the standalone PDF after loading the paper's font package in it too. `\caption` first, then `\label{fig:…}`.

## Token discipline

- Copy and edit; never regenerate a whole figure to change a label. One `Edit` per change.
- Don't echo figure code in chat after writing the file. Reply with the path, a one-line description and the preview check.
- Prefer compact idioms (they cut output 30–60 %):
  - `\foreach \a/\b in {x/y, y/z} \draw[flow] (\a) -- (\b);` instead of one `\draw` per edge
  - `\foreach … [remember=\i as \prev (initially 0)]` for chains of layers
  - `matrix of math nodes` for grids; `\graph {a -> b -> {c, d}};` (`graphs` library) for quick DAGs
  - `fit` + `on background layer` for group boxes; `|-` / `-|` for orthogonal routing
  - `pic` for repeated sub-figures; `label=` instead of extra label nodes.

## Academic style rules

- Greyscale first. Accents (`hi`, `hi2`, `axblue` …, Okabe–Ito colour-blind-safe) are opt-in and always paired with a second cue: dash pattern, shape, label or line weight.
- `semithick` lines; `arrows.meta` tips only (set once by `ax`); solid = main flow, dashed = skip/optional, dotted = auxiliary.
- All maths in math mode, using the paper's macros (`\bm{x}`, `\mathbf{W}^{(l)}`). Labels `\small`, annotations `\footnotesize`/`\scriptsize`.
- Relative placement (`positioning`) and shared sizes; hardcoded coordinates only for genuinely geometric figures (built with `calc`).
- One flow direction per diagram; label every decision branch, input and output.
- No shadows, gradients or glow. Vector only: no raster images inside figures.

## Debugging

| Symptom | Fix |
|---|---|
| `I do not know the key …` | missing `\usetikzlibrary{…}` (check with `tikzref.py <key>`) |
| `No shape named …` | edge drawn before the node exists, or a typo |
| Overlapping labels | increase `node distance`; put annotations on a shared baseline (`(n |- base)`) |
| `fit` box too tight | list every node; raise `inner sep` |
| Content clipped | raise standalone `border` |
| `Dimension too large` (plots) | rescale data, `compat=1.18`, or the `fpu` library |
