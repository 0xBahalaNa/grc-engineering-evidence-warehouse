with padded as (
    select * from {{ source('raw', 'cloudtrail_audit') }}
    union all by name
    select
        null::varchar as event_source,
        null::varchar as principal,
        null::varchar as error_code,
        null::varchar as source_ip
    where false
)
select
    source,
    check_id,
    resource_id,
    case status
        when 'CRITICAL' then 'FAIL'
        when 'WARN' then 'WARN'
        when 'INFO' then 'WARN'
        else error(
            'stg_cloudtrail_audit: unmapped status: '
            || coalesce(status, '<NULL>')
        )
    end as status,
    collected_at::timestamptz as collected_at,
    event_time::timestamptz as event_time,
    event_name,
    event_source,
    nullif(principal, 'N/A') as principal,
    error_code,
    nullif(source_ip, 'N/A') as source_ip,
    native_severity,
    run_id,
    loaded_at
from padded
