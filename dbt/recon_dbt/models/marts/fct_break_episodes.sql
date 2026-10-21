-- Break episodes: one row per unbroken run of break days for a security.
--
-- A security flagged on Mon, Tue, Wed and again Fri is two episodes. The gap
-- on Thursday means the break cleared and then came back, which an ops team
-- treats as a new item with its own age.
--
-- "Consecutive" means consecutive TRADING days (days that appear in the recon),
-- so a break that runs Friday into Monday is one episode, not two.
--
-- Technique: gaps and islands. Number every trading day (day_no), number each
-- security's break days in order (row_number), and subtract. Days in the same
-- unbroken run all give the same difference, so that difference labels the run.
--
-- Open means the episode is still flagged on the latest date in the recon.
-- Age is the number of trading days in the episode (through the latest date
-- while it is open).
with calendar as (
    select
        as_of_date,
        row_number() over (order by as_of_date) as day_no
    from (select distinct as_of_date from {{ ref('fct_recon_positions') }}) d
),

break_days as (
    select r.security_id, r.as_of_date, r.recon_status, c.day_no
    from {{ ref('fct_recon_positions') }} r
    join calendar c on c.as_of_date = r.as_of_date
    where r.is_break
),

labelled as (
    select
        *,
        day_no - row_number() over (partition by security_id order by day_no) as island_id
    from break_days
),

episodes as (
    select
        security_id,
        island_id,
        min(as_of_date)                                            as episode_start,
        max(as_of_date)                                            as episode_end,
        max(day_no)                                                as end_day_no,
        count(*)                                                   as days_in_break,
        (array_agg(recon_status order by as_of_date))[1]           as first_status,
        (array_agg(recon_status order by as_of_date desc))[1]      as last_status
    from labelled
    group by security_id, island_id
),

latest as (
    select max(day_no) as latest_day_no, max(as_of_date) as latest_date from calendar
)

select
    e.security_id,
    e.episode_start,
    e.episode_end,
    e.days_in_break,
    e.first_status,
    e.last_status,
    (e.end_day_no = l.latest_day_no) as is_open,
    l.latest_date                    as as_of_latest_date,
    case
        when e.days_in_break <= 2  then '1-2 days'
        when e.days_in_break <= 5  then '3-5 days'
        when e.days_in_break <= 10 then '6-10 days'
        when e.days_in_break <= 30 then '11-30 days'
        else '31+ days'
    end as age_bucket
from episodes e
cross join latest l
