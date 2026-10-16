-- Reconciliation: our book vs the custodian, one row per security per trading
-- day where either side (or both) holds a position.
--
-- Full outer join on purpose: an inner join would drop the rows that exist on
-- only one side, and those are often the real problems.
--
-- recon_status, in order:
--   matched               custodian agrees with our trade-date book
--   timing_difference     custodian agrees with our SETTLED book: the gap is just
--                         trades that have not settled yet, not an error
--   missing_on_custodian  custodian holds nothing, but our settled book does
--   missing_in_book       custodian holds something, our book holds nothing
--   quantity_break        both hold it, and the numbers disagree after settlement
-- Everything except matched and timing_difference is a break (is_break).
--
-- Tolerance (shares): differences up to this are rounding noise, not breaks.
{% set tol = var('recon_tolerance', 0.001) %}

with trading_days as (
    select distinct price_date as as_of_date
    from {{ ref('int_prices_split_indexed') }}
),

book as (
    select * from {{ ref('int_book_daily_holdings') }}
),

-- A custodian statement only exists on trading days; ignore any other date.
custodian as (
    select c.as_of_date, c.security_id, c.quantity
    from {{ ref('stg_custodian_holdings') }} c
    join trading_days d on d.as_of_date = c.as_of_date
),

joined as (
    select
        coalesce(b.as_of_date, c.as_of_date)       as as_of_date,
        coalesce(b.security_id, c.security_id)     as security_id,
        coalesce(b.quantity_trade_basis, 0)        as book_quantity_trade_basis,
        coalesce(b.quantity_settled_basis, 0)      as book_quantity_settled_basis,
        coalesce(c.quantity, 0)                    as custodian_quantity
    from book b
    full outer join custodian c
        on c.as_of_date = b.as_of_date
       and c.security_id = b.security_id
),

active as (
    select * from joined
    where abs(book_quantity_trade_basis) > {{ tol }}
       or abs(book_quantity_settled_basis) > {{ tol }}
       or abs(custodian_quantity) > {{ tol }}
),

classified as (
    select
        *,
        custodian_quantity - book_quantity_trade_basis   as difference_vs_trade_basis,
        custodian_quantity - book_quantity_settled_basis as difference_vs_settled_basis,
        case
            when abs(custodian_quantity - book_quantity_trade_basis) <= {{ tol }}
                then 'matched'
            when abs(custodian_quantity - book_quantity_settled_basis) <= {{ tol }}
                then 'timing_difference'
            when abs(custodian_quantity) <= {{ tol }}
                then 'missing_on_custodian'
            when abs(book_quantity_trade_basis) <= {{ tol }}
             and abs(book_quantity_settled_basis) <= {{ tol }}
                then 'missing_in_book'
            else 'quantity_break'
        end as recon_status
    from active
)

select
    *,
    recon_status not in ('matched', 'timing_difference') as is_break
from classified
