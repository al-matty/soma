with docs as (
    select * from {{ source('raw', 'documents') }}
),

biomarker_counts as (
    select
        source_file,
        count(*) as actual_biomarker_count
    from {{ ref('stg_lab_results') }}
    group by source_file
)

select
    d.id as document_id,
    d.source_file,
    d.report_date,
    d.provider,
    d.report_type,
    d.tags,
    d.markdown_path,
    coalesce(b.actual_biomarker_count, 0) as biomarker_count,
    d.extracted_at,
    d.extraction_method
from docs d
left join biomarker_counts b
    on d.source_file = b.source_file
