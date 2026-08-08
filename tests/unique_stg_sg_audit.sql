SELECT
    check_id,
    resource_id,
    from_port,
    to_port,
    cidr_ip,
    COUNT(*) AS row_count
FROM {{ ref('stg_sg_audit')}}
GROUP BY
    check_id,
    resource_id,
    from_port,
    to_port,
    cidr_ip
HAVING COUNT(*) > 1
