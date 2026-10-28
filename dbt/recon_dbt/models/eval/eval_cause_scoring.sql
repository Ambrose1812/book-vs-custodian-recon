-- Eval, not a mart. Scores the rules baseline against the planted-break answer
-- key, one row per planted break. This only exists in the simulation, because
-- real data has no answer key.
-- It uses each security's first break episode, since planted errors never clear.
with latest_key as (
    select
        security_id,
        break_type    as cause_actual,
        transaction_id as transaction_id_actual
    from {{ source('raw', 'planted_breaks') }}
    where ingest_date = (select max(ingest_date) from {{ source('raw', 'planted_breaks') }})
),

first_episode as (
    select *
    from (
        select
            b.*,
            row_number() over (partition by security_id order by first_break_date) as rn
        from {{ ref('fct_break_cause_baseline') }} b
    ) x
    where rn = 1
)

select
    k.security_id,
    k.cause_actual,
    p.cause_predicted,
    p.cause_method,
    k.transaction_id_actual,
    p.candidate_transaction_id,
    coalesce(k.cause_actual = p.cause_predicted, false)                    as cause_correct,
    -- An unknown answer is not the same as a wrong one. Saying "I can't tell"
    -- sends the break to a human, while a wrong label hides it.
    case
        when k.cause_actual = p.cause_predicted then 'correct'
        when p.cause_predicted = 'unknown' or p.cause_predicted is null then 'abstained'
        else 'wrong'
    end                                                                    as outcome,
    case
        when k.cause_actual = 'split_not_applied' then null
        else k.transaction_id_actual is not distinct from p.candidate_transaction_id
    end                                                                    as trade_correct
from latest_key k
left join first_episode p
    on p.security_id = k.security_id
