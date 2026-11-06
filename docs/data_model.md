# Data model

Draft v1. For every table: the **grain** (what exactly one row means), its **type** in Kimball terms, and the **test that enforces the grain**. If a table has no grain test, that is a gap.

Kimball terms used here:

- **Transaction fact**: one row per business event, when it happens.
- **Periodic snapshot fact**: one row per thing per regular period (here: per security per trading day), whether or not anything happened.
- **Accumulating snapshot fact**: one row per process instance, updated as it moves through milestones (opened, aged, closed).
- **Dimension**: descriptive context (who/what/where) that facts join to.
- **Semi-additive measure**: can be summed across some dimensions but not time. Share quantity is the classic one: you can sum positions across securities on one day, but summing one security's quantity across days is meaningless.

## Layers

`raw` (every ingest kept, nothing deleted) → `staging` (one clean row per business key, latest data wins) → `intermediate` (reusable calculation) → `marts` (facts and dimensions that people query) → `eval` (simulation scoring only).

## Staging

| Model | Grain (one row per...) | Grain test |
|---|---|---|
| `stg_openfigi_mappings` | FIGI (latest ingest) | unique on `figi` |
| `stg_transactions` | transaction_id (latest ingest) | unique on `transaction_id` |
| `stg_prices` | ticker + price_date (latest ingest) | unique combination |
| `stg_custodian_holdings` | as_of_date + security_id, from the latest **full snapshot** only | unique combination |

Rule that differs by feed type: the custodian feed is a snapshot, so staging takes the latest ingest as a whole. The others are keyed deltas, so latest row per key wins.

## Intermediate

| Model | Grain | Type | Grain test |
|---|---|---|---|
| `int_prices_split_indexed` | ticker + price_date | Calculation (running split index) | **missing** |
| `int_book_daily_holdings` | security + trading day, from the security's first trade | **Periodic snapshot** (two measures: trade-basis and settled-basis quantity) | **missing** |

`int_book_daily_holdings` is a periodic snapshot in everything but name and location. Promoting it to a mart is the next step.

## Marts

| Model | Grain | Kimball type | Grain test |
|---|---|---|---|
| `dim_security_master` | FIGI | Dimension, **Type 1** (overwrite, no history) | unique `security_id` |
| `fct_positions` | transaction | Transaction fact, with a running position (semi-additive) | unique `transaction_id` |
| `fct_holdings_daily` | security + trading day, from the security's first trade (zero-quantity days kept) | **Periodic snapshot**, valued at the day's close; analyst-facing layer over `int_book_daily_holdings` | unique combination |
| `fct_recon_positions` | security + trading day, only where either side holds a position | **Periodic snapshot** (sparse: zero-holding days are absent) | unique combination |
| `fct_break_episodes` | unbroken run of break days for a security | Accumulating-snapshot style (start, end, open flag, age) | unique `security_id` + `episode_start` |
| `fct_break_action_history` | break episode + trading day it was open | Periodic snapshot of an episode | unique combination |
| `fct_break_cause_baseline` | break episode (rules-based cause at its first break day) | Fact (derived) | unique `security_id` + `first_break_date` |
| `fct_break_requires_action` | open break episode | Latest-day slice of the history table | unique combination |
| `fct_recon_daily_kpis` | trading day | Aggregate, one row per day | check `as_of_date` unique |
| `fct_open_breaks_summary` | break type + age bucket (right now) | Aggregate, current state only | **missing** |

## Eval

| Model | Grain | Note |
|---|---|---|
| `eval_cause_scoring` | planted break (one row per planted break, latest answer key) | Simulation only |

## What is solid

- Every business fact has an explicit grain, and most have a test that enforces it.
- Two bases (trade and settled) are kept side by side instead of choosing one. That is the point of the project: the difference between them is the legitimate timing gap.
- The recon table uses a full outer join, so rows that exist on only one side are not silently dropped.

## Gaps to close (in priority order)

1. **No grain tests** on `int_book_daily_holdings`, `int_prices_split_indexed`, `fct_open_breaks_summary`. Cheap to add, high signal.
2. **`dim_security_master` is Type 1.** If a ticker changes, the old ticker is overwritten and history is lost. A Type 2 dimension keeps one row per version with `valid_from` and `valid_to`. Needed for correct point-in-time joins (mastery list #7).
3. ~~The daily holdings snapshot lives only in `intermediate`.~~ Done: `fct_holdings_daily` is a thin mart on top of `int_book_daily_holdings`. The intermediate model stays (the recon and its unit tests depend on it).
4. **No date dimension.** Every fact stores a raw date. A `dim_date` with a trading-day flag, week, month and quarter makes calendar logic one join instead of ad hoc SQL.
5. **One portfolio only.** Real books have funds and accounts. A `dim_account` (or `dim_fund`) would turn the grain into account + security + day. Worth mentioning in the README as a known simplification.
6. **`fct_recon_positions` has quantities only.** Valuation now lives in `fct_holdings_daily`; the recon could join it to size each break in money.

## Open questions for the author

Answer these in your own words before changing anything:

1. Why is `fct_positions` a transaction fact and `fct_recon_positions` a periodic snapshot? What question does each answer?
2. What breaks if `dim_security_master` stays Type 1 and a ticker changes?
3. Why is quantity semi-additive, and what would go wrong if a dashboard summed it over a month?
