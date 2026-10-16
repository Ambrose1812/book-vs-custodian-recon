-- Our book's holdings per security per trading day, in as-of share terms, on
-- TWO bases:
--   quantity_trade_basis    counts a trade from its trade date (our book of record)
--   quantity_settled_basis  counts a trade only from its settlement date, which
--                           is how a custodian reports
-- The gap between the two is what is bought or sold but not yet settled, i.e.
-- the legitimate timing difference the recon must not call a break.
--
-- Same split math as fct_positions: shares on day D =
--   F(D) * sum(signed quantity / F(trade date)) over the trades counted by D
-- where F is the cumulative split factor. Trading days come from the price
-- calendar (days Tiingo has a price), one row per security from its first trade.
with securities as (
    select security_id, ticker from {{ ref('dim_security_master') }}
),

trades as (
    select
        t.transaction_id,
        t.security_id,
        s.ticker,
        t.trade_date,
        t.settlement_date,
        case when t.side = 'BUY' then t.quantity else -t.quantity end as signed_quantity
    from {{ ref('stg_transactions') }} t
    join securities s on s.security_id = t.security_id
),

base as (
    select
        tr.*,
        tr.signed_quantity / coalesce(px.cum_split_factor, 1) as base_quantity
    from trades tr
    left join lateral (
        select p.cum_split_factor
        from {{ ref('int_prices_split_indexed') }} p
        where p.ticker = tr.ticker
          and p.price_date <= tr.trade_date
        order by p.price_date desc
        limit 1
    ) px on true
),

first_trade as (
    select security_id, min(trade_date) as first_trade_date
    from base
    group by security_id
),

spine as (
    select s.security_id, p.price_date as as_of_date, p.cum_split_factor
    from securities s
    join first_trade f on f.security_id = s.security_id
    join {{ ref('int_prices_split_indexed') }} p
        on p.ticker = s.ticker
       and p.price_date >= f.first_trade_date
)

select
    sp.as_of_date,
    sp.security_id,
    round(
        coalesce(sum(b.base_quantity) filter (where b.trade_date <= sp.as_of_date), 0)
        * sp.cum_split_factor, 6
    ) as quantity_trade_basis,
    round(
        coalesce(sum(b.base_quantity) filter (where b.settlement_date <= sp.as_of_date), 0)
        * sp.cum_split_factor, 6
    ) as quantity_settled_basis
from spine sp
left join base b on b.security_id = sp.security_id
group by sp.as_of_date, sp.security_id, sp.cum_split_factor
