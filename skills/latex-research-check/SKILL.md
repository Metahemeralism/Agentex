---
name: latex-research-check
description: "Find the published work closest to your project and assess novelty. Searches OpenAlex, arXiv and Semantic Scholar, ranks by similarity to your abstract, and reports overlaps, differences and what to cite. Use for \"has this been done\", related work, novelty or prior-art checks."
---

# Research Check: Closest Prior Work

Goal: know the paper a reviewer will compare you to *before* they do.

## Workflow

1. **Reference text.** Use the paper's title and abstract (`--from-tex`). If there is no paper yet, write 3–4 sentences from the code/README (problem, method, data, main claim) and pass it with `--text`.
2. **Queries: 3–6 different phrasings**, because one query misses things:
   problem in the field's vocabulary · method name + task · synonyms of the key technique (e.g. *GNN / message passing / graph network*) · benchmark or dataset + task · title of a paper you suspect is closest.
3. **Search:**
   ```bash
   python3 scripts/related.py --from-tex paper/main.tex -q "..." -q "..." -n 15
   ```
   If academic search tools are connected (e.g. alphaXiv, Semantic Scholar, Consensus, Exa, PubMed for biomedicine), run 1–2 semantic searches there too and merge.
4. **Triage cheaply.** Re-run with `--abstracts` for the top ~8 only. Open full text (arXiv HTML/PDF) only for the 1–3 papers that look like direct overlap, and read just their method/experiment sections.
5. **Snowball** from the closest 1–2 papers: newer work that cites them is the most likely overlap.
   - OpenAlex: `https://api.openalex.org/works?filter=cites:<W-id>&sort=publication_date:desc`
   - Semantic Scholar: `https://api.semanticscholar.org/graph/v1/paper/arXiv:<id>/citations?fields=title,year,externalIds`
   - Latest arXiv: `related.py` hits are relevance-sorted; for fast-moving fields also check `sortBy=submittedDate`.
6. **Report** (write to `review/related-work.md`; reply with the table and the verdict only):

   | # | Paper (year, link) | Same problem? | Same method? | Same data? | Key difference |
   |---|---|---|---|---|---|

   - **Novelty risk:** *High* (same problem and method), *Medium* (one of the two), *Low*. Explain in 2–3 sentences. Never claim novelty with certainty, because search coverage is partial.
   - **Must-cite list** with DOI/arXiv IDs. Hand these to `latex-references` for verified BibTeX.
   - **Positioning:** 2–4 sentences for the related-work section. Every claim about another paper must be backed by text you actually read.

## Rules

- Never invent a paper, author, venue or result. Every row must have an identifier that came from tool output.
- Scores are TF-IDF cosine values, comparable only within one run. Use them to order, not to judge.
- Distinguish preprints from peer-reviewed work, and note when a "closest" paper is concurrent (within ~3 months).
- Set `S2_API_KEY` if Semantic Scholar rate-limits (HTTP 429). The script continues with the other sources either way.
