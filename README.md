# Financial news and stock direction

We want to test whether adding financial headlines improves next-trading-day direction prediction beyond historical market data. The current work covers collection and EDA; the model comparison has not been run.

## Files to review

- `reports/financial_news_eda_report.docx`: report with the findings, target definition, planned comparison and all nine figures.
- `src/eda_joyce.ipynb`: EDA code, explanations and saved plots. Open it to read the outputs; rerunning requires the local data files.
- `src/collect_data_improved.ipynb`: Alpaca collection with additional checks and a separate Yahoo section. Collection is off by default.
- `src/collect_data.ipynb`: Carmen's original Alpaca cells and outputs, with Joyce's Yahoo section appended. The original Alpaca cells can make requests if run.
- `docs/DATA_COLLECTION.md`: sources, exact request ranges, saved fields, file locations and steps to reproduce the downloads.

## Contributions and data sources

Hung-Jen Wang added the early API exploration, merged from the `michael` branch through PR #1. Carmen added the Alpaca collection notebook and its saved stock/year counts and price coverage tables.

Joyce added Yahoo and EODHD collection, the extended Alpaca workflow, nine EDA plots, further data checks and the report. The first two EDA plots use Carmen's saved summaries. The other seven use actual rows from the added sample.

| Source | Stocks | Period requested | Evidence available here |
| --- | --- | --- | --- |
| Original Alpaca collection | AAPL/JNJ news; AAPL/JNJ/SPY prices | January 2020 to October 2026 | Saved notebook summaries; original raw files still needed |
| Added Yahoo prices | AAPL, AMZN, JNJ, SPY | `2020-01-01 <= NY session date < 2026-10-16` | 6,824 local price rows inspected |
| Added EODHD demo news | AAPL, AMZN | `2024-01-01 <= UTC time < 2025-01-01` | 10,817 local ticker-news rows inspected |

The added sample is stored separately. AMZN was included because the public news demo supports it; the team still needs to choose the final stocks, sources and dates.

## Setup

The environment used for this work is recorded in `environment.yml` and `requirements-eda.txt`.

```bash
conda env create -f environment.yml
conda activate finmedia-eda
python -m ipykernel install --user --name finmedia-eda --display-name "Python (finmedia EDA)"
```

## Reproducing the collection

Run these commands from the project folder. The defaults show the plan or inspect saved files without making requests:

```bash
python src/collect_public_prices.py
python src/collect_public_news.py
```

To explicitly request the added sample:

```bash
python src/collect_public_prices.py --collect
python src/collect_public_news.py --collect
```

Yahoo uses an undocumented public chart endpoint. EODHD uses its documented public `demo` token with limited supported stocks. Those collectors do not load private credentials. New requests may return different rows or be restricted; check the saved run status.

For Alpaca, use `src/collect_data_improved.ipynb`, create this project's private `.env` containing `API_KEY` and `SECRET_KEY`, and enable `RUN_COLLECTION` when ready. The account must have access to the selected SIP feed. See the collection guide for exact date bounds and output files. The original Alpaca download was not rerun during this work.

## Reading and rerunning the EDA

The EDA notebook has nine saved plots that can be viewed without data or API access. Its code uses:

- `eda_saved_outputs.py` to extract and plot Carmen's saved summary tables.
- `supplemental_eda.py` to check the added rows, calculate returns and labels, and align news with actual NYSE closes.
- `raw_eda.py` to check the original Alpaca files when available.

To rerun all EDA cells, these added files must exist locally:

```text
data/supplemental/yahoo_prices/prices.parquet
data/supplemental/eodhd_news/news.parquet
data/supplemental/eodhd_news/collection_run.json
```

Keep the collection manifests and raw-response archives alongside the downloaded tables for provenance and cache checks. They stay outside Git. The original-data check separately expects `data/raw/news/AAPL.parquet`, `data/raw/news/JNJ.parquet` and `data/raw/prices.parquet`; it reports missing files when they are absent.

Missing trading sessions are left empty. News after a close moves to the next cutoff, with holidays and early closes handled by the NYSE calendar. Exact-midnight UTC news is left out of daily pairing until its precision can be checked. Monthly totals retain those records.

## Planned model comparison

Both models use the same stock-days and label:

```text
y = 1 if next trading day's adjusted close > today's adjusted close
y = 0 if it is lower or equal
```

A missing next-session price leaves the label missing. Outperforming SPY is a separate return-based question. We plan chronological splits, with vocabulary, scaling and tuning fitted within the training portion and the final test period held out.

There are 500 stock-days in the added 2024 news/price pairing. The 10,817 headline records are not 10,817 independent prediction observations. A near-zero count/return correlation does not answer whether headline wording helps the model.

## Checks

```bash
python -m unittest discover -s tests -v
```

The tests use temporary fixtures and fake API clients, not live collection. Fixtures are not included in the actual EDA.

## Sharing

Code, notebooks with aggregate outputs, figures and the Word report can be reviewed here. Raw provider files, full article text, credentials, environments, caches and machine-specific run summaries stay outside Git. Confirm suitable provider terms before redistributing its data or using it in a public submission. The sharing ZIP is a review copy with saved outputs; it does not contain the raw files needed to rerun the full EDA.
