---
name: latex-algorithms
description: "Turn source code into LaTeX pseudocode (algorithmicx, algorithm2e) or code listings (minted, listings) pulled from the repo. Use for algorithm boxes, code in papers or slides, and listings/minted errors."
---

# Code → Pseudocode & Listings

First decide which the reader needs:

- **Pseudocode**: communicates the *idea*. Language-agnostic, mathematical, omits plumbing. Default for papers.
- **Listing**: shows *actual code*. For tutorials, software papers, appendices, reproducibility sections, slides.

## Pseudocode workflow

1. **Read the function and everything it calls.** Identify inputs, outputs, the core loop(s), and the key update equations.
2. **Strip the plumbing**: logging, device moves (`.to(device)`), checkpointing, argument parsing, type conversions, batching boilerplate. Keep anything that changes the result (gradient clipping, early stopping, warm-up, seeds when relevant).
3. **Lift to mathematics**: `w -= lr * grad` → `\State $\vw \gets \vw - \eta \nabla_{\vw}\loss$`. Use the *same symbols* as the paper's equations and `macros.tex` (see `latex-math`).
4. **Keep it short**: aim for ≤ 20 lines. Factor sub-procedures into separate `\Function` blocks or separate algorithms.
5. **Cross-check**: every hyperparameter in `\Require` must exist in the code (and vice versa for anything that matters). Flag discrepancies via `latex-consistency`.

### algorithmicx (`algorithm` + `algpseudocode`), the default

```latex
\begin{algorithm}[t]
  \caption{Mini-batch SGD with gradient clipping}\label{alg:sgd}
  \begin{algorithmic}[1]                   % [1] = number every line
    \Require dataset $\data$, step size $\eta$, clip norm $c$, epochs $E$
    \Ensure trained parameters $\vtheta$
    \State initialise $\vtheta$
    \For{$e = 1$ \textbf{to} $E$}
      \ForAll{minibatch $\mathcal{B} \subset \data$}
        \State $\bm{g} \gets \nabla_{\vtheta} \loss_{\mathcal{B}}(\vtheta)$
        \If{$\norm{\bm{g}} > c$}
          \State $\bm{g} \gets c \, \bm{g} / \norm{\bm{g}}$  \Comment{clip}
        \EndIf
        \State $\vtheta \gets \vtheta - \eta \bm{g}$
      \EndFor
    \EndFor
    \State \Return $\vtheta$
  \end{algorithmic}
\end{algorithm}
```

Notes: `\Require/\Ensure` can be renamed to Input/Output with
`\algrenewcommand\algorithmicrequire{\textbf{Input:}}`. Don't load `algorithmic` (old) alongside `algpseudocode`. If the venue template already loads `algorithm2e`, use its syntax (`\KwIn`, `\For{...}{...}`, `\;` line endings) instead: the two packages conflict.

## Listings workflow

**`minted`** (best highlighting; needs Pygments and `-shell-escape`):

```latex
\usepackage{minted}
\begin{listing}[t]
\begin{minted}[fontsize=\small, linenos, breaklines, frame=lines]{python}
def softmax(z):
    z = z - z.max(axis=-1, keepdims=True)  # numerical stability
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)
\end{minted}
\caption{Numerically stable softmax.}\label{lst:softmax}
\end{listing}
```

Build: `latexmk -pdf -shell-escape main.tex`. On Overleaf it works out of the box. Many arXiv/journal pipelines **do not** allow shell-escape; use `listings` there, or minted's `frozencache` option.

**`listings`** (no external dependencies):

```latex
\usepackage{listings, xcolor}
\lstset{basicstyle=\ttfamily\small, numbers=left, numberstyle=\tiny,
        breaklines=true, frame=tb, keywordstyle=\bfseries, columns=fullflexible,
        upquote=true, showstringspaces=false}
\begin{lstlisting}[language=Python, caption={Numerically stable softmax.}, label={lst:softmax}]
...
\end{lstlisting}
```

- Include code from the repo file rather than pasting, so it never goes stale: `\inputminted[firstline=10,lastline=24]{python}{../src/model.py}` or `\lstinputlisting[firstline=10,lastline=24]{../src/model.py}`. Note line ranges drift when the file changes; re-check them.
- Unicode in code (e.g. `θ`, `→`) breaks `listings` under pdfLaTeX; use `literate=` mappings or LuaLaTeX + minted.
- Inside Beamer frames with code: `\begin{frame}[fragile]`.

## Checklist

- [ ] Symbols match the paper's equations and notation table
- [ ] Every input/hyperparameter exists in the code with the same meaning
- [ ] Algorithm is referenced in the text (`\cref{alg:...}`)
- [ ] Listings pulled from files where possible; line ranges correct
- [ ] Build flags (`-shell-escape`) documented if minted is used
