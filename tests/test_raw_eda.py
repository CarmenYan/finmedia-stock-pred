"""Offline regression checks; all input observations are temporary test fixtures."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from raw_eda import run_raw_eda


class RawEdaChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data/raw/news").mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def news(self, ticker, times=None, updates=None):
        times = times if times is not None else ["2024-11-25T15:00:00Z", "2024-12-02T20:00:00Z"]
        frame = pd.DataFrame({
            "ticker": [ticker] * len(times), "created_at": pd.to_datetime(times, utc=True),
            "headline": [f"Fixture {i}" for i in range(len(times))],
            "source": ["offline fixture"] * len(times), "symbols": [[ticker] for _ in times],
        })
        if updates is not None:
            frame["updated_at"] = pd.to_datetime(updates, utc=True)
        frame.to_parquet(self.root / f"data/raw/news/{ticker}.parquet", index=False)

    def prices(self, symbols=("AAPL", "JNJ", "SPY"), dates=("2024-11-26", "2024-11-27", "2024-11-29")):
        rows = []
        for symbol in symbols:
            for day in dates:
                timestamp = pd.Timestamp(day, tz="America/New_York").tz_convert("UTC")
                rows.append({"symbol": symbol, "timestamp": timestamp, "open": 100.,
                             "high": 102., "low": 98., "close": 101., "volume": 1000})
        pd.DataFrame(rows).to_parquet(self.root / "data/raw/prices.parquet", index=False)

    def run_eda(self):
        return run_raw_eda(self.root, requested_start="2024-11-25T00:00:00Z",
                           requested_end="2024-12-03T00:00:00Z")

    def test_waiting_run_does_not_leave_previous_generated_figures(self):
        (self.root / "figures").mkdir()
        generated = self.root / "figures/eda_raw_monthly_news.png"
        generated.write_bytes(b"old generated output")
        unrelated = self.root / "figures/team_figure.png"
        unrelated.write_bytes(b"keep")
        result = self.run_eda()
        self.assertEqual(result["status"], "waiting_for_data")
        self.assertFalse(generated.exists())
        self.assertTrue(unrelated.exists())

    def test_empty_required_source_is_partial_even_if_other_figures_exist(self):
        self.news("AAPL")
        self.news("JNJ", times=[])
        self.prices()
        result = self.run_eda()
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any(item["input"] == "JNJ" for item in result["unusable_inputs"]))
        self.assertTrue(result["figures"])

    def test_entire_missing_symbol_and_missing_edge_dates_are_reported(self):
        self.news("AAPL")
        self.news("JNJ")
        self.prices(symbols=("AAPL", "JNJ"))
        result = self.run_eda()
        self.assertEqual(result["prices"]["missing_expected_symbols"], ["SPY"])
        coverage = result["prices"]["by_symbol"]["AAPL"]["requested_window_coverage"]
        self.assertEqual(coverage["missing_before_first_observation"], 1)
        self.assertEqual(coverage["missing_after_last_observation"], 1)
        self.assertEqual(coverage["expected_sessions"], 5)

    def test_headline_revision_after_early_close_is_flagged(self):
        self.news("AAPL", times=["2024-11-29T17:00:00Z", "2024-11-29T17:50:00Z"],
                  updates=["2024-11-29T17:15:00Z", "2024-11-29T19:00:00Z"])
        self.news("JNJ")
        self.prices()
        result = self.run_eda()
        check = result["news"]["AAPL"]["headline_revision_check"]
        self.assertEqual(check["updated_after_first_eligible_close_rows"], 1)

    def test_missing_session_never_becomes_a_single_day_return(self):
        self.news("AAPL")
        self.news("JNJ")
        self.prices(dates=("2024-11-25", "2024-11-27"))
        result = self.run_eda()
        check = result["prices"]["by_symbol"]["AAPL"]
        self.assertEqual(check["missing_session_dates"], ["2024-11-26"])
        self.assertEqual(check["daily_return_percent_summary"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
