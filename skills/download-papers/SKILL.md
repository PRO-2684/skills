---
name: download-papers
description: Download IEEE Xplore publisher PDFs by document ID through institutional or subscriber access, especially when inherited proxies or browser-only entitlement cookies defeat direct downloads. Not for general literature search.
---

# Download Papers

IEEE only, for now. Resolve the helper relative to this `SKILL.md` and inspect its CLI before use:

```bash
python3 scripts/download_ieee.py --help
```

Pass one or more numeric IEEE document IDs and an output directory:

```bash
python3 scripts/download_ieee.py 9757872 9879360 --output-dir papers/
```

The helper owns the workflow: it creates a fresh proxy-free `agent-browser` session, confirms and reports `Access provided by`, exports browser cookies into private temporary storage, waits a randomized interval before each PDF request, downloads through `wget`, `curl`, or `aria2c`, validates each PDF, writes `<DOCUMENT_ID>.pdf`, prints JSON metadata to stdout, and removes the browser session and credentials.

Use `--downloader` only to select a transport when `auto` is unsuitable. Use `--force` only when replacing existing `<DOCUMENT_ID>.pdf` files is intended. Rename files afterward from the emitted metadata when useful.

## Failure Meaning

- IEEE 418: stop; do not add retries or reduce the randomized delays.
- Repeated `tag=1` redirects or 502: entitlement cookies were not accepted.
- HTML instead of `%PDF-`: access denial or an IEEE error page, not a PDF.

Do not bypass a paywall. This carries access already granted to the user's direct institutional, open-access, or personal IEEE session.
