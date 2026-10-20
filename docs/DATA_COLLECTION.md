# Data collection and reproduction

## Original collection and added work

The original work is recorded in the repository history. Hung-Jen Wang's API exploration was committed as `1659df6` and merged from `michael` through PR #1. Carmen's collection notebook and saved outputs were added in `082ba68`, following `8840ed3`.

The original notebook contains saved summaries for 23,674 AAPL and 4,219 JNJ ticker-news records, plus 1,706 daily price rows each for AAPL, JNJ and SPY. Those original Parquet files were not available in this checkout. The first two EDA figures use the saved tables; the original collection was not rerun and its raw-row quality has not been checked here.

Joyce added the collectors and checks described below. Yahoo and EODHD files are stored in `data/supplemental/` so they can be evaluated separately from the original Alpaca sample. All chart images were generated locally from the stated tables or rows.

## Alpaca collection

Entry point: `src/collect_data_improved.ipynb`; implementation: `src/collect_pipeline.py`.

The defaults are AAPL and JNJ headlines and AAPL, JNJ and SPY daily prices. The improved collector uses explicit UTC bounds:

```text
start included: 2020-01-01T00:00:00Z
end excluded:   2026-10-16T00:00:00Z
price timeframe: 1 day
price feed: SIP
price adjustment: ALL
```

These UTC bounds are not the same as New York calendar-day bounds. Change them deliberately if a different interval is needed. The original notebook supplied naive datetime values; this implementation makes the timezone explicit for new runs.

News is requested in non-overlapping yearly intervals. Alpaca's SDK handles pagination automatically; no total-result limit is supplied. Returned records are filtered to each requested interval. Price collection requests all selected symbols and the benchmark together.

Private keys are read only from the project's `.env` when collection is enabled and a new request is needed. Keep `API_KEY` and `SECRET_KEY` out of notebooks and Git. Requests use the chosen feed; an entitlement error does not trigger a silent change to IEX.

Each saved chunk has a manifest recording its settings, package versions, schema, row count, time range and SHA-256 hash. Matching valid chunks can be reused after an interrupted run. Temporary errors have bounded retries; access errors stop the request. Empty completed responses are recorded so they can be investigated.

Saved news fields include ticker, article ID, publication time, update time, headline, source, linked symbols, URL and retrieval time. Combined files keep the latest returned version of each ticker/article ID and retain records without IDs. News may legitimately appear under more than one stock. Update times cannot reconstruct exactly what text was available at an earlier cutoff.

Outputs:

```text
data/raw/news/chunks/<ticker>/...parquet
data/raw/news/AAPL.parquet
data/raw/news/JNJ.parquet
data/raw/prices.parquet
data/raw/collection_run.json
matching .manifest.json files
```

Collection is disabled by default. Install the dependencies, supply the private project `.env`, review the plan and enable `RUN_COLLECTION` to make new Alpaca requests.

## Yahoo daily prices

Entry points: the Yahoo sections in both collection notebooks, or `src/collect_public_prices.py`.

The collector requests each of AAPL, AMZN, JNJ and SPY from:

```text
https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
```

The requested range is `2020-01-01 <= New York session date < 2026-10-16`. `period1` and `period2` are Unix timestamps calculated from midnight in `America/New_York`, with `interval=1d`, `events=div,splits` and `includeAdjustedClose=true`. The returned rows are filtered by New York session date. The last included date is October 15, 2026.

The endpoint is an undocumented public interface. No private key is used. The collector checks response status and structure, keeps the supplied OHLC and volume columns, and stores the supplied adjusted close separately. It does not assume Yahoo's quote adjustment conventions match Alpaca's. Missing adjusted close causes a validation failure rather than being replaced with raw close.

Raw response bytes, per-symbol normalized files and manifests are retained. Cache reuse checks request settings, package versions, schema, row counts and hashes. Bounded retries apply to temporary failures. Access blocks and rate-limit responses are respected; the collector does not switch identities or bypass a gate.

Outputs:

```text
data/supplemental/yahoo_prices/raw/<symbol>.json
data/supplemental/yahoo_prices/cache/<symbol>.parquet
data/supplemental/yahoo_prices/cache/<symbol>.manifest.json
data/supplemental/yahoo_prices/prices.parquet
data/supplemental/yahoo_prices/manifest.json
```

The inspected retrieval has 1,706 rows per symbol, or 6,824 total, from January 2, 2020 through October 15, 2026. All four series match the expected NYSE sessions and pass the implemented date, numeric and OHLC checks. This is a current provider snapshot, not independently verified point-in-time price history.

```bash
python src/collect_public_prices.py           # Inspect local cache only
python src/collect_public_prices.py --collect # Allow requests if needed
```

In either notebook, `RUN_YAHOO_COLLECTION=False` keeps requests off. The Yahoo section runs independently of the original Alpaca cells.

## EODHD public demo news

Entry point: `src/collect_public_news.py`; endpoint: `https://eodhd.com/api/news`.

This collection uses EODHD's documented public `demo` token. AAPL and AMZN were chosen from the demo's supported stocks. The range is `2024-01-01 <= publication time UTC < 2025-01-01`.

For each ticker, the collector requests 12 monthly windows, or 24 ticker/month windows in total. Parameters include the symbol with `.US`, `from`, `to`, `limit=1000`, `offset` and `fmt=json`. The API's inclusive `to` date is set to the day before the internal exclusive end. Offset increases by the page size when needed, up to the documented 9,000 cap. Requests are spaced by at least 1.1 seconds, with at most two attempts under the default configuration.

The collector saves exact responses and their hashes before normalizing the fields used in the EDA. It checks timestamp parsing and requested date bounds, detects repeated pages and records empty or capped windows as issues. Exact duplicates are identified by ticker, full URL, title and UTC publication time; incomplete keys are retained for review. It stops on access failures and rate-limit responses.

The normalized table includes ticker, provider publication time, headline, URL, URL host, linked symbols, tags, available sentiment metadata, retrieval time, requested window and response hash. URL hosts identify where a link points, which may differ from the original publisher. Provider sentiment is not used as a historical predictor because its availability time is unverified.

Outputs:

```text
data/supplemental/eodhd_news/raw/...
data/supplemental/eodhd_news/news.parquet
data/supplemental/eodhd_news/collection_run.json
```

The inspected sample has 10,817 ticker-news records: 5,298 AAPL and 5,519 AMZN, with 10,038 distinct URLs. Its completed request status does not establish that the underlying news archive is complete. The late-year drop in retrieved counts, exact-midnight timestamps and headline relevance require further checks.

```bash
python src/collect_public_news.py           # Show the collection plan
python src/collect_public_news.py --collect # Allow public demo requests
```

Raw responses may contain article content. Keep provider files local while the team checks suitable academic access and redistribution terms. The Git contribution and sharing ZIP contain code and aggregate outputs, not raw provider data.

## EDA inputs and alignment

`src/eda_joyce.ipynb` reads local files only. Its nine saved plots can be read without running it. To rerun, retain the collection folder structure and manifests, install `requirements-eda.txt`, and select the project environment. Current added Parquets are required by the first code cell; a code-only checkout is not a complete data bundle.

Price dates are matched to the NYSE calendar before daily returns and labels are computed. Missing sessions stay missing. News is assigned to the first actual exchange close at or after its publication time, so stories after a close enter a later observation. Exact-midnight UTC records are excluded from daily pairing until their precision is checked, but remain in monthly counts. Boundary windows outside the observed story range are omitted. These rules produce 250 stock-days per ticker in the 2024 comparison; archive completeness and historical text availability remain unverified.

## Source documentation

- [Alpaca historical news client](https://alpaca.markets/sdks/python/api_reference/data/news/historical.html)
- [EODHD news API and public demo](https://eodhd.com/financial-apis/stock-market-financial-news-api)
- [EODHD terms](https://eodhd.com/financial-apis/terms-conditions)
- [NYSE calendar](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html)
