with source as (
    select * from {{ source('raw', 'lab_results') }}
),

cleaned as (
    select
        id as lab_result_id,
        source_file,
        extracted_at,
        extraction_method,
        report_date,
        provider,
        -- Standardize biomarker name: trim whitespace
        trim(biomarker_name_raw) as biomarker_name,
        value_raw,
        unit_raw as unit,

        -- Parse numeric value from raw string
        case
            when value_raw like '<%'
                then try_cast(replace(value_raw, '<', '') as double) / 2.0
            when value_raw like '>%'
                then try_cast(replace(value_raw, '>', '') as double)
            else try_cast(value_raw as double)
        end as value_numeric,

        -- Detection limit flags
        value_raw like '<%' as is_below_detection_limit,
        value_raw like '>%' as is_above_detection_limit,

        -- Reference ranges: parse to numeric
        try_cast(reference_range_low_raw as double) as reference_range_low,
        try_cast(reference_range_high_raw as double) as reference_range_high,

        loinc_code,
        notes,

        -- Deduplication: rank by extraction time, keep latest
        row_number() over (
            partition by report_date, trim(biomarker_name_raw), provider
            order by extracted_at desc
        ) as _row_num

    from source
    where
        biomarker_name_raw is not null
        and value_raw is not null
)

select
    lab_result_id,
    source_file,
    extracted_at,
    extraction_method,
    report_date,
    provider,
    biomarker_name,
    value_raw,
    value_numeric,
    unit,
    is_below_detection_limit,
    is_above_detection_limit,
    reference_range_low,
    reference_range_high,
    loinc_code,
    notes
from cleaned
where _row_num = 1
