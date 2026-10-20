"""Offline tests: fake clients only, temporary outputs, no credentials or API calls."""

import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "src/collect_pipeline.py"
spec = importlib.util.spec_from_file_location("collect_pipeline", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
# dataclasses resolves annotations through the module registry.
import sys
sys.modules[spec.name] = pipeline
spec.loader.exec_module(pipeline)


class FakeHTTPError(Exception):
    def __init__(self, status):
        self.status_code = status
        super().__init__("Sensitive server detail deliberately not propagated")


class FakeNewsClient:
    def __init__(self, articles=None, failures=None):
        self.articles = articles or []
        self.failures = list(failures or [])
        self.calls = []

    def get_news(self, request):
        self.calls.append(request)
        if self.failures:
            raise self.failures.pop(0)
        # Model inclusive API boundaries; production code must make saved chunks
        # half-open. The real SDK handles pagination before returning this list.
        start, end = pd.Timestamp(request["start"]), pd.Timestamp(request["end"])
        rows = [article for article in self.articles
                if start <= pd.Timestamp(article["created_at"]) <= end]
        return SimpleNamespace(data={"news": rows})


class FakePriceClient:
    def __init__(self, failures=None):
        self.calls = []
        self.failures = list(failures or [])

    def get_stock_bars(self, request):
        self.calls.append(request)
        if self.failures:
            raise self.failures.pop(0)
        timestamp = pd.Timestamp(request["start"]) + pd.Timedelta(hours=6)
        rows = [{"symbol": symbol, "timestamp": timestamp, "open": 100.0,
                 "high": 103.0, "low": 99.0, "close": 102.0, "volume": 1000,
                 "trade_count": 10, "vwap": 101.0} for symbol in request["symbols"]]
        return SimpleNamespace(df=pd.DataFrame(rows).set_index(["symbol", "timestamp"]))


def article(identifier, created, headline="News", updated=None):
    return {"id": identifier, "created_at": created, "updated_at": updated or created,
            "headline": headline, "source": "offline fixture", "symbols": ["AAPL", "JNJ"],
            "url": "https://example.invalid/offline-test"}


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="finmedia-collection-offline-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def config(self, **changes):
        values = {"tickers": ("AAPL",), "start": "2020-12-31T00:00:00Z", "end": "2021-01-02T00:00:00Z"}
        values.update(changes)
        return pipeline.CollectionConfig(**values)

    def run_collection(self, config=None, news=None, prices=None, **kwargs):
        return pipeline.collect_dataset(self.root, config or self.config(),
                                        news_client=news or FakeNewsClient(),
                                        price_client=prices or FakePriceClient(), **kwargs)

    def test_plan_requires_no_credentials_or_network_and_rejects_naive_bounds(self):
        plan = pipeline.collect_dataset(self.root, self.config(), dry_run=True)
        self.assertEqual(plan["status"], "plan_only")
        self.assertFalse(plan["network_calls_executed"])
        self.assertFalse(plan["credential_status"]["credentials_loaded"])
        self.assertFalse((self.root / "data").exists())
        with self.assertRaises(ValueError):
            self.config(start="2020-12-31")

    def test_boundaries_versions_missing_ids_and_multiple_tickers(self):
        news = FakeNewsClient([
            article(1, "2020-12-31T12:00:00Z"),
            article(2, "2021-01-01T00:00:00Z", "Older", "2021-01-01T00:00:00Z"),
            article(2, "2021-01-01T00:00:00Z", "Revised", "2021-01-01T03:00:00Z"),
            article(None, "2021-01-01T12:00:00Z", "No ID"),
            article(None, "2021-01-01T12:00:00Z", "No ID"),
            article(3, "2021-01-02T00:00:00Z", "Exclusive end"),
        ])
        config = self.config(tickers=("AAPL", "JNJ"))
        result = self.run_collection(config, news=news)
        self.assertEqual(len(news.calls), 4)
        for ticker in config.tickers:
            saved = pd.read_parquet(self.root / "data/raw/news" / f"{ticker}.parquet")
            self.assertEqual(len(saved), 4)
            self.assertEqual(saved["id"].isna().sum(), 2)
            self.assertEqual(saved.loc[saved["id"].eq("2"), "headline"].item(), "Revised")
            self.assertFalse(saved["headline"].eq("Exclusive end").any())
            self.assertEqual(result["news"][ticker]["duplicate_id_records_removed"], 1)
            self.assertIn("url", saved)
            self.assertIn("updated_at", saved)
        self.assertTrue(all(call["limit"] is None for call in news.calls))
        chunks = sorted((self.root / "data/raw/news/chunks/AAPL").glob("*.manifest.json"))
        first = json.loads(chunks[0].read_text())
        self.assertGreater(first["outside_half_open_window_rows"], 0)
        self.assertFalse(first["api_archive_completeness_verified"])

    def test_prices_persist_and_second_run_uses_validated_cache(self):
        news, prices = FakeNewsClient(), FakePriceClient()
        first = self.run_collection(news=news, prices=prices)
        call_counts = len(news.calls), len(prices.calls)
        second = self.run_collection(news=news, prices=prices)
        self.assertEqual((len(news.calls), len(prices.calls)), call_counts)
        self.assertTrue(all(event["action"] == "reused" for event in second["events"]))
        price_path = self.root / "data/raw/prices.parquet"
        saved = pd.read_parquet(price_path)
        self.assertEqual(set(saved["symbol"]), {"AAPL", "SPY"})
        manifest = json.loads(price_path.with_suffix(".manifest.json").read_text())
        self.assertEqual(manifest["file_sha256"], pipeline._hash(price_path))
        self.assertEqual(manifest["row_count"], len(saved))
        self.assertEqual(manifest["identity"]["parameters"]["feed"], "sip")
        self.assertEqual(manifest["identity"]["parameters"]["adjustment"], "all")
        self.assertFalse(first["api_archive_completeness_verified"])

    def test_corrupted_hash_and_schema_are_refetched(self):
        news, prices = FakeNewsClient(), FakePriceClient()
        self.run_collection(news=news, prices=prices)
        chunks = sorted((self.root / "data/raw/news/chunks/AAPL").glob("*.parquet"))
        with chunks[0].open("ab") as stream:
            stream.write(b"corrupted offline fixture")
        price_manifest_path = self.root / "data/raw/prices.manifest.json"
        price_manifest = json.loads(price_manifest_path.read_text())
        price_manifest["schema"][0]["dtype"] = "incorrect test schema"
        price_manifest_path.write_text(json.dumps(price_manifest))
        old_news, old_prices = len(news.calls), len(prices.calls)
        result = self.run_collection(news=news, prices=prices)
        self.assertEqual(len(news.calls), old_news + 1)
        self.assertEqual(len(prices.calls), old_prices + 1)
        self.assertIn("file_hash_mismatch", [event["cache_reason"] for event in result["events"]])
        self.assertIn("dtype_schema_mismatch", [event["cache_reason"] for event in result["events"]])

    def test_request_changes_invalidate_relevant_cache(self):
        news, prices = FakeNewsClient(), FakePriceClient()
        self.run_collection(news=news, prices=prices)
        old_news, old_prices = len(news.calls), len(prices.calls)
        result = self.run_collection(self.config(price_feed="iex"), news=news, prices=prices)
        self.assertEqual(len(news.calls), old_news)
        self.assertEqual(len(prices.calls), old_prices + 1)
        self.assertEqual(result["prices"]["feed"], "iex")
        old_news = len(news.calls)
        self.run_collection(self.config(end="2021-01-03T00:00:00Z", price_feed="iex"), news=news, prices=prices)
        self.assertEqual(len(news.calls), old_news + 1)

    def test_auth_failure_has_no_retry_or_feed_fallback(self):
        waits = []
        news, prices = FakeNewsClient(failures=[FakeHTTPError(401)]), FakePriceClient()
        with self.assertRaisesRegex(pipeline.CollectionError, "HTTP 401") as caught:
            self.run_collection(news=news, prices=prices, sleep=waits.append)
        self.assertEqual(len(news.calls), 1)
        self.assertEqual(waits, [])
        self.assertEqual(prices.calls, [])
        self.assertNotIn("Sensitive", str(caught.exception))
        run = json.loads((self.root / "data/raw/collection_run.json").read_text())
        self.assertEqual(run["status"], "failed_partial_caches_preserved")

    def test_transient_retry_is_bounded(self):
        waits = []
        news = FakeNewsClient(failures=[FakeHTTPError(429), ConnectionError("offline test")])
        self.run_collection(news=news, sleep=waits.append)
        self.assertEqual(waits, [1.0, 2.0])
        self.assertTrue(all(wait <= 30 for wait in waits))
        self.assertEqual(len(news.calls), 4)  # three attempts for chunk 1, one for chunk 2

    def test_failure_preserves_completed_chunks_for_resume(self):
        class FailSecondChunk(FakeNewsClient):
            def get_news(self, request):
                if pd.Timestamp(request["start"]).year == 2021:
                    self.calls.append(request)
                    raise FakeHTTPError(403)
                return super().get_news(request)

        with self.assertRaisesRegex(pipeline.CollectionError, "HTTP 403"):
            self.run_collection(news=FailSecondChunk())
        directory = self.root / "data/raw/news/chunks/AAPL"
        self.assertEqual(len(list(directory.glob("*.manifest.json"))), 1)
        self.assertFalse((self.root / "data/raw/prices.parquet").exists())
        resumed = FakeNewsClient()
        result = self.run_collection(news=resumed)
        self.assertEqual(len(resumed.calls), 1)
        self.assertEqual(result["events"][0]["action"], "reused")
        self.assertTrue((self.root / "data/raw/prices.parquet").is_file())

    def test_interruption_before_manifest_is_never_a_valid_cache(self):
        news = FakeNewsClient()
        with patch.object(pipeline, "_atomic_json", side_effect=OSError("offline interrupted commit")):
            with self.assertRaises(OSError):
                self.run_collection(news=news)
        directory = self.root / "data/raw/news/chunks/AAPL"
        self.assertEqual(len(list(directory.glob("*.parquet"))), 1)
        self.assertEqual(list(directory.glob("*.manifest.json")), [])
        resumed = FakeNewsClient()
        result = self.run_collection(news=resumed)
        self.assertEqual(len(resumed.calls), 2)
        self.assertEqual(result["events"][0]["cache_reason"], "file_or_manifest_missing")

    def test_auth_credentials_are_project_file_only(self):
        env_path = self.root / ".env"
        env_path.write_text("API_KEY=${UNRELATED_GLOBAL_KEY}\nSECRET_KEY=local-fixture\n")
        # Global environment references are rejected before any request.
        with self.assertRaisesRegex(pipeline.CollectionError, "interpolation is disabled"):
            pipeline._project_credentials(self.root)
        env_path.write_text("API_KEY=local-key-fixture\nSECRET_KEY=local-fixture\n")
        with patch.dict("os.environ", {"API_KEY": "wrong-global-fixture", "SECRET_KEY": "wrong-global-fixture"}):
            key, secret = pipeline._project_credentials(self.root)
        self.assertEqual(key, "local-key-fixture")
        self.assertEqual(secret, "local-fixture")
        self.assertFalse(pipeline.credential_file_status(self.root)["credentials_loaded"])

    @unittest.skipUnless(importlib.util.find_spec("alpaca"), "alpaca-py optional in offline environments")
    def test_real_sdk_request_objects_are_utc_and_unlimited_without_network(self):
        news = pipeline._sdk_request("news", {"ticker": "AAPL", "start": self.config().start,
                                              "end": self.config().end})
        self.assertIsNone(news.limit)
        self.assertIsNotNone(news.start.tzinfo)
        self.assertEqual(news.sort, "asc")
        prices = pipeline._sdk_request("prices", {"symbols": ["AAPL", "SPY"],
                                                   "start": self.config().start, "end": self.config().end,
                                                   "feed": "sip", "adjustment": "all"})
        self.assertIsNone(prices.limit)
        self.assertEqual(prices.feed.value, "sip")
        self.assertEqual(prices.adjustment.value, "all")


if __name__ == "__main__":
    unittest.main()
