#!/usr/bin/env python3
"""Search accepted AI conference papers through the Hugging Face Space."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any, Literal

import requests


BASE_URL = "https://ai-conferences-conference-paper-search.hf.space/gradio_api"
EXPECTED_FIELDS = [
    "query", "mode", "conferences", "year_min", "year_max", "types", "sort", "limit"
]
CONFERENCES = (
    "3DV", "AAAI", "ACL", "COLM", "CVPR", "ECCV", "EMNLP", "ICASSP", "ICCV",
    "ICLR", "ICML", "ICRA", "Interspeech", "MICCAI", "NAACL", "NeurIPS",
    "SIGGRAPH", "SIGGRAPHAsia", "WACV",
)
PAPER_TYPES = ("poster", "spotlight", "oral", "notable-top-25%", "notable-top-5%", "talk")
Mode = Literal["semantic", "keyword"]
Sort = Literal["relevance", "newest", "upvotes"]


@dataclass(frozen=True)
class SearchParams:
    query: str
    mode: Mode = "semantic"
    conferences: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None
    types: list[str] | None = None
    sort: Sort = "relevance"
    limit: int = 20

    def payload(self) -> dict[str, object]:
        return asdict(self)


def parse_sse(body: str) -> Any:
    for block in body.replace("\r\n", "\n").split("\n\n"):
        lines = block.splitlines()
        event = next((line[6:].strip() for line in lines if line.startswith("event:")), "")
        data = "\n".join(line[5:].lstrip() for line in lines if line.startswith("data:"))
        if event == "error":
            raise RuntimeError(f"Space returned error: {data}")
        if event == "complete" and data:
            return json.loads(data)
    raise RuntimeError("Space response ended without a complete event")


def validate_schema(endpoint: dict[str, Any] | None) -> None:
    fields = {item.get("parameter_name") for item in (endpoint or {}).get("parameters", [])}
    if fields != set(EXPECTED_FIELDS):
        raise RuntimeError("live API schema mismatch; read references/conference-paper-search.md")


def search(params: SearchParams, token: str, timeout: float) -> Any:
    with requests.Session() as session:
        session.headers["Authorization"] = f"Bearer {token}"

        schema_response = session.get(f"{BASE_URL}/info", timeout=timeout)
        schema_response.raise_for_status()
        endpoint = schema_response.json().get("named_endpoints", {}).get("/search")
        validate_schema(endpoint)

        call_response = session.post(
            f"{BASE_URL}/call/v2/search", json=params.payload(), timeout=timeout
        )
        call_response.raise_for_status()
        event_id = call_response.json().get("event_id")
        if not event_id:
            raise RuntimeError("Space response missing event_id")

        result_response = session.get(
            f"{BASE_URL}/call/search/{event_id}", timeout=timeout
        )
        result_response.raise_for_status()
        result = parse_sse(result_response.text)
        return result[0] if isinstance(result, list) and len(result) == 1 else result


def parser() -> argparse.ArgumentParser:
    description = "Search accepted AI conference papers; emits JSON to stdout."
    epilog = """example:
  python3 scripts/search_conference.py 'agent memory' --conference ICLR --year-min 2024 --limit 10

Requires HF_TOKEN and requests. Nonzero exit means input, dependency, auth,
network, schema, or API failure."""
    value = argparse.ArgumentParser(
        description=description, epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    value.add_argument("query", help="semantic or keyword query")
    value.add_argument("--mode", choices=("semantic", "keyword"), default="semantic")
    value.add_argument(
        "--conference", action="append", choices=CONFERENCES, dest="conferences",
        help="repeatable venue filter",
    )
    value.add_argument("--year-min", type=int)
    value.add_argument("--year-max", type=int)
    value.add_argument(
        "--type", action="append", choices=PAPER_TYPES, dest="types",
        help="repeatable presentation type",
    )
    value.add_argument("--sort", choices=("relevance", "newest", "upvotes"), default="relevance")
    value.add_argument("--limit", type=int, default=20)
    value.add_argument("--timeout", type=float, default=120, help="HTTP timeout seconds (default: 120)")
    return value


def main() -> int:
    arg_parser = parser()
    args = arg_parser.parse_args()
    token = os.environ.get("HF_TOKEN")
    if not token:
        arg_parser.error("HF_TOKEN is missing; create one with inference access")
    params = SearchParams(
        query=args.query,
        mode=args.mode,
        conferences=args.conferences,
        year_min=args.year_min,
        year_max=args.year_max,
        types=args.types,
        sort=args.sort,
        limit=args.limit,
    )
    try:
        result = search(params, token, args.timeout)
    except Exception as error:
        print(f"{arg_parser.prog}: {error}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
