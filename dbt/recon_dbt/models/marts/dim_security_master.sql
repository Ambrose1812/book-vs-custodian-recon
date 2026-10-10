select
    figi as security_id,
    figi,
    composite_figi,
    share_class_figi,
    name,
    ticker,
    exchange_code,
    security_type,
    security_type_2,
    market_sector
from {{ ref('stg_openfigi_mappings') }}