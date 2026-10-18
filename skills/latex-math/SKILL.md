---
name: latex-math
description: "Turn code into equations and keep notation consistent: symbol maps, shape and index checks against the implementation, amsmath typesetting, notation tables and macro files. Use when writing or fixing equations or auditing symbols."
---

# Code → Mathematics & Notation

Goal: equations that are **faithful to the code**, **typographically correct**, and use **one notation system** for the whole document.

## Workflow: code to equation

1. **Read the code first, all of it.** Follow the call chain until you know every operation actually applied: reductions (`mean` vs `sum`), axes, broadcasting, `eps` terms, clipping, in-place updates, default arguments.
2. **Write a symbol map before any LaTeX**:

   | Code | Symbol | Meaning | Shape / domain |
   |---|---|---|---|
   | `X` | $\mathbf{X}$ | input batch | $\mathbb{R}^{N \times d}$ |
   | `lr` | $\eta$ | learning rate | $\mathbb{R}_{>0}$ |
   | `logits.softmax(-1)` | $\operatorname{softmax}(\mathbf{z})$ | class probabilities | $\Delta^{K-1}$ |

   Reuse symbols already defined in the document's `macros.tex` / notation table. Never introduce a second symbol for an existing quantity.
3. **Derive the equation**, then **check it against the code line by line**. Shapes on both sides must agree. Indices must be bound (every free index appears on both sides or under a sum/product).
4. **Flag mismatches, don't paper over them.** If the paper's existing equation differs from the code (e.g. paper says sum, code takes mean; paper says $\log$, code uses `log1p`; missing $\epsilon$ in a denominator), report it explicitly and ask which is intended. See `latex-consistency`.
5. **Typeset** using the rules below, then add new symbols to the macros file and notation table.

## Common translations

| Code idiom | Mathematics |
|---|---|
| `x.mean()` over N items | $\frac{1}{N}\sum_{i=1}^{N} x_i$ |
| `A @ B` | $\mathbf{A}\mathbf{B}$ |
| `A * B` (elementwise) | $\mathbf{A} \odot \mathbf{B}$ |
| `A.T` | $\mathbf{A}^{\top}$ (use `^\top`, never `^T`) |
| `np.linalg.norm(x)` | $\lVert \mathbf{x} \rVert_2$ |
| `x.sum(axis=1)` | $\sum_{j} x_{ij}$ (state which axis is $j$) |
| `torch.logsumexp(z, -1)` | $\log \sum_{k} \exp(z_k)$ |
| `F.cross_entropy(z, y)` | $-\frac{1}{N}\sum_i \log \frac{\exp(z_{i,y_i})}{\sum_k \exp(z_{i,k})}$ |
| `x.clamp(min=0)` | $\max(0, x)$ or $(x)_+$ |
| `for t in range(T): x = f(x)` | $x_{t+1} = f(x_t),\; t = 0,\dots,T-1$ |
| `np.random.normal(mu, s)` | $X \sim \mathcal{N}(\mu, \sigma^2)$ (code takes **std**, notation takes **variance**) |
| `scipy ... scale=` | check parametrisation: rate vs scale, std vs var |
| 0-indexed loops | decide 0- or 1-indexing once and state it |

## Typesetting rules

- Environments: `equation` (one line, numbered), `align` (multi-line aligned at `&`), `gather` (multi-line centred), `multline` (one long equation), `cases` for piecewise. Never `eqnarray`. Never `$$ … $$`.
- Number only equations that are referenced; use `\nonumber` or `\notag` (or starred env) for the rest.
- Upright for operators and named functions: `\exp`, `\log`, `\max`, `\operatorname{softmax}` or `\DeclareMathOperator`. Upright `\mathrm{d}` for differentials is common in physics/applied maths; follow the field's convention, consistently.
- Multi-letter variable names are never italic runs: `$\mathit{loss}$` or better a proper symbol; `$loss$` reads as $l \cdot o \cdot s \cdot s$.
- Vectors bold lowercase (`\bm{x}`), matrices bold uppercase (`\bm{W}`), sets calligraphic (`\mathcal{D}`), spaces blackboard (`\mathbb{R}`), random variables uppercase, estimates hatted (`\hat{\theta}`).
- Delimiters: `\left( … \right)` or better `\bigl( … \bigr)`; prefer `mathtools`' `\DeclarePairedDelimiter` for norms and absolute values.
- Punctuate displayed equations as part of the sentence (comma or full stop inside the display).
- Define every symbol in the text at or before first use: "where $\eta > 0$ is the learning rate".
- Units via `siunitx`, never `$5 ms$`.

## Notation table

For any paper with more than ~10 symbols, maintain a notation table (often in the appendix or after the problem setup):

```latex
\begin{table}[t]
  \centering
  \caption{Notation.}\label{tab:notation}
  \begin{tabular}{@{}ll@{}}
    \toprule
    Symbol & Meaning \\
    \midrule
    $\data = \{(\vx_i, y_i)\}_{i=1}^{N}$ & training set of $N$ examples \\
    $\vtheta \in \R^{p}$ & model parameters \\
    $\eta$ & learning rate \\
    \bottomrule
  \end{tabular}
\end{table}
```

## Notation audit (when asked to check a document)

Start from the `macros` line of `texmap.py` (latex-project skill), then `grep -rn` each symbol, rather than reading every file. Report:
- The same quantity with two symbols (e.g. $n$ and $N$ for sample size).
- The same symbol for two quantities (e.g. $\alpha$ = learning rate in §3 and significance level in §5).
- Symbols used before definition, or never defined.
- Inconsistent styling ($x$ vs $\mathbf{x}$ for the same vector; `^T` vs `^\top`).
- Macros in `macros.tex` that are never used, and raw symbols that bypass an existing macro.

Report as a table: symbol, locations (file:line), issue, suggested fix. Apply fixes only after confirmation if they change meaning.
