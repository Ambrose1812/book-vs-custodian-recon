-- Where every AI decision gets recorded once the step runs inside the pipeline.
-- For now classify/llm_step.py writes the same fields to a JSONL file, and this
-- table is the plan for later. Not run yet.
create schema if not exists audit;

create table if not exists audit.llm_decisions (
    decision_id       uuid primary key,
    created_at        timestamptz not null,
    security_id       text not null,
    first_break_date  date not null,
    input_hash        text not null,        -- same case + prompt version + model gives the same hash
    provider          text not null,
    model             text not null,
    prompt_version    text not null,
    prompt_text       text not null,        -- exactly what the model saw
    raw_response      text,                 -- exactly what it said (null if the call failed)
    final_cause       text not null,        -- after validation; bad answers become unknown
    confidence        numeric,
    reason            text,
    min_action_level  int not null,         -- anything the AI labels is at least level 2
    validation_error  text,
    unique (input_hash)
);
