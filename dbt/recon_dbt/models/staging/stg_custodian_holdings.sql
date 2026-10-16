-- One row per security per statement date, as the custodian reports it.
-- Zero positions are absent from the statement, as on a real one.
-- If a date is re-delivered in a later ingest, the most recent ingest wins.
select distinct on (as_of_date, security_id)
    as_of_date,
    security_id,
    quantity::numeric as quantity,
    ingest_date,
    _source_file,
    _loaded_at
from {{ source('raw', 'custodian_holdings') }}
order by as_of_date, security_id, ingest_date desc, _loaded_at desc
