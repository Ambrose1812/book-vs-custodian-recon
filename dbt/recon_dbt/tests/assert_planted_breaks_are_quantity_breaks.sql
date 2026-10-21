{{ config(severity='warn') }}
-- Classification check (warns, does not fail the build): on the first day each
-- planted error is flagged, the recon should call it a quantity_break.
--
-- Why that is the expected type: in this simulation every planted cause (a missing,
-- 10x or duplicated trade, or a skipped split) leaves BOTH sides holding the security
-- with different numbers, which is the definition of a quantity_break. Today all 14
-- planted breaks come out that way.
--
-- Why it only warns: the detection test (assert_recon_finds_planted_breaks) is the
-- hard gate. A different seed could legitimately produce another status, for example
-- a missing trade that leaves the custodian at exactly zero would be
-- missing_on_custodian. A warning here means "look at the classification", not
-- "the recon is broken".
with latest_key as (
    select security_id, break_type
    from {{ source('raw', 'planted_breaks') }}
    where ingest_date = (select max(ingest_date) from {{ source('raw', 'planted_breaks') }})
),

first_flag as (
    select security_id, min(as_of_date) as first_flag_date
    from {{ ref('fct_recon_positions') }}
    where is_break
    group by security_id
)

select k.security_id, k.break_type, r.as_of_date, r.recon_status
from latest_key k
join first_flag f on f.security_id = k.security_id
join {{ ref('fct_recon_positions') }} r
  on r.security_id = f.security_id
 and r.as_of_date = f.first_flag_date
where r.recon_status <> 'quantity_break'
