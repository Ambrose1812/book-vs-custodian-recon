-- One row per ticker per trading day. Every Tiingo ingest re-fetches the full
-- date range, so a day can appear once per ingest_date; the most recent ingest
-- wins, which also means a restated price replaces the old one.
select distinct on (ticker, date::date)
    ticker,
    date::date       as price_date,
    close            as close_price,
    "splitFactor"    as split_factor,
    "divCash"        as dividend_cash,
    ingest_date,
    _source_file,
    _loaded_at
from {{ source('raw', 'prices') }}
order by ticker, date::date, ingest_date desc, _loaded_at desc
