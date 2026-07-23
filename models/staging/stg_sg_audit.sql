with padded as (
    select * from raw.sg_audit
    union all by name
    select
        null::varchar as from_port,
        null::varchar as to_port,
        null::varchar as cidr_ip,
        null::varchar as sg_name
    where false
)
select
    source,
    check_id,
    resource_id,
    status,
    collected_at::timestamptz as collected_at,
    from_port::varchar as from_port,
    to_port::varchar as to_port,
    cidr_ip,
    sg_name,
    run_id,
    loaded_at
from padded
