"""
Unified Data Export Module for AOP-Wiki CLI.

Provides a DRY (Don't Repeat Yourself) approach to CSV and Excel generation.
Uses configurable field definitions and transformers to produce consistent,
maintainable outputs.

Usage:
    from src.data_export import write_csv, AOP_FIELDS_MIN
    
    write_csv(
        data=aop_dict,
        field_config=AOP_FIELDS_MIN,
        output_path='outputs/aops.csv',
        sort_key='completion_score.percent'
    )
"""

from .field_definitions import (
    FieldConfig,
    FieldConfigSet,
    AOP_FIELDS_MIN,
    AOP_DETAIL_FIELDS,
    EVENT_FIELDS_MIN,
    EVENT_DETAIL_FIELDS,
    CONCORDANCE_KER_FIELDS,
    SEARCH_RESULTS_AOP_FIELDS,
    SEARCH_RESULTS_EVENT_FIELDS,
    SEIZURE_AOP_EVENT_FIELDS,
    HARMONIZED_SEIZURE_AOP_EVENT_FIELDS,
    HARMONIZED_SEIZURE_AOP_SUMMARY_FIELDS,
    SEIZURE_ASSAY_FIELDS,
    SEIZURE_TARGET_FAMILIES_SUMMARY_FIELDS,
    SEIZURE_TF_TO_EVENTS_ASSAYS_FIELDS,
    SEIZURE_AOP_ID_MAPPING_FIELDS,
    SEIZURE_KE_DESC_MAPPING_FIELDS,
    SEIZURE_TF_ASSAYS_KE_MAPPING_FIELDS,
    SEIZURE_KE_DESC_TO_HARMONIZED_FIELDS,
)

from .csv_writer import (
    write_csv,
    write_concordance_csv,
    write_seizure_aop_csv,
    write_harmonized_seizure_aop_csv,
    write_summary_harmonized_seizure_aop_csv,
    write_ke_description_to_harmonized_mapping_csv,
    write_summary_stats_csv,
    get_nested_value,
)

from .transformers import (
    clean_text,
    round_2,
    yes_no,
    join_list,
    format_term_with_source,
    extract_ec_objects,
    extract_ec_actions,
    extract_ec_processes,
    flatten_ordered_events,
    get_transformer,
    prepare_concordance_results_for_export,
    build_aop_to_ker_mapping,
    build_submitted_title_by_event_id,
)

from .search_export import (
    export_search_results_to_json,
    write_search_results_csv,
    generate_search_results_filename,
)

from .excel_workbook_initiator import (
    initiate_workbook_creation_for_harmonized_kers,
    create_aop_specific_harmonized_ker_workbook,
)

from .excel_writer import (
    write_excel_workbook,
    write_excel_sheet,
    auto_size_columns,
)

from .seizure_aop_export import (
    write_seizure_aop_excel_workbook,
    export_seizure_aop_results,
)

# Reference search result exports
from src.data_export.export_reference_search_results import (
    export_search_results_to_csv,
    export_structured_json,
    export_summary,
)

__all__ = [
    # Core classes
    'FieldConfig',
    'FieldConfigSet',
    
    # Field configurations
    'AOP_FIELDS_MIN',
    'AOP_DETAIL_FIELDS',
    'EVENT_FIELDS_MIN',
    'EVENT_DETAIL_FIELDS',
    'CONCORDANCE_KER_FIELDS',
    'SEIZURE_AOP_EVENT_FIELDS',
    'HARMONIZED_SEIZURE_AOP_EVENT_FIELDS',
    'HARMONIZED_SEIZURE_AOP_SUMMARY_FIELDS',
    'SEIZURE_ASSAY_FIELDS',
    'SEIZURE_TARGET_FAMILIES_SUMMARY_FIELDS',
    'SEIZURE_TF_TO_EVENTS_ASSAYS_FIELDS',
    'SEIZURE_AOP_ID_MAPPING_FIELDS',
    'SEIZURE_KE_DESC_MAPPING_FIELDS',
    'SEIZURE_TF_ASSAYS_KE_MAPPING_FIELDS',
    'SEIZURE_KE_DESC_TO_HARMONIZED_FIELDS',
    
    # CSV Writer
    'write_csv',
    'write_concordance_csv',
    'write_seizure_aop_csv',
    'write_harmonized_seizure_aop_csv',
    'write_summary_harmonized_seizure_aop_csv',
    'write_ke_description_to_harmonized_mapping_csv',
    'write_summary_stats_csv',
    'get_nested_value',
    
    # Transformers
    'clean_text',
    'round_2',
    'yes_no',
    'join_list',
    'format_term_with_source',
    'extract_ec_objects',
    'extract_ec_actions',
    'extract_ec_processes',
    'flatten_ordered_events',
    'get_transformer',
    'prepare_concordance_results_for_export',
    'build_aop_to_ker_mapping',
    'build_submitted_title_by_event_id',
    
    # Excel Workbooks
    'initiate_workbook_creation_for_harmonized_kers',
    'create_aop_specific_harmonized_ker_workbook',
    'write_excel_workbook',
    'write_excel_sheet',
    'write_seizure_aop_excel_workbook',
    'auto_size_columns',
    
    # Seizure AOP exports
    'export_seizure_aop_results',
    
    # Reference search exports
    'export_search_results_to_csv',
    'export_structured_json',
    'export_summary',
]
