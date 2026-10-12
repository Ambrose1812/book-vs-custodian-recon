select
    ticker,
    date::date       as price_date,
    close            as close_price,
    "splitFactor"    as split_factor,
    "divCash"        as dividend_cash,
    ingest_date,
    _source_file,
    _loaded_at
from {{ source('raw', 'prices') }}