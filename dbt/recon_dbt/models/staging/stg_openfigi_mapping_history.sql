-- One row per FIGI per ingest_date: every OpenFIGI snapshot we ever received.
-- stg_openfigi_mappings keeps only the latest ingest per FIGI (the current view);
-- this one keeps them all, so dim_security_history can see when an attribute changed.
-- If one ingest somehow loaded the same FIGI twice, the most recent load wins.
select distinct on (figi, ingest_date)
    figi                as security_id,
    "compositeFIGI"     as composite_figi,
    "shareClassFIGI"    as share_class_figi,
    name,
    ticker,
    "exchCode"          as exchange_code,
    "securityType"      as security_type,
    "securityType2"     as security_type_2,
    "marketSector"      as market_sector,
    ingest_date
from {{ source('raw', 'openfigi_mappings') }}
where match_status = 'matched'
order by figi, ingest_date, _loaded_at desc
