-- One row per transaction: the running position in the security immediately
-- after that trade, in share terms as of the trade date, valued at the latest
-- raw close on or before the trade date.
--
-- Corporate actions: splits change share counts without any transaction row.
-- Each trade is converted to pre-split "base units" (quantity / cumulative
-- split factor at the trade date), summed, then converted back to share terms
-- as of the row's own date. Prices stay unadjusted so quantity and price are
-- always on the same basis.
with transactions as (
    select * from {{ ref('stg_transactions') }}
),

-- as-of join: latest price row on or before each trade date. Lateral lets
-- the subquery return both the close and the cumulative split factor.
enriched as (
    select
        t.security_id,
        sm.ticker,
        t.trade_date,
        t.transaction_id,
        t.side,
        t.quantity,
        px.close_price,
        coalesce(px.cum_split_factor, 1) as cum_split_factor
    from transactions t
    join {{ ref('dim_security_master') }} sm
        on t.security_id = sm.security_id
    left join lateral (
        select p.close_price, p.cum_split_factor
        from {{ ref('int_prices_split_indexed') }} p
        where p.ticker = sm.ticker
          and p.price_date <= t.trade_date
        order by p.price_date desc
        limit 1
    ) px on true
),

signed_base as (
    select
        security_id,
        ticker,
        trade_date,
        transaction_id,
        close_price,
        cum_split_factor,
        (case when side = 'BUY' then quantity else -quantity end)
            / cum_split_factor as signed_base_quantity
    from enriched
),

running_position as (
    select
        *,
        sum(signed_base_quantity) over (
            partition by security_id
            order by trade_date, transaction_id
            rows between unbounded preceding and current row
        ) as running_base_quantity
    from signed_base
)

select
    security_id,
    ticker,
    trade_date,
    transaction_id,
    round(running_base_quantity * cum_split_factor, 6) as shares_held,
    close_price,
    round(running_base_quantity * cum_split_factor, 6) * close_price as market_value
from running_position
order by security_id, trade_date, transaction_id
