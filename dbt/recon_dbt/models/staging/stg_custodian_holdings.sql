-- One row per security per statement date, as the custodian reports it.
-- Zero positions are absent from the statement, as on a real one.
--
-- Each custodian ingest delivers the full statement history, so the latest
-- ingest replaces the earlier ones as a whole. Picking the latest row per key
-- instead would be wrong: a position that is absent from the new statement
-- (closed out, so not reported) would survive from an older ingest as a phantom
-- holding. (A real custodian sends one statement per date; there the rule would
-- be "latest ingest per as_of_date", applied to the whole statement.)
with latest_ingest as (
    select max(ingest_date) as ingest_date
    from {{ source('raw', 'custodian_holdings') }}
)

select distinct on (h.as_of_date, h.security_id)
    h.as_of_date,
    h.security_id,
    h.quantity::numeric as quantity,
    h.ingest_date,
    h._source_file,
    h._loaded_at
from {{ source('raw', 'custodian_holdings') }} as h
inner join latest_ingest using (ingest_date)
order by h.as_of_date, h.security_id, h._loaded_at desc
