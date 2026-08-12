WITH staged AS (
    SELECT 's3_audit' AS source, run_id, COUNT(*) AS staged_count
    FROM {{ ref('stg_s3_audit') }}
    GROUP BY run_id

    UNION ALL

    SELECT 'sg_audit' AS source, run_id, COUNT(*) AS staged_count
    FROM {{ ref('stg_sg_audit') }}
    GROUP BY run_id

    UNION ALL

    SELECT 'cloudtrail_audit' AS source, run_id, COUNT(*) AS staged_count
    FROM {{ ref('stg_cloudtrail_audit') }}
    GROUP BY run_id

    UNION ALL

    SELECT 'evidence_logger' AS source, run_id, COUNT(*) AS staged_count
    FROM {{ ref('stg_evidence_logger') }}
    GROUP BY run_id
)

SELECT
    manifest.source,
    manifest.run_id,
    manifest.row_count AS landed_count,
    coalesce(staged.staged_count, 0) AS staged_count
FROM {{ source('raw', 'load_manifest') }} AS manifest
LEFT JOIN staged
    ON manifest.source = staged.source
    AND manifest.run_id = staged.run_id
WHERE manifest.row_count != coalesce(staged.staged_count, 0)