{% snapshot snap_reference_ranges %}
{{
    config(
      target_schema='snapshots',
      unique_key="provider || '-' || biomarker_name",
      strategy='check',
      check_cols=['reference_range_low', 'reference_range_high'],
    )
}}

select
    provider,
    biomarker_name,
    reference_range_low,
    reference_range_high,
    max(report_date) as last_seen_date
from {{ ref('stg_lab_results') }}
where reference_range_low is not null
   or reference_range_high is not null
group by provider, biomarker_name, reference_range_low, reference_range_high

{% endsnapshot %}
