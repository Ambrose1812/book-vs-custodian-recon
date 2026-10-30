-- Rules-only baseline for break causes. No model and no LLM, just the
-- signatures in docs/break_taxonomy.md. Anything added later gets scored
-- against this.
--
-- For each break episode, looking at its first break day (D):
--   1. gap = custodian quantity minus our settled-basis book. The custodian
--      reports settled holdings, so settled is the fair comparison.
--   2. The candidate trades are our trades that settle on D. The first break
--      day is the settlement date of the bad trade, which pins it down.
--   3. Convert each candidate's signed quantity to share terms on D. If the gap
--      is -1x that amount it is a missing trade, +1x a duplicate, +9x a 10x slip.
--   4. If no trade fits, D is a split ex-date, and the custodian quantity times
--      the split factor equals our book, the custodian skipped the split.
--   5. Anything else is unknown. If more than one trade fits I also say unknown,
--      because picking one would be a coin flip.
{% set tol = var('recon_tolerance', 0.001) %}

with trading_days as (
    select
        as_of_date,
        lag(as_of_date) over (order by as_of_date) as prev_as_of_date
    from (select distinct price_date as as_of_date from {{ ref('int_prices_split_indexed') }}) d
),

first_break as (
    select
        e.security_id,
        sm.ticker,
        e.episode_start                       as first_break_date,
        td.prev_as_of_date,
        r.recon_status,
        r.custodian_quantity,
        r.book_quantity_settled_basis,
        r.difference_vs_settled_basis         as gap_vs_settled
    from {{ ref('fct_break_episodes') }} e
    join {{ ref('fct_recon_positions') }} r
        on r.security_id = e.security_id
       and r.as_of_date = e.episode_start
    join {{ ref('dim_security_master') }} sm
        on sm.security_id = e.security_id
    join trading_days td
        on td.as_of_date = e.episode_start
),

-- Split factor on the first break day, plus any split that takes effect that day.
day_factor as (
    select
        fb.security_id,
        fb.first_break_date,
        coalesce(px.cum_split_factor, 1)                                   as factor_on_day,
        case when px.price_date = fb.first_break_date
             then px.split_factor::numeric else 1 end                      as split_on_day
    from first_break fb
    left join lateral (
        select p.cum_split_factor, p.split_factor, p.price_date
        from {{ ref('int_prices_split_indexed') }} p
        where p.ticker = fb.ticker
          and p.price_date <= fb.first_break_date
        order by p.price_date desc
        limit 1
    ) px on true
),

candidates as (
    select
        fb.security_id,
        fb.first_break_date,
        fb.gap_vs_settled,
        t.transaction_id,
        (case when t.side = 'BUY' then t.quantity else -t.quantity end)
            / coalesce(px.cum_split_factor, 1) * df.factor_on_day          as effect_on_day
    from first_break fb
    join day_factor df
        on df.security_id = fb.security_id
       and df.first_break_date = fb.first_break_date
    join {{ ref('stg_transactions') }} t
        on t.security_id = fb.security_id
       and t.settlement_date <= fb.first_break_date
       and (fb.prev_as_of_date is null or t.settlement_date > fb.prev_as_of_date)
    left join lateral (
        select p.cum_split_factor
        from {{ ref('int_prices_split_indexed') }} p
        where p.ticker = fb.ticker
          and p.price_date <= t.trade_date
        order by p.price_date desc
        limit 1
    ) px on true
),

matches as (
    select
        c.security_id,
        c.first_break_date,
        c.transaction_id,
        m.cause,
        m.trade_multiple
    from candidates c
    cross join (values
        ('missing_trade',   -1.0),
        ('duplicate_trade',  1.0),
        ('wrong_quantity',   9.0)
    ) as m(cause, trade_multiple)
    where abs(c.gap_vs_settled - m.trade_multiple * c.effect_on_day) <= {{ tol }}
),

match_summary as (
    select
        security_id,
        first_break_date,
        count(*)                as n_trade_matches,
        min(cause)              as cause,
        min(transaction_id)     as transaction_id,
        min(trade_multiple)     as trade_multiple
    from matches
    group by security_id, first_break_date
)

select
    fb.security_id,
    fb.first_break_date,
    fb.recon_status,
    fb.custodian_quantity,
    fb.book_quantity_settled_basis,
    fb.gap_vs_settled,
    coalesce(ms.n_trade_matches, 0)                       as n_trade_matches,
    ms.transaction_id                                     as candidate_transaction_id,
    ms.trade_multiple,
    case
        when ms.n_trade_matches = 1 then ms.cause
        when ms.n_trade_matches > 1 then 'unknown'
        when df.split_on_day <> 1
         and abs(fb.custodian_quantity * df.split_on_day - fb.book_quantity_settled_basis)
             <= {{ tol }} * greatest(df.split_on_day, 1) then 'split_not_applied'
        else 'unknown'
    end                                                   as cause_predicted,
    case
        when ms.n_trade_matches = 1 then 'trade_ratio'
        when ms.n_trade_matches > 1 then 'ambiguous'
        when df.split_on_day <> 1
         and abs(fb.custodian_quantity * df.split_on_day - fb.book_quantity_settled_basis)
             <= {{ tol }} * greatest(df.split_on_day, 1) then 'split_ratio'
        else 'no_signature'
    end                                                   as cause_method
from first_break fb
join day_factor df
    on df.security_id = fb.security_id
   and df.first_break_date = fb.first_break_date
left join match_summary ms
    on ms.security_id = fb.security_id
   and ms.first_break_date = fb.first_break_date
