-- Type 2 integrity: for every security the versions must tile time with no gap and no
-- overlap. A gap means a fact on that date joins to nothing; an overlap means it joins
-- to two versions and gets counted twice. Returns one row per problem found.
with ordered as (
    select
        security_id,
        version_number,
        valid_from,
        valid_to,
        is_current,
        lead(valid_from) over (partition by security_id order by valid_from) as next_valid_from
    from {{ ref('dim_security_history') }}
),

problems as (
    select security_id, 'first version does not start at 1900-01-01' as problem
    from ordered where version_number = 1 and valid_from <> date '1900-01-01'
    union all
    select security_id, 'gap or overlap between versions'
    from ordered where next_valid_from is not null and next_valid_from <> valid_to
    union all
    select security_id, 'window is empty or backwards'
    from ordered where valid_to <= valid_from
    union all
    select security_id, 'not exactly one current version'
    from ordered group by security_id having count(*) filter (where is_current) <> 1
)

select * from problems
