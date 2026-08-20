#!/usr/bin/env python3
"""Search arXiv and emit normalized JSON records."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Literal, TypedDict
from urllib.parse import urlencode

import requests


API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
Sort = Literal["relevance", "lastUpdatedDate", "submittedDate"]
Order = Literal["ascending", "descending"]


class Paper(TypedDict):
    id: str | None
    title: str | None
    authors: list[str]
    summary: str | None
    published: str | None
    updated: str | None
    categories: list[str]
    doi: str | None
    journal_ref: str | None
    url: str | None


@dataclass(frozen=True)
class ArxivQuery:
    query: str | None = None
    ids: list[str] | None = None
    start: int = 0
    limit: int = 20
    sort: Sort = "relevance"
    order: Order = "descending"

    def url(self) -> str:
        params: dict[str, str | int] = {
            "start": self.start,
            "max_results": self.limit,
            "sortBy": self.sort,
            "sortOrder": self.order,
        }
        if self.ids:
            params["id_list"] = ",".join(self.ids)
        elif self.query is not None:
            params["search_query"] = self.query
        else:
            raise ValueError("query or ids required")
        return f"{API_URL}?{urlencode(params)}"


def text(entry: ET.Element, name: str, namespace: str = ATOM) -> str | None:
    value = entry.findtext(f"{namespace}{name}")
    return " ".join(value.split()) if value else None


def parse_feed(body: bytes) -> list[Paper]:
    root = ET.fromstring(body)
    records: list[Paper] = []
    for entry in root.findall(f"{ATOM}entry"):
        identifier = text(entry, "id")
        links = entry.findall(f"{ATOM}link")
        url = next((link.get("href") for link in links if link.get("rel") == "alternate"), identifier)
        authors = [name for author in entry.findall(f"{ATOM}author") if (name := text(author, "name"))]
        categories = [term for item in entry.findall(f"{ATOM}category") if (term := item.get("term"))]
        records.append({
            "id": identifier.rsplit("/", 1)[-1] if identifier else None,
            "title": text(entry, "title"),
            "authors": authors,
            "summary": text(entry, "summary"),
            "published": text(entry, "published"),
            "updated": text(entry, "updated"),
            "categories": categories,
            "doi": text(entry, "doi", ARXIV),
            "journal_ref": text(entry, "journal_ref", ARXIV),
            "url": url,
        })
    return records


def search(query: ArxivQuery, user_agent: str, timeout: float) -> list[Paper]:
    response = requests.get(query.url(), headers={"User-Agent": user_agent}, timeout=timeout)
    response.raise_for_status()
    return parse_feed(response.content)


def parser() -> argparse.ArgumentParser:
    description = "Search arXiv preprints; emits normalized JSON to stdout."
    epilog = """examples:
  python3 scripts/search_arxiv.py --query 'ti:agent AND cat:cs.AI' --limit 10
  python3 scripts/search_arxiv.py --id 2301.07041

Requires requests. Nonzero exit means input, dependency, network, XML, or API
failure."""
    value = argparse.ArgumentParser(
        description=description, epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = value.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="arXiv query, e.g. 'ti:agent AND cat:cs.AI'")
    source.add_argument("--id", action="append", dest="ids", help="repeatable arXiv ID lookup")
    value.add_argument("--start", type=int, default=0)
    value.add_argument("--limit", type=int, default=20)
    value.add_argument("--sort", choices=("relevance", "lastUpdatedDate", "submittedDate"), default="relevance")
    value.add_argument("--order", choices=("ascending", "descending"), default="descending")
    value.add_argument("--timeout", type=float, default=60, help="HTTP timeout seconds (default: 60)")
    value.add_argument("--user-agent", default="search-papers/1.0 (https://github.com/PRO-2684/skills)")
    return value


def main() -> int:
    arg_parser = parser()
    args = arg_parser.parse_args()
    query = ArxivQuery(args.query, args.ids, args.start, args.limit, args.sort, args.order)
    try:
        records = search(query, args.user_agent, args.timeout)
    except Exception as error:
        print(f"{arg_parser.prog}: {error}", file=sys.stderr)
        return 1
    json.dump(records, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
