SELECT
    check_id,
    resource_id,
    COUNT(*) AS row_count
FROM {{ ref('stg_s3_audit')}}
GROUP BY check_id, resource_id
HAVING COUNT(*) > 1
