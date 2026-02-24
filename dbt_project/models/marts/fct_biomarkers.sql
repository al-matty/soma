with staging as (
    select * from {{ ref('stg_lab_results') }}
),

meta as (
    select * from {{ ref('biomarker_meta') }}
),

joined as (
    select
        s.lab_result_id,
        s.report_date,
        s.provider,
        s.source_file,
        s.biomarker_name as biomarker_key,
        s.value_raw,

        -- Original values
        s.value_numeric as value_original,
        s.unit as unit_original,

        -- SI conversion
        coalesce(m.si_unit, s.unit) as unit_si,
        case
            when m.conversion_factor is not null
                then s.value_numeric * m.conversion_factor
            else s.value_numeric
        end as value_si,

        -- Reference ranges converted to SI
        case
            when m.conversion_factor is not null and s.reference_range_low is not null
                then s.reference_range_low * m.conversion_factor
            else s.reference_range_low
        end as reference_range_low_si,
        case
            when m.conversion_factor is not null and s.reference_range_high is not null
                then s.reference_range_high * m.conversion_factor
            else s.reference_range_high
        end as reference_range_high_si,

        -- Optimal ranges from seed
        m.optimal_range_low_si,
        m.optimal_range_high_si,

        -- Range flags
        case
            when s.reference_range_low is not null and s.reference_range_high is not null
                then s.value_numeric >= s.reference_range_low
                     and s.value_numeric <= s.reference_range_high
            when s.reference_range_high is not null
                then s.value_numeric <= s.reference_range_high
            when s.reference_range_low is not null
                then s.value_numeric >= s.reference_range_low
            else null
        end as is_within_ref_range,

        case
            when m.optimal_range_low_si is not null
                 and m.optimal_range_high_si is not null
                then (s.value_numeric * coalesce(m.conversion_factor, 1.0)) >= m.optimal_range_low_si
                     and (s.value_numeric * coalesce(m.conversion_factor, 1.0)) <= m.optimal_range_high_si
            else null
        end as is_within_optimal_range,

        s.is_below_detection_limit,
        s.is_above_detection_limit,

        -- Metadata
        m.category,
        coalesce(s.loinc_code, m.loinc_code) as loinc_code

    from staging s
    left join meta m
        on s.biomarker_name = m.biomarker_key
)

select * from joined
