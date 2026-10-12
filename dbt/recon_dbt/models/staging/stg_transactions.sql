select
    transaction_id,
    security_id,
    trade_date,
    settlement_date,
    side,
    quantity,
    price,
    ingest_date,
    _source_file,
    _loaded_at
from {{ source('raw', 'transactions') }}