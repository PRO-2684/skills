---
name: search-papers
description: Use when finding academic papers, AI conference publications, literature, or arXiv preprints.
---

# Search Papers

Prefer peer-reviewed conference papers when relevant. Clearly label arXiv-only preprints.

## Suggested Routing

Choose the smallest useful path from apparent user intent; adapt when the request needs more:

- Exact arXiv ID/URL or explicit preprint request: usually use arXiv only.
- Explicit conference, accepted, or peer-reviewed request: usually use conference search only.
- Explicit request for both, or generic paper search with no source preference: use both; conference first.

An arXiv identifier alone does not imply conference search. If the user explicitly asks whether that paper was accepted or has a peer-reviewed version, use an exact-title conference lookup rather than a full topic search.

## Conference Papers

1. Test whether `HF_TOKEN` exists without printing it. If missing, warn once per session, link to `https://huggingface.co/settings/tokens/new?preset=inference`, suggest web search as fallback, then stop and await user choice.
2. Run `python3 scripts/search_conference.py --help`, then use the script. Do not read its source or full contract during normal use.
3. If the script behaves unexpectedly or reports schema mismatch, read the [local contract](references/conference-paper-search.md). Inspect script source only when debugging the wrapper. If still unresolved, fetch the live contract once:
    ```bash
    curl -fsSL 'https://huggingface.co/spaces/ai-conferences/conference-paper-search/agents.md'
    ```
    Do not add `raw/main`, `resolve/main`, or `blob/main`; this is an app route, not a repo file.
4. Treat `401`, `403`, or an explicit inference-permission error as missing inference access. Give the same warning once per session, then stop and await user choice. Never expose the token or mistake service errors for permission failures.
5. If the user chooses web fallback, search official proceedings or conference sites before general web results.

## arXiv Preprints

Run `python3 scripts/search_arxiv.py --help`, then use the script. Read [arxiv-api.md](references/arxiv-api.md) only if the script behaves unexpectedly.

## Combined Search

Run conference search, then arXiv. Deduplicate by title, authors, DOI, and arXiv ID. Keep the conference version primary; attach the arXiv link when useful.

## Output

For combined results, return conference papers first, then `arXiv-only preprints`. For each result, include title, authors, year, venue/status, primary link, and brief relevance. Label uncertain venue or review status; never present arXiv-only work as peer-reviewed.

## Common Mistakes

- Silently bypassing failed Hugging Face access.
- Repeating token warning in same session.
- Searching arXiv first during a combined search.
- Mixing preprints with accepted conference papers.
- Claiming token lacks inference access from `HF_TOKEN` presence alone.
- Using `search_papers` as skill directory. The correct one is `search-papers`.
