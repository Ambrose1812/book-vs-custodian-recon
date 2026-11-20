-- The current version in dim_security_history and the row in dim_security_master are
-- two routes to the same answer, so they must agree. Returns any security where they
-- differ, or that exists on one side only.
with current_versions as (
    select security_id, ticker, name, exchange_code, security_type
    from {{ ref('dim_security_history') }}
    where is_current
),

master as (
    select security_id, ticker, name, exchange_code, security_type
    from {{ ref('dim_security_master') }}
)

(select 'only in history or different' as problem, * from current_versions
 except
 select 'only in history or different', * from master)
union all
(select 'only in master or different', * from master
 except
 select 'only in master or different', * from current_versions)
