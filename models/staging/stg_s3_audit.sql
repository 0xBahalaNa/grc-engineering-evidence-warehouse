with padded as (
    select * from {{ source('raw', 's3_audit') }}
    union all by name
    select
        null::varchar as enc_type
    where false
)
select
    source,
    check_id,
    resource_id,
    status,
    collected_at::timestamptz as collected_at,
    enc_type,
    run_id,
    loaded_at
from padded
