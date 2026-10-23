# finmedia-stock-pred
Do financial media content help predict next-day stock returns?

*Can the news help telling us where a stock is headed tomorrow? Let's find out!*

## Overview

This project predicts whether a stock's closing price will rise on the next trading day, using price history and the sentiment of financial news articles scored with FinBERT. We compare a price-only model with a model that also uses news sentiment. Curious how it turned out? 

Fair warning: markets are hard to predict, so we are not chasing a perfect score here. This project is more of an exploration on whether the mood of the news carry any signal that prices alone don't? And what if it does...!

Want to dig deeper? Here are some decent places to start:

* [Yahoo Finance](https://finance.yahoo.com/): stock prices, charts, and the latest news for any ticker
* [Benzinga](https://www.benzinga.com/): the news outlet behind the articles in our data
* [FinBERT on Hugging Face](https://huggingface.co/ProsusAI/finbert): the sentiment model we use, you might able to find how it works here



## Quick Start

If you wanna run it yourself, here's how.

1. Clone this repo
   `git clone https://github.com/CarmenYan/finmedia-stock-pred.git`
2. Create the environment
   `conda env create -f environment.yml && conda activate data1030-proj`
3. Get free API keys from [Alpaca](https://alpaca.markets/) and put them in `.env` in the project root (this file is git-ignored):
   `API_KEY=...` and `SECRET_KEY=...`
4. Run the notebooks in `src/` in order: `collect_data.ipynb` → `clean_data.ipynb`
   (Downloading news takes a while, so grab a coffee!)

## Data

News articles: collected from the Alpaca News API (articles published by Benzinga), January 2020 to October 2026.
Docs: https://docs.alpaca.markets/docs/news-api

Daily stock prices: collected from the Alpaca Market Data API, January 2020 to October 2026.
Docs: https://docs.alpaca.markets/docs/about-market-data-api


The data files (`data/raw/` and `data/processed/`) are not included in this repo because of their size. You might run notebooks in `src/` in order to download them.


## Repository structure

```
├── data/
│   ├── raw/                
│   ├── processed/            
│   └── data_description.txt  
├── figures/                  
├── results/                  
├── report/                   
├── src/
│   ├── collect_data.ipynb 
│   ├── clean_data.ipynb     
│   └── scratch/              # initial API exploration 
├── environment.yml
├── .gitignore
├── LICENSE
└── README.md
```

## Environment

Developed with Python 3.12. 

- `python` 3.12
- `pandas` 3.0.6
- `numpy` 1.26.4
- `alpaca-py` 0.44.0
- `transformers` 4.44.2
- `torch` 2.5.1
- `pyarrow` 26.0.0
- `python-dotenv` 1.2.3
- `yfinance` 1.7.0
- `matplotlib` 3.11.0
- `scikit-learn` 1.9.0
- `beautifulsoup4` 4.15.0
