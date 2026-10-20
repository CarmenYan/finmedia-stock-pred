"""Public-price collector tests use only fake HTTP and temporary directories."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import requests


MODULE = Path(__file__).resolve().parents[1] / "src/collect_public_prices.py"
spec = importlib.util.spec_from_file_location("collect_public_prices", MODULE)
collector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)


def fixture(symbol="AAPL"):
    timestamps = [int(pd.Timestamp(value).timestamp()) for value in
                  ["2019-12-31T14:30:00Z", "2020-01-02T14:30:00Z",
                   "2026-10-15T13:30:00Z", "2026-10-16T13:30:00Z"]]
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "exchangeTimezoneName": "America/New_York", "currency": "USD"},
        "timestamp": timestamps,
        "indicators": {
            "quote": [{"open": [100, 101, 102, 103], "high": [104, 105, 106, 107],
                       "low": [99, 100, 101, 102], "close": [102, 103, 104, 105],
                       "volume": [1000, 2000, 3000, 4000]}],
            "adjclose": [{"adjclose": [90, 91, 92, 93]}],
        },
    }]}}


class FakeResponse:
    def __init__(self, payload=None, *, body=None, status=200, headers=None):
        self.content = body if body is not None else json.dumps(payload).encode("utf-8")
        self.status_code = status
        self.headers = {"Content-Type": "application/json", **(headers or {})}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class PublicPriceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="finmedia-yahoo-offline-")
        self.root = Path(self.temporary.name)
        self.base = self.root / "data/supplemental/yahoo_prices"
        self.config = collector.PublicPriceConfig(symbols=("AAPL",))

    def tearDown(self):
        self.temporary.cleanup()

    def collect(self, responses, **kwargs):
        session = FakeSession(responses)
        result = collector.run_collection(self.root, self.config, collect=True, session=session, **kwargs)
        return result, session

    def test_default_inspection_never_constructs_session_or_creates_files(self):
        with patch.object(collector.requests, "Session", side_effect=AssertionError("No network allowed")):
            result = collector.run_collection(self.root, self.config)
        self.assertFalse(result["network_calls_executed"])
        self.assertEqual(result["status"], "missing_or_invalid_cache")
        self.assertFalse((self.root / "data").exists())
        self.assertEqual(collector.PublicPriceConfig().symbols, ("AAPL", "JNJ", "SPY", "AMZN"))

    def test_ny_half_open_dates_raw_preservation_and_adjusted_close(self):
        body = ("  " + json.dumps(fixture(), indent=2) + "\n\n").encode("utf-8")
        result, session = self.collect([FakeResponse(body=body)])
        saved = pd.read_parquet(result["dataset_path"])
        self.assertEqual(list(saved.columns), collector.OUTPUT_COLUMNS)
        self.assertEqual(saved["date"].dt.strftime("%Y-%m-%d").tolist(), ["2020-01-02", "2026-10-15"])
        self.assertIsNone(saved["date"].dt.tz)
        self.assertEqual(str(saved["timestamp"].dt.tz), "UTC")
        self.assertEqual(saved["close"].tolist(), [103.0, 104.0])
        self.assertEqual(saved["adjusted_close"].tolist(), [91.0, 92.0])
        self.assertEqual((self.base / "raw/AAPL.json").read_bytes(), body)
        archived = list((self.base / "raw/responses/AAPL").glob("*.body"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), body)
        params = session.calls[0][1]["params"]
        self.assertEqual(params["period1"], int(pd.Timestamp("2020-01-01T00:00:00", tz="America/New_York").timestamp()))
        self.assertEqual(params["period2"], int(pd.Timestamp("2026-10-16T00:00:00", tz="America/New_York").timestamp()))
        manifest = json.loads((self.base / "cache/AAPL.manifest.json").read_text())
        self.assertEqual(manifest["outside_session_date_interval_rows"], 2)
        self.assertEqual(manifest["raw_json_sha256"], collector._sha256(self.base / "raw/AAPL.json"))
        self.assertIn("retrieved_at_utc", manifest)
        self.assertFalse((self.root / "data/raw").exists())

    def test_missing_adjusted_close_and_malformed_lengths_rejected_but_bodies_archived(self):
        missing = fixture()
        del missing["chart"]["result"][0]["indicators"]["adjclose"]
        lengths = fixture()
        lengths["chart"]["result"][0]["indicators"]["quote"][0]["open"] = [1]
        null_adjusted = fixture()
        null_adjusted["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][1] = None
        for payload in (missing, lengths, null_adjusted):
            with self.subTest(payload=payload):
                session = FakeSession([FakeResponse(payload)])
                with self.assertRaises(collector.PublicPriceError):
                    collector.run_collection(self.root, self.config, collect=True, session=session)
                self.assertEqual(len(session.calls), 1)
                self.assertFalse((self.base / "prices.parquet").exists())
        self.assertEqual(len(list((self.base / "raw/responses/AAPL").glob("*.body"))), 3)

    def test_provider_errors_empty_results_and_non_json_are_not_retried(self):
        responses = [FakeResponse({"chart": {"result": None, "error": {"code": "Not Found"}}}),
                     FakeResponse({"chart": {"result": [], "error": None}}),
                     FakeResponse(body=b"<html>Access restriction</html>")]
        for response in responses:
            with self.subTest(body=response.content):
                session = FakeSession([response])
                with self.assertRaises(collector.PublicPriceError):
                    collector.run_collection(self.root, self.config, collect=True, session=session)
                self.assertEqual(len(session.calls), 1)

    def test_quote_nulls_stay_missing_without_zero_fill(self):
        payload = fixture()
        payload["chart"]["result"][0]["indicators"]["quote"][0]["open"][1] = None
        payload["chart"]["result"][0]["indicators"]["quote"][0]["volume"][1] = None
        result, _ = self.collect([FakeResponse(payload)])
        frame = pd.read_parquet(result["dataset_path"])
        self.assertTrue(pd.isna(frame.loc[0, "open"]))
        self.assertTrue(pd.isna(frame.loc[0, "volume"]))
        manifest = json.loads((self.base / "cache/AAPL.manifest.json").read_text())
        self.assertEqual(manifest["null_counts"]["open"], 1)
        self.assertEqual(manifest["null_counts"]["volume"], 1)

    def test_cache_integrity_and_no_second_request(self):
        self.collect([FakeResponse(fixture())])
        session = FakeSession([])
        result = collector.run_collection(self.root, self.config, collect=True, session=session)
        self.assertEqual(session.calls, [])
        self.assertEqual(result["symbols"]["AAPL"]["action"], "reused")
        self.assertEqual(collector.inspect_cache(self.root, self.config)["status"], "ready")
        with (self.base / "raw/AAPL.json").open("ab") as stream:
            stream.write(b"corruption")
        self.assertEqual(collector.inspect_cache(self.root, self.config)["symbols"]["AAPL"]["cache_status"], "file_hash_mismatch")
        result, session = self.collect([FakeResponse(fixture())])
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(result["symbols"]["AAPL"]["action"], "fetched")

    def test_access_restrictions_are_not_bypassed_or_retried(self):
        session = FakeSession([FakeResponse(body=b"Forbidden", status=403)])
        waits = []
        with self.assertRaisesRegex(collector.PublicPriceError, "HTTP 403"):
            collector.run_collection(self.root, self.config, collect=True, session=session, sleep=waits.append)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(waits, [])
        self.assertEqual(len(list((self.base / "raw/responses/AAPL").glob("*.body"))), 1)

    def test_retry_after_is_respected_and_long_pause_stops(self):
        waits = []
        result, session = self.collect([FakeResponse({}, status=429, headers={"Retry-After": "2"}),
                                        FakeResponse(fixture())], sleep=waits.append)
        self.assertEqual(waits, [2.0])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(result["symbols"]["AAPL"]["rows"], 2)
        blocked = FakeSession([FakeResponse({}, status=429, headers={"Retry-After": "31"})])
        with self.assertRaisesRegex(collector.PublicPriceError, "longer pause"):
            collector.run_collection(self.root, self.config, collect=True, refresh=True,
                                     session=blocked, sleep=waits.append)
        self.assertEqual(len(blocked.calls), 1)
        self.assertEqual(waits, [2.0])

    def test_transient_connection_and_server_failures_are_bounded(self):
        waits = []
        _, session = self.collect([requests.ConnectionError("offline failure"),
                                    FakeResponse({}, status=503), FakeResponse(fixture())], sleep=waits.append)
        self.assertEqual(waits, [1.0, 2.0])
        self.assertEqual(len(session.calls), 3)
        self.assertTrue(all(wait <= 30 for wait in waits))

    def test_duplicate_dates_and_wrong_symbols_rejected(self):
        duplicate = fixture()
        duplicate["chart"]["result"][0]["timestamp"][2] = duplicate["chart"]["result"][0]["timestamp"][1]
        wrong_symbol = fixture("JNJ")
        for payload in (duplicate, wrong_symbol):
            with self.subTest(payload=payload):
                with self.assertRaises(collector.PublicPriceError):
                    self.collect([FakeResponse(payload)])


if __name__ == "__main__":
    unittest.main()
