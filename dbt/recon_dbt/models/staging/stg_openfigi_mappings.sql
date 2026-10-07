select
    figi,
    "compositeFIGI"    as composite_figi,
    "shareClassFIGI"   as share_class_figi,
    name,
    ticker,
    "exchCode"         as exchange_code,
    "securityType"     as security_type,
    "securityType2"    as security_type_2,
    "marketSector"     as market_sector,
    ingest_date,
    _source_file,
    _loaded_at
from {{ source('raw', 'openfigi_mappings') }}
where match_status = 'matched'