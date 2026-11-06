-- Our book's holdings per security per trading day, valued at that day's close.
-- One row per security per trading day, from the security's first trade onward.
-- Days after a position is fully sold stay in with quantity 0, which is what
-- makes this a periodic snapshot: a row exists whether or not anything traded.
--
-- This is the analyst-facing layer over int_book_daily_holdings, which holds the
-- split math and both quantity bases. Nothing is recalculated here: the model
-- adds the security's name and ticker, the day's close, and a market value.
--
-- Quantity is semi-additive: sum it across securities on one day, never across
-- days for one security.
--
-- market_value uses the trade-basis quantity (our book of record) and the raw,
-- unadjusted close on the same day, so shares and price are on the same basis.
-- quantity_settled_basis is kept for comparison with the custodian.
select
    h.as_of_date,
    h.security_id,
    sm.ticker,
    sm.name                                        as security_name,
    h.quantity_trade_basis,
    h.quantity_settled_basis,
    p.close_price,
    -- close_price is double precision; Postgres rounds only numeric, hence the cast
    round((h.quantity_trade_basis * p.close_price)::numeric, 2) as market_value
from {{ ref('int_book_daily_holdings') }} h
join {{ ref('dim_security_master') }} sm
    on sm.security_id = h.security_id
join {{ ref('int_prices_split_indexed') }} p
    on p.ticker = sm.ticker
   and p.price_date = h.as_of_date
