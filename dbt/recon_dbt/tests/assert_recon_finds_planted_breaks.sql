-- Simulation check: score the recon against the planted-break answer key.
-- Returns the failures; zero rows means the recon passed all three checks.
--   missed_break          a security with a planted error that the recon never flagged
--   false_positive        a security with no planted error that the recon flagged
--   wrong_detection_date  a planted error the recon flagged, but its first flag is not
--                         on the first trading day the error exists (too early means
--                         something else was flagged, too late means detection lagged)
-- Uses the most recent answer key. Exists only because the custodian feed is
-- simulated; real data has no answer key.
-- Why the date check: the first check only asks "was this security flagged on ANY
-- day". A recon that flagged it for the wrong reason, or months late, would pass.
-- effective_date is the day the error starts to show: the settlement date of the bad
-- trade, or the ex-date of the split the custodian skipped.
with latest_key as (
    select security_id, break_type, effective_date::date as effective_date
    from {{ source('raw', 'planted_breaks') }}
    where ingest_date = (select max(ingest_date) from {{ source('raw', 'planted_breaks') }})
),

trading_days as (
    select distinct price_date as as_of_date
    from {{ ref('int_prices_split_indexed') }}
),

expected as (
    select
        k.security_id,
        k.break_type,
        (select min(d.as_of_date) from trading_days d
         where d.as_of_date >= k.effective_date) as expected_first_flag
    from latest_key k
),

flagged as (
    select security_id, min(as_of_date) as actual_first_flag
    from {{ ref('fct_recon_positions') }}
    where is_break
    group by security_id
)

select 'missed_break' as problem, e.security_id, e.break_type,
       e.expected_first_flag, null::date as actual_first_flag
from expected e
left join flagged f on f.security_id = e.security_id
where f.security_id is null

union all

select 'false_positive', f.security_id, null,
       null::date, f.actual_first_flag
from flagged f
left join expected e on e.security_id = f.security_id
where e.security_id is null

union all

select 'wrong_detection_date', e.security_id, e.break_type,
       e.expected_first_flag, f.actual_first_flag
from expected e
join flagged f on f.security_id = e.security_id
where f.actual_first_flag is distinct from e.expected_first_flag
