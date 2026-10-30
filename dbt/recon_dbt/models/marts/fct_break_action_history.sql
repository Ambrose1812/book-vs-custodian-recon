-- Daily history of break urgency. One row per security, per break episode, per
-- trading day the episode was open. On each day it shows what the age, the gap,
-- and the requires-action level were AS OF that day, so you can watch a break
-- get more urgent as it ages.
--
-- This is where the level logic lives. fct_break_requires_action is just the
-- latest day of this table, for the open breaks.
--
-- Levels, highest one that fires wins:
--   level 3  escalate: big gap, large share of the position, old, a corporate
--            action, or the same security broke again recently
--   level 2  review: cause unknown, a gap over the review size, or getting old
--   level 1  routine: the rules named a cause and nothing else fired
-- A matched row or a timing difference is not a break, so it never shows up here.
--
-- Thresholds come from vars in dbt_project.yml. They mirror
-- classify/action_policy.py, so change both together.
{% set tol = var('recon_tolerance', 0.001) %}

with trading_days as (
    select
        price_date,
        row_number() over (order by price_date) as day_no
    from (select distinct price_date from {{ ref('int_prices_split_indexed') }}) d
),

-- Look at the previous episode of the same security across all episodes, so a
-- recurrence can see an earlier episode that has already closed.
episodes as (
    select
        e.security_id,
        e.episode_start,
        e.episode_end,
        e.last_status,
        e.is_open,
        ts.day_no as start_day_no,
        te.day_no as end_day_no,
        lag(e.episode_end) over (
            partition by e.security_id order by e.episode_start
        ) as prev_episode_end
    from {{ ref('fct_break_episodes') }} e
    join trading_days ts on ts.price_date = e.episode_start
    join trading_days te on te.price_date = e.episode_end
),

episodes_with_prev as (
    select e.*, tp.day_no as prev_end_day_no
    from episodes e
    left join trading_days tp on tp.price_date = e.prev_episode_end
),

-- One row for each trading day inside an episode. Age on a day is how many
-- trading days the episode has been open up to and including that day.
episode_days as (
    select
        e.*,
        d.price_date                         as as_of_date,
        d.day_no - e.start_day_no + 1        as age_trading_days
    from episodes_with_prev e
    join trading_days d on d.day_no between e.start_day_no and e.end_day_no
),

-- Every position on every recon date, valued at the latest price on or before
-- that date. Quantity and price are both unadjusted for the date, so they are
-- on the same basis.
positions as (
    select
        r.security_id,
        r.as_of_date,
        r.book_quantity_settled_basis,
        r.difference_vs_settled_basis,
        px.close_price
    from {{ ref('fct_recon_positions') }} r
    join {{ ref('dim_security_master') }} sm on sm.security_id = r.security_id
    left join lateral (
        select p.close_price
        from {{ ref('int_prices_split_indexed') }} p
        where p.ticker = sm.ticker
          and p.price_date <= r.as_of_date
        order by p.price_date desc
        limit 1
    ) px on true
),

portfolio_by_date as (
    select
        as_of_date,
        sum(book_quantity_settled_basis * close_price) as portfolio_market_value
    from positions
    group by as_of_date
),

scored as (
    select
        ed.security_id,
        ed.episode_start,
        ed.as_of_date,
        ed.age_trading_days,
        ed.last_status,
        ed.is_open                                                        as episode_is_open,
        c.cause_predicted                                                 as cause,
        abs(p.difference_vs_settled_basis)                                as gap_quantity,
        abs(p.difference_vs_settled_basis) * p.close_price                as gap_market_value,
        abs(p.difference_vs_settled_basis) * p.close_price
            / nullif(pd.portfolio_market_value, 0) * 10000                as gap_bps,
        -- If our book holds nothing, any gap is 100% of the position.
        case
            when abs(p.book_quantity_settled_basis) > {{ tol }}
                then abs(p.difference_vs_settled_basis) / abs(p.book_quantity_settled_basis)
            else 1.0
        end                                                               as relative_gap,
        coalesce(
            ed.start_day_no - ed.prev_end_day_no <= {{ var('recurrence_window_trading_days') }},
            false
        )                                                                 as is_recurrence,
        ed.as_of_date = (select max(as_of_date) from {{ ref('fct_recon_positions') }})
                                                                          as is_latest_date
    from episode_days ed
    join positions p
        on p.security_id = ed.security_id
       and p.as_of_date = ed.as_of_date
    join portfolio_by_date pd on pd.as_of_date = ed.as_of_date
    left join {{ ref('fct_break_cause_baseline') }} c
        on c.security_id = ed.security_id
       and c.first_break_date = ed.episode_start
),

flagged as (
    select
        *,
        coalesce(gap_bps >= {{ var('gap_bps_escalate') }}, false)                 as t_gap_escalate,
        relative_gap >= {{ var('relative_gap_escalate') }}                        as t_relative_gap,
        age_trading_days >= {{ var('age_escalate_trading_days') }}                as t_age_escalate,
        coalesce(cause = 'split_not_applied', false)                              as t_corporate_action,
        coalesce(gap_bps >= {{ var('gap_bps_review') }}, false)                   as t_gap_review,
        age_trading_days >= {{ var('age_review_trading_days') }}                  as t_age_review,
        coalesce(cause = 'unknown', true)                                         as t_cause_unknown
    from scored
)

select
    security_id,
    episode_start,
    as_of_date,
    age_trading_days,
    last_status,
    episode_is_open,
    is_latest_date,
    cause,
    gap_quantity,
    gap_market_value,
    gap_bps,
    relative_gap,
    is_recurrence,
    coalesce(gap_bps >= {{ var('nav_materiality_bps') }}, false) as nav_materiality_candidate,
    case
        when t_gap_escalate or t_relative_gap or t_age_escalate
          or t_corporate_action or is_recurrence then 3
        when t_cause_unknown or t_gap_review or t_age_review then 2
        else 1
    end as action_level,
    -- One reason per measure: the biggest tier that fired, so the text does not
    -- say both "over 5 bp" and "over 0.5 bp" about the same gap.
    coalesce(nullif(concat_ws('; ',
        case when t_gap_escalate then 'gap over ' || {{ var('gap_bps_escalate') }} || ' bp of portfolio'
             when t_gap_review   then 'gap over ' || {{ var('gap_bps_review') }} || ' bp of portfolio' end,
        case when t_relative_gap then 'gap is a large share of the position' end,
        case when t_age_escalate then 'open ' || {{ var('age_escalate_trading_days') }} || '+ trading days'
             when t_age_review   then 'open ' || {{ var('age_review_trading_days') }} || '+ trading days' end,
        case when t_corporate_action then 'corporate action (split)' end,
        case when is_recurrence then 'same security broke again recently' end,
        case when t_cause_unknown then 'cause unknown' end
    ), ''), 'routine: cause named by rules, nothing else fired') as action_reason
from flagged
