-- Security dimension, Type 2 (slowly changing dimension): one row per version of a
-- security. A new version starts whenever any tracked attribute changes between two
-- OpenFIGI snapshots (ticker, name, exchange, type, sector, composite or share-class
-- FIGI). dim_security_master stays as the current view; this table keeps history,
-- so a fact can be joined to the version that was true on its own date.
--
-- Built from the raw history, not with a dbt snapshot: raw keeps every ingest, so the
-- whole table can be rebuilt from scratch and a clean clone gives the same answer.
-- A dbt snapshot records state at the moment it runs, and that history would be lost
-- on a rebuild.
--
-- Dates, read carefully:
--   first_seen_ingest_date  the ingest where this version first appeared, i.e. when
--                           WE learned it (knowledge time), not when the change
--                           happened in the market
--   valid_from / valid_to   the window this version is treated as true for joins.
--                           valid_to is exclusive. The first version of each security
--                           starts at 1900-01-01 because we have no earlier history and
--                           assume the first thing we saw was always true; without that,
--                           a June trade could not join to anything first seen in October.
--                           The current version ends at 9999-12-31.
with snapshots as (
    select
        *,
        -- One fingerprint of every tracked attribute. coalesce + a separator so a null
        -- in one column can never look the same as a value moved into the next column.
        md5(concat_ws('|',
            coalesce(ticker, '~'), coalesce(name, '~'), coalesce(exchange_code, '~'),
            coalesce(security_type, '~'), coalesce(security_type_2, '~'),
            coalesce(market_sector, '~'), coalesce(composite_figi, '~'),
            coalesce(share_class_figi, '~')
        )) as attributes_hash
    from {{ ref('stg_openfigi_mapping_history') }}
),

-- Keep a snapshot only if it differs from the one before it for the same security.
-- Comparing to the previous snapshot (not "distinct attributes") is what makes a change
-- back to an earlier value (A -> B -> A) count as a third version.
changes as (
    select *
    from (
        select
            *,
            lag(attributes_hash) over (partition by security_id order by ingest_date) as prev_hash
        from snapshots
    ) s
    where prev_hash is null or prev_hash <> attributes_hash
),

versions as (
    select
        *,
        row_number() over (partition by security_id order by ingest_date) as version_number,
        lead(ingest_date) over (partition by security_id order by ingest_date) as next_change_date
    from changes
)

select
    {{ dbt_utils.generate_surrogate_key(['security_id', 'ingest_date']) }} as security_key,
    security_id,
    version_number,
    ticker,
    name,
    exchange_code,
    security_type,
    security_type_2,
    market_sector,
    composite_figi,
    share_class_figi,
    ingest_date                                                          as first_seen_ingest_date,
    case when version_number = 1 then date '1900-01-01' else ingest_date end as valid_from,
    coalesce(next_change_date, date '9999-12-31')                        as valid_to,
    next_change_date is null                                             as is_current
from versions
