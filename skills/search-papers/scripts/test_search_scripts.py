import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ConferenceTests(unittest.TestCase):
    def test_payload_uses_named_api_fields(self):
        module = load("search_conference")
        params = module.SearchParams(
            query="agent memory",
            mode="semantic",
            conferences=["ICLR", "NeurIPS"],
            year_min=2024,
            year_max=None,
            types=["oral"],
            sort="newest",
            limit=10,
        )
        self.assertEqual(
            params.payload(),
            {
                "query": "agent memory",
                "mode": "semantic",
                "conferences": ["ICLR", "NeurIPS"],
                "year_min": 2024,
                "year_max": None,
                "types": ["oral"],
                "sort": "newest",
                "limit": 10,
            },
        )

    def test_sse_returns_complete_data_event(self):
        module = load("search_conference")
        body = 'event: complete\ndata: [{"title":"Paper"}]\n\n'
        self.assertEqual(module.parse_sse(body), [{"title": "Paper"}])

    def test_schema_field_order_does_not_matter(self):
        module = load("search_conference")
        endpoint = {"parameters": [
            {"parameter_name": name} for name in reversed(module.EXPECTED_FIELDS)
        ]}
        module.validate_schema(endpoint)


class ArxivTests(unittest.TestCase):
    def test_url_encodes_query_and_sort(self):
        module = load("search_arxiv")
        url = module.ArxivQuery(
            query="ti:agent memory AND cat:cs.AI",
            ids=None,
            start=0,
            limit=5,
            sort="submittedDate",
            order="descending",
        ).url()
        self.assertIn("search_query=ti%3Aagent+memory+AND+cat%3Acs.AI", url)
        self.assertIn("sortBy=submittedDate", url)
        self.assertIn("max_results=5", url)

    def test_atom_parser_outputs_json_ready_records(self):
        module = load("search_arxiv")
        feed = b'''<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><id>https://arxiv.org/abs/2401.00001v1</id>
          <title> Agent Memory </title><summary> Useful work. </summary>
          <published>2024-01-01T00:00:00Z</published>
          <author><name>A. Author</name></author>
          <link href="https://arxiv.org/abs/2401.00001v1" rel="alternate" />
          <category term="cs.AI" /></entry>
        </feed>'''
        self.assertEqual(
            module.parse_feed(feed),
            [{
                "id": "2401.00001v1",
                "title": "Agent Memory",
                "authors": ["A. Author"],
                "summary": "Useful work.",
                "published": "2024-01-01T00:00:00Z",
                "updated": None,
                "categories": ["cs.AI"],
                "doi": None,
                "journal_ref": None,
                "url": "https://arxiv.org/abs/2401.00001v1",
            }],
        )


if __name__ == "__main__":
    unittest.main()
