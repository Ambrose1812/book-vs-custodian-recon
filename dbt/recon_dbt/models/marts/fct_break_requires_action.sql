-- The open breaks that need a human right now: the latest day of
-- fct_break_action_history, for episodes that are still open. The level logic
-- lives in the history model, so there is only one copy of it.
select
    security_id,
    episode_start,
    age_trading_days    as days_in_break,
    last_status,
    cause,
    gap_quantity,
    gap_market_value,
    gap_bps,
    relative_gap,
    is_recurrence,
    nav_materiality_candidate,
    action_level,
    action_reason,
    as_of_date          as as_of_latest_date
from {{ ref('fct_break_action_history') }}
where is_latest_date
  and episode_is_open
