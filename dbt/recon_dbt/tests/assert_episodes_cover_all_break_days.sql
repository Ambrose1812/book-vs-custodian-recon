-- Conservation check: every break day in the recon belongs to exactly one
-- episode, so the episode lengths must add up to the number of break rows.
-- Returns a row only if the two totals disagree.
with episode_days as (
    select coalesce(sum(days_in_break), 0) as total from {{ ref('fct_break_episodes') }}
),
break_rows as (
    select count(*) as total from {{ ref('fct_recon_positions') }} where is_break
)
select e.total as episode_days, b.total as break_rows
from episode_days e
cross join break_rows b
where e.total <> b.total
