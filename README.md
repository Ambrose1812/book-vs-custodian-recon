# Book vs. Custodian Reconciliation Pipeline

Does our book of record match the custodian, and where are the breaks?

## Why this matters
A fund's internal records (the book of record) and its custodian bank's records
should agree on what is owned. Differences are called breaks and need
investigation. This project models that daily process end to end.

## Status
- **Phase 1 (complete):** batch pipeline from raw sources to split-adjusted positions, orchestrated by Airflow.
- **Phase 2 (planned):** simulated custodian feed, break detection and classification, break aging and KPIs.

## Architecture
```
OpenFIGI + Tiingo + simulated transactions
        -> Python ingest -> Parquet (landing zone, partitioned by ingest date)
        -> Postgres `raw` (append-only history)
        -> dbt: staging (latest ingest wins) -> intermediate -> marts
        -> Airflow (LocalExecutor) runs the whole chain; everything in Docker
```

| Layer | Models | Purpose |
| --- | --- | --- |
| staging | `stg_openfigi_mappings`, `stg_prices`, `stg_transactions` | Dedupe to the latest ingest per record |
| intermediate | `int_prices_split_indexed` | Cumulative split factor per ticker and date |
| marts | `dim_security_master`, `fct_positions` | Security dimension; split-adjusted position and market value per trade |

## Key design decisions
- **Raw is append-only; staging picks the latest ingest.** Reruns never overwrite history, and a corrected source row replaces the old one downstream.
- **Idempotent loads.** The loader deletes and inserts one `ingest_date` partition per table in a single transaction, and holds a Postgres advisory lock so two loads cannot overlap.
- **Splits use an as-of basis (custodian style).** Prices stay raw; shares are rebuilt as `F_D x sum(q_i / F_i)` using the cumulative split factor at each date. A trade on the split's ex-date is not adjusted.
- **Tests.** 11 dbt data tests plus 2 unit tests (mocked inputs, expected outputs for the split math). A snapshot-and-`EXCEPT` check confirmed the rewritten `fct_positions` matched the previous output.

## Run it
1. Copy `.env.example` to `.env` and fill in `OPENFIGI_API_KEY` and `TIINGO_API_KEY`.
2. `docker compose up -d --build` (Postgres on host port 5433, Airflow UI at http://localhost:8080).
3. Open Airflow, unpause `recon_pipeline`, and trigger it. The DAG runs: OpenFIGI ingest, reference load, security master, then transactions seed and Tiingo ingest in parallel, raw load, `dbt run`, `dbt test`.

## Data sources
- OpenFIGI: real identifier mappings
- Tiingo: daily prices (raw `close` plus `splitFactor`)
- Transactions: **simulated**, generated once by `ingest/simulate_transactions.py` and kept
- Custodian feed: **simulated** (Phase 2)

## Known limitations
- Small simulated scale (20 securities, 350 transactions, about 2,400 price rows).
- The DAG is manually triggered, with no schedule yet.
- Only splits are handled; dividends and other corporate actions are not.
- Idempotent reruns are tested with unchanged prices; a changed price replacing an old one is not yet covered by a test.
- Depth is prioritized over flash.
