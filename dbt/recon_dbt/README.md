# recon_dbt

The dbt project for the book-vs-custodian reconciliation pipeline. See the [top-level README](../../README.md) for what the project does and how to run it, and [docs/decisions.md](../../docs/decisions.md) for the design reasoning.

## Layers
- `models/staging`: one model per source; picks the latest ingest per record.
- `models/intermediate`: cumulative split factors per ticker and date; the book's daily holdings on trade-date and settled bases.
- `models/marts`: security dimension, split-adjusted positions, the book-vs-custodian recon, break episodes, and daily KPIs.

## Tests
- Column tests and singular tests (including `assert_recon_finds_planted_breaks`, which scores the recon against the simulator's answer key) run with `dbt test`.
- Unit tests with mocked inputs live in `models/marts/unit_tests.yml`.

In the normal setup, Airflow runs `dbt run` and `dbt test` as part of the `recon_pipeline` DAG.
