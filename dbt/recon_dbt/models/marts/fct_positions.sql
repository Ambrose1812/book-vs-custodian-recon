with transactions as (
    select * from {{ ref('stg_transactions') }}
),

signed_transactions as (
    select
        security_id,
        trade_date,
        transaction_id,
        case when side = 'BUY' then quantity else -quantity end as signed_quantity
    from transactions
),

running_position as (
    select
        security_id,
        trade_date,
        transaction_id,
        signed_quantity,
        sum(signed_quantity) over (
            partition by security_id
            order by trade_date, transaction_id
            rows between unbounded preceding and current row
        ) as shares_held
    from signed_transactions
),

priced_positions as (
    select
        rp.security_id,
        sm.ticker,
        rp.trade_date,
        rp.transaction_id,
        rp.shares_held,
        (
            select p.close_price
            from {{ ref('stg_prices') }} p
            where p.ticker = sm.ticker
              and p.price_date <= rp.trade_date
            order by p.price_date desc
            limit 1
        ) as close_price
    from running_position rp
    join {{ ref('dim_security_master') }} sm on rp.security_id = sm.security_id
)

select
    security_id,
    ticker,
    trade_date,
    transaction_id,
    shares_held,
    close_price,
    shares_held * close_price as market_value
from priced_positions
order by security_id, trade_date, transaction_id