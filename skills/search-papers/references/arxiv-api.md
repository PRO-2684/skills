# arXiv API

Use raw arXiv API for preprints. No authentication required.

## Query endpoint

Send `GET https://export.arxiv.org/api/query`.

| Parameter      | Use                                                         |
| -------------- | ----------------------------------------------------------- |
| `search_query` | Boolean query with `ti`, `au`, `abs`, `cat`, or `id` fields |
| `id_list`      | Comma-separated arXiv IDs                                   |
| `start`        | Pagination offset                                           |
| `max_results`  | Result count                                                |
| `sortBy`       | `relevance`, `lastUpdatedDate`, or `submittedDate`          |
| `sortOrder`    | `ascending` or `descending`                                 |

Example:

```bash
curl -A "paper-search/1.0 (contact: user@example.com)" \
  "https://export.arxiv.org/api/query?search_query=%28ti%3Atransformer%20OR%20abs%3Atransformer%29%20AND%20cat%3Acs.CL&start=0&max_results=20&sortBy=relevance&sortOrder=descending"
```

URL-encode query values. Parse Atom `<entry>` fields: `id`, `title`, `summary`, `author`, `published`, `updated`, `link`, `arxiv:primary_category`, DOI, and journal reference when present.

## Query patterns

- Known papers: use `id_list=2301.07041,2302.13971`.
- Recent category work: combine `cat:` with `submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM]`; sort by `submittedDate`.
- Topic search: combine title and abstract terms, then constrain with `cat:`.
- Page large searches with `start`; do not request entire corpus.

Wait at least 3 seconds between repeated API calls. On `503`, back off and retry. Use bulk data access for bulk harvesting.

Treat all arXiv records as preprints unless journal reference, DOI, or a separate official venue source proves publication. Verify conference status outside arXiv.

Sources:

- https://info.arxiv.org/help/api/
- https://info.arxiv.org/help/api/user-manual.html
- https://info.arxiv.org/help/bulk_data.html
