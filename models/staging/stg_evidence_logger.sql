with padded as (
    select * from raw.evidence_logger
    union all by name
    select
        null::varchar as raw_message
    where false
)
select
    source,
    check_id,
    resource_id,
    status,
    collected_at::timestamptz as collected_at,
    policy_file,
    violated_attribute,
    raw_message,
    run_id,
    loaded_at
from padded
