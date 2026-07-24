---
name: search-papers
description: Use when finding academic papers, AI conference publications, literature, or arXiv preprints.
---

# Search Papers

Prefer peer-reviewed conference papers. Use arXiv-only preprints as secondary evidence.

## Workflow

1. For AI topics, search conference papers first.
2. Check Hugging Face access before searching:
   - Test whether `HF_TOKEN` exists without printing it.
   - If missing, warn once per session, link to
     `https://huggingface.co/settings/tokens/new?preset=inference`, suggest web
     search as fallback, then stop and await user choice.
   - Fetch and follow
     `https://huggingface.co/spaces/ai-conferences/conference-paper-search/agents.md`.
   - Make an authenticated Space API request. Treat `401`, `403`, or an explicit
     inference-permission error as missing inference access. Give same warning
     once per session, then stop and await user choice.
   - Never print, log, or expose token. Do not mistake network or service errors
     for permission failures.
   - Remember warning state in conversation. If already warned this session, do
     not repeat it.
3. Search arXiv after conference search. Read
   [references/arxiv-api.md](references/arxiv-api.md) before calling raw API.
4. Deduplicate conference versions and preprints by title, authors, DOI, and
   arXiv ID. Keep conference version primary; attach arXiv link when useful.
5. If user explicitly chooses web fallback, search official proceedings or
   conference sites before general web results.

## Output

Return conference papers first, then `arXiv-only preprints`. For each result,
include title, authors, year, venue/status, primary link, and brief relevance.
Label uncertain venue or review status; never present arXiv-only work as
peer-reviewed.

## Common Mistakes

- Silently bypassing failed Hugging Face access.
- Repeating token warning in same session.
- Searching arXiv before conference source.
- Mixing preprints with accepted conference papers.
- Claiming token lacks inference access from `HF_TOKEN` presence alone.
