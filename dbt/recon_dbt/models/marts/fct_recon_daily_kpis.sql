-- Daily recon KPIs: one row per trading day.
--
-- match_rate = positions in good standing / positions held that day, where
-- good standing means matched or timing_difference. A timing difference is not
-- an error (the custodian agrees with our settled book), so it is not a break.
-- breaks = positions in a break status that day.
select
    as_of_date,
    count(*)                                                       as positions,
    count(*) filter (where recon_status = 'matched')               as matched,
    count(*) filter (where recon_status = 'timing_difference')     as timing_differences,
    count(*) filter (where is_break)                               as breaks,
    round(
        count(*) filter (where not is_break)::numeric / count(*), 4
    )                                                              as match_rate
from {{ ref('fct_recon_positions') }}
group by as_of_date
