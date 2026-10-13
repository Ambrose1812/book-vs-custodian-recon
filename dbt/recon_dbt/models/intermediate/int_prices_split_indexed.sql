-- Daily prices with a cumulative split index per ticker.
--
-- cum_split_factor on a given day = product of every split_factor with an
-- effective date on or before that day (1 if the ticker has never split).
-- A trade made on a split's effective date therefore counts as post-split,
-- matching how that day's prices are quoted.
--
-- Product via exp(sum(ln(x))): SQL has no product() aggregate, and
-- ln(1) = 0 means ordinary days contribute nothing to the running sum.
select
    ticker,
    price_date,
    close_price,
    split_factor,
    round(
        exp(
            sum(ln(split_factor::numeric)) over (
                partition by ticker
                order by price_date
                rows between unbounded preceding and current row
            )
        ),
        8
    ) as cum_split_factor
from {{ ref('stg_prices') }}
