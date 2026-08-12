SELECT expected.source, manifest.run_id
FROM {{ ref('expected_sources') }} AS expected
LEFT JOIN {{ source('raw', 'load_manifest') }} AS manifest
    ON expected.source = manifest.source
WHERE manifest.source IS NULL
