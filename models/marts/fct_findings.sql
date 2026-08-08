{{ config(materialized='table') }}

SELECT source, check_id, resource_id, status, collected_at, run_id 
FROM {{ ref('stg_s3_audit')}}
UNION ALL
SELECT source, check_id, resource_id, status, collected_at, run_id 
FROM {{ ref('stg_sg_audit')}}
UNION ALL
SELECT source, check_id, resource_id, status, collected_at, run_id 
FROM {{ ref('stg_cloudtrail_audit')}}
UNION ALL
SELECT source, check_id, resource_id, status, collected_at, run_id 
FROM {{ ref('stg_evidence_logger')}}