-- Open breaks right now, by type and age bucket. Type is the status the break
-- shows today (last_status), because a break can change type while it is open.
select
    last_status as break_type,
    age_bucket,
    count(*)    as open_breaks
from {{ ref('fct_break_episodes') }}
where is_open
group by last_status, age_bucket
