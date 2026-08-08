SELECT
    check_id,
    resource_id,
    policy_file,
    violated_attribute,
    COUNT(*) AS row_count
FROM {{ ref('stg_evidence_logger')}}
GROUP BY
    check_id,
    resource_id,
    policy_file,
    violated_attribute
HAVING COUNT(*) > 1
