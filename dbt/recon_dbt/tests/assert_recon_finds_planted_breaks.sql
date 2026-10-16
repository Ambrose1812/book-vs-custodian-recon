-- Simulation check: score the recon against the planted-break answer key.
-- Returns the failures; zero rows means the recon found every planted break
-- and raised no false alarm on the control securities.
--   missed_break    a security with a planted error that the recon never flagged
--   false_positive  a security with no planted error that the recon flagged
-- Uses the most recent answer key. Exists only because the custodian feed is
-- simulated; real data has no answer key.
with latest_key as (
    select distinct security_id
    from {{ source('raw', 'planted_breaks') }}
    where ingest_date = (select max(ingest_date) from {{ source('raw', 'planted_breaks') }})
),

flagged as (
    select distinct security_id
    from {{ ref('fct_recon_positions') }}
    where is_break
)

select 'missed_break' as problem, k.security_id
from latest_key k
left join flagged f on f.security_id = k.security_id
where f.security_id is null

union all

select 'false_positive' as problem, f.security_id
from flagged f
left join latest_key k on k.security_id = f.security_id
where k.security_id is null
