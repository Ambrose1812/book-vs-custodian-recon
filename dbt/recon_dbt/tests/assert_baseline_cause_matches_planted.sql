{{ config(severity='warn') }}
-- Checks the cause labels against the answer key. This only warns and does not
-- fail the build. It returns planted breaks where the baseline picked the wrong
-- cause, or got a trade-level cause right but pointed at the wrong trade.
-- Zero rows means the baseline matched the answer key.
select *
from {{ ref('eval_cause_scoring') }}
where not cause_correct
   or trade_correct is false
