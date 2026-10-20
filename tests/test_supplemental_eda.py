"""Calendar and target checks use small synthetic inputs, never the actual data."""
from pathlib import Path
import sys
import unittest

import pandas as pd
import pandas_market_calendars as mcal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from supplemental_eda import align_news, prepare_prices


class SupplementalEdaChecks(unittest.TestCase):
    def prices(self, dates):
        return pd.DataFrame({"symbol": ["AAPL"] * len(dates), "date": dates,
                             "open": [100.] * len(dates), "high": [102.] * len(dates),
                             "low": [98.] * len(dates), "close": [101.] * len(dates),
                             "adjusted_close": [101. + i for i in range(len(dates))], "volume": [1000] * len(dates)})

    def test_missing_day_is_not_a_one_day_return_or_target(self):
        daily, quality, _ = prepare_prices(self.prices(["2024-11-25", "2024-11-27"]), "2024-11-25", "2024-11-28")
        self.assertEqual(quality.missing_or_excluded_sessions.iloc[0], 1)
        self.assertEqual(daily.return_pct.notna().sum(), 0)
        self.assertEqual(daily.target_up.notna().sum(), 0)

    def test_next_session_skips_holiday_but_last_outcome_stays_missing(self):
        daily, _, _ = prepare_prices(self.prices(["2024-11-27", "2024-11-29"]), "2024-11-27", "2024-11-30")
        self.assertEqual(daily.target_up.iloc[0], 1)
        self.assertTrue(pd.isna(daily.target_up.iloc[-1]))

    def test_news_after_early_close_moves_to_next_actual_close(self):
        schedule = mcal.get_calendar("NYSE").schedule("2024-11-27", "2024-12-02")
        frame = pd.DataFrame({"ticker": ["AAPL"] * 3,
                              "created_at": ["2024-11-29T17:59:00Z", "2024-11-29T18:00:00Z", "2024-11-29T18:01:00Z"],
                              "headline": ["Apple"] * 3, "link": ["a", "b", "c"]})
        aligned = align_news(frame, schedule)
        self.assertEqual(aligned.cutoff_date.dt.strftime("%Y-%m-%d").tolist(), ["2024-11-29", "2024-11-29", "2024-12-02"])

    def test_exact_duplicate_keeps_one_story_instead_of_deleting_both(self):
        schedule = mcal.get_calendar("NYSE").schedule("2024-11-27", "2024-12-02")
        frame = pd.DataFrame({"ticker": ["AAPL", "AAPL"], "created_at": ["2024-11-29T17:59:00Z"] * 2,
                              "headline": ["Apple earnings"] * 2, "link": ["https://example.test/story"] * 2})
        aligned = align_news(frame, schedule)
        self.assertEqual(aligned.duplicate_exact_record.sum(), 2)
        self.assertEqual(aligned.exclude_duplicate_copy.sum(), 1)
        self.assertEqual(aligned.loc[~aligned.exclude_duplicate_copy].cutoff_date.notna().sum(), 1)


if __name__ == "__main__":
    unittest.main()
