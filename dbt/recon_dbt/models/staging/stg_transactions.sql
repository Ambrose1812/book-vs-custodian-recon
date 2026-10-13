-- One row per transaction_id; if the same id arrives in several ingests
-- (a correction or a re-delivery), the most recent ingest wins.
select distinct on (transaction_id)
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
order by transaction_id, ingest_date desc, _loaded_at desc
