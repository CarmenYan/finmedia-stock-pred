"""Offline collector tests: synthetic responses and temporary local directories only."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd


SOURCE = Path(__file__).resolve().parents[1] / "src/collect_public_news.py"
spec = importlib.util.spec_from_file_location("collect_public_news", SOURCE)
news = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = news
spec.loader.exec_module(news)


def article(when="2024-01-03T12:00:00Z", title="Offline fixture", link="https://example.invalid/story?id=1"):
    return {"date": when, "title": title, "link": link, "symbols": ["AAPL.US"],
            "tags": ["fixture"], "sentiment": {"polarity": 0.2, "neg": 0.1, "neu": 0.6, "pos": 0.3},
            "content": "FULL BODY MUST NOT ENTER NORMALIZED TABLES"}


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, parameters, timeout):
        self.calls.append(parameters)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, tuple):
            return result
        return 200, {"Content-Type": "application/json"}, json.dumps(result).encode()


class PublicNewsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="eodhd-offline-")
        self.root = Path(self.temporary.name)
        self.waits = []

    def tearDown(self):
        self.temporary.cleanup()

    def config(self, **changes):
        values = {"tickers": ("AAPL",), "start": "2024-01-01", "end": "2024-02-01"}
        values.update(changes)
        return news.PublicNewsConfig(**values)

    def run_collector(self, responses, config=None):
        transport = responses if isinstance(responses, FakeTransport) else FakeTransport(responses)
        result = news.collect_public_news(self.root, config or self.config(), collect=True,
                                          transport=transport, sleep=self.waits.append, monotonic=lambda: 0)
        return result, transport

    def test_default_is_offline_without_writes_or_credentials(self):
        transport = FakeTransport([])
        result = news.collect_public_news(self.root, self.config(), transport=transport)
        self.assertEqual(result["status"], "plan_only")
        self.assertFalse(result["network_calls_executed"])
        self.assertEqual(transport.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(ValueError):
            self.config(tickers=("JNJ",))

    def test_monthly_half_open_bounds_and_leap_year_requests(self):
        result, transport = self.run_collector([[], []], self.config(start="2024-02-28", end="2024-03-03"))
        self.assertEqual([(p["from"], p["to"]) for p in transport.calls],
                         [("2024-02-28", "2024-02-29"), ("2024-03-01", "2024-03-02")])
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["archive_completeness_verified"])

    def test_preserves_exact_response_bytes_and_excludes_full_content(self):
        raw = ("  " + json.dumps([article()], ensure_ascii=False) + "\n").encode()
        result, _ = self.run_collector([(200, {}, raw)])
        self.assertEqual(Path(result["pages"][0]["raw_path"]).read_bytes(), raw)
        frame = pd.read_parquet(result["normalized_path"])
        self.assertEqual(str(frame["created_at"].dtype), "datetime64[ns, UTC]")
        self.assertNotIn("content", frame.columns)
        self.assertNotIn("FULL BODY", frame.to_json(date_format="iso"))
        self.assertAlmostEqual(frame["sentiment_polarity"].item(), 0.2)
        self.assertFalse(result["point_in_time_text_verified"])

    def test_pagination_range_checks_and_exact_url_dedup(self):
        first = article()
        second = article(link="https://example.invalid/story?id=2")
        outside = article("2024-02-01T00:00:00Z", "Exclusive boundary")
        result, transport = self.run_collector([[first, second], [first, outside], []], self.config(page_size=2))
        self.assertEqual([p["offset"] for p in transport.calls], [0, 2, 4])
        self.assertEqual(result["normalized_rows"], 2)
        self.assertEqual(result["exact_duplicate_records_removed"], 1)
        self.assertEqual(result["windows"][0]["out_of_window_rows"], 1)
        self.assertEqual(result["status"], "partial")
        saved = pd.read_parquet(result["normalized_path"])
        self.assertEqual(set(saved["link"]), {first["link"], second["link"]})

    def test_validated_cache_reuse_and_tampering_refetch(self):
        first, _ = self.run_collector([[article()]])
        cached, transport = self.run_collector([])
        self.assertEqual(transport.calls, [])
        self.assertEqual(cached["cache_pages_reused"], 1)
        Path(first["pages"][0]["raw_path"]).write_bytes(b"tampered")
        refreshed, transport = self.run_collector([[article(title="New fixture")]])
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(refreshed["cache_pages_reused"], 0)

    def test_cache_parameters_must_match(self):
        self.run_collector([[article()]])
        changed, transport = self.run_collector([[article()]], self.config(page_size=2))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(changed["cache_pages_reused"], 0)

    def test_repeated_page_stops_and_partial_window_is_not_complete(self):
        result, transport = self.run_collector([[article()], [article()]], self.config(page_size=1))
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(result["normalized_rows"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["windows"][0]["status"], "duplicate_page")

    def test_page_budget_and_empty_windows_are_explicit(self):
        result, _ = self.run_collector([[article()], [article(title="Other")]],
                                       self.config(page_size=1, max_pages_per_window=2))
        self.assertEqual(result["windows"][0]["status"], "capped_window")
        self.assertEqual(result["status"], "partial")
        empty_root = self.root / "empty"
        empty_root.mkdir()
        empty = news.collect_public_news(empty_root, self.config(), collect=True,
                                         transport=FakeTransport([[]]), sleep=self.waits.append)
        self.assertEqual(empty["windows"][0]["status"], "empty_window")
        self.assertEqual(empty["normalized_rows"], 0)
        self.assertEqual(len(pd.read_parquet(empty["normalized_path"])), 0)

    def test_429_and_403_stop_without_retry_or_gate_bypass(self):
        for status in (429, 403):
            with self.subTest(status=status):
                target = self.root / str(status)
                target.mkdir()
                transport = FakeTransport([(status, {"Retry-After": "60"}, b"blocked fixture")])
                result = news.collect_public_news(target, self.config(), collect=True,
                                                  transport=transport, sleep=self.waits.append)
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["issues"][0]["http_status"], status)
                self.assertEqual(Path(result["issues"][0]["raw_path"]).read_bytes(), b"blocked fixture")

    def test_5xx_retry_is_bounded_and_requests_are_paced(self):
        result, transport = self.run_collector([(503, {}, b"temporary fixture"), [article()]])
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(self.waits, [1, 1.1])
        self.assertEqual(result["normalized_rows"], 1)

    def test_naive_or_missing_dates_are_not_assumed_asof(self):
        result, _ = self.run_collector([[article("2024-01-03"), article(None), article()]])
        self.assertEqual(result["normalized_rows"], 1)
        self.assertEqual(result["windows"][0]["invalid_or_naive_date_rows"], 2)
        self.assertEqual(result["status"], "partial")

    def test_malformed_responses_have_no_reusable_cache(self):
        result, _ = self.run_collector([(200, {}, b'{"error":"fixture"}')])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["issues"][0]["reason"], "unexpected_response_schema")
        self.assertEqual(list((self.root / "data/supplemental/eodhd_news/raw").glob("*.manifest.json")), [])


if __name__ == "__main__":
    unittest.main()
