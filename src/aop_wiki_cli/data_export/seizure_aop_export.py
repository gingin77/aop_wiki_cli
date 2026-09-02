"""Export orchestration for seizure AOP analysis results.

This module handles the export of seizure AOP data to multiple formats,
similar to how excel_workbook_initiator.py orchestrates harmonized KER exports.
"""

import os
from typing import Dict, Any, Callable, Union, List
from pathlib import Path

from aop_wiki_cli.utilities import write_dict_to_json
from .csv_writer import (
    write_csv,
    write_seizure_aop_csv,
)
from .excel_writer import write_excel_workbook
from .field_definitions import (
    FieldConfigSet,
    SEIZURE_ASSAY_FIELDS,
    SEIZURE_KE_DESC_MAPPING_FIELDS,
    SEIZURE_AOP_EVENT_FIELDS,
    HARMONIZED_SEIZURE_AOP_EVENT_FIELDS,
    HARMONIZED_SEIZURE_AOP_SUMMARY_FIELDS,
    SEIZURE_KE_DESC_TO_HARMONIZED_FIELDS,
    SEIZURE_READY_LIST_FIELDS,
    SEIZURE_EVENT_TO_HARMONIZED_FIELDS,
    SEIZURE_AOP_TO_HARMONIZED_FIELDS,
    SEIZURE_AOP_VALIDATION_FIELDS,
    SEIZURE_ASSAYS_BY_AEID_FIELDS,
    SEIZURE_CHEMICALS_BY_CASRN_FIELDS,
)
from .transformers import (
    flatten_harmonized_events,
    build_seizure_extracted_rows,
    build_seizure_ke_desc_mapping_rows,
    build_seizure_summary_rows,
    build_seizure_ke_desc_to_harmonized_rows,
)


SEIZURE_EXPORT_DECODER: Dict[str, Dict[str, Dict[str, str]]] = {
    'ready_for_emod': {
        'biological_target_families': {
            'file_prefix': 'biological_target_families',
            'sheet_name': 'Biological Target Families',
        },
        'harmonized_kes': {
            'file_prefix': 'harmonized_kes',
            'sheet_name': 'Harmonized KEs',
        },
        'event_mappings_orig_to_harmonized': {
            'file_prefix': 'event_mappings_orig_to_harmonized',
            'sheet_name': 'Event Mappings - Orig to Harm.',
        },
        'aop_to_harmonized_events_dict': {
            'file_prefix': 'aop_to_harmonized_events_dict',
            'sheet_name': 'AOP to Harmonized Events',
        },
        'assays_by_aeid': {
            'file_prefix': 'assays_by_aeid',
            'sheet_name': 'Assays by AEID',
        },
        'chemicals_by_casrn_with_seizure_details': {
            'file_prefix': 'chemicals_by_casrn_with_seizure_details',
            'sheet_name': 'Chemicals by CASRN',
        },
    },
    'to_analyze': {
        'harmonization_dict': {
            'file_prefix': 'harmonized_events',
            'sheet_name': 'Harmonized Events (Raw)',
        },
        'assays': {
            'file_prefix': 'assays',
            'sheet_name': 'Assays',
        },
        'ke_description_mappings_from_assays_df': {
            'file_prefix': 'mappings_ke_description_from_assays_df',
            'sheet_name': 'KE Description Mappings',
        },
    },
    'enriched': {
        'biological_target_families_enriched': {
            'file_prefix': 'biological_target_families_enriched',
            'sheet_name': 'Biological Target Families - Enriched',
        },
        'enriched_seizure_aop_events': {
            'file_prefix': 'harmonized_events_with_wiki_content',
            'sheet_name': 'Harmonized Events',
        },
        'event_to_assays_via_target_families': {
            'file_prefix': 'event_to_assays_via_target_families',
            'sheet_name': 'Event to Assays via Target Families',
        },
        'harmonized_summary': {
            'file_prefix': 'summary_harmonized_ke',
            'sheet_name': 'Summary of Harmonized KEs',
        },
        'ke_description_to_harmonized_ke_mapping': {
            'file_prefix': 'mapping_ke_description_to_harmonized_ke',
            'sheet_name': 'Mapping KE Description to Harmonized KEs',
        },
    },
    'for_xlsx_export_only': {
        'harmonized_aop_validation_results': {
            'file_prefix': 'harmonized_aop_validation_results',
            'sheet_name': 'Harmonized AOP Validation Results',
        },
    },

}


def _build_aop_to_harmonized_rows(aop_to_harmonized_events: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for aop_id, events in aop_to_harmonized_events.items():
        if not isinstance(events, dict):
            continue

        for event_data in events.values():
            if not isinstance(event_data, dict):
                continue
            if 'harmonized_event' not in event_data:
                continue

            rows.append({
                'aop_id': aop_id,
                'row_index': event_data.get('row_index', ''),
                'harmonized_event': event_data.get('harmonized_event', ''),
                'original_event_id': event_data.get('original_event_id', ''),
                'references': event_data.get('references', ''),
                'target_family': event_data.get('target_family', ''),
            })

    return rows


def _build_validation_rows(validation_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(validation_data, dict):
        return rows

    for aop_pair, counts in validation_data.get('unique_event_mismatches', {}).items():
        rows.append({
            'validation_type': 'unique_event_mismatch',
            'aop_pair': aop_pair,
            'aop_id': '',
            'harmonized_event': '',
            'row_index': '',
            'original_event_id': '',
            'original_event_title': '',
            'aop_one_event_count': counts.get('aop_one_event_count', ''),
            'aop_two_event_count': counts.get('aop_two_event_count', ''),
        })

    for aop_id, events in validation_data.get('extra_events', {}).items():
        if not isinstance(events, dict):
            continue
        for event in events.values():
            if not isinstance(event, dict):
                continue
            rows.append({
                'validation_type': 'extra_event',
                'aop_pair': '',
                'aop_id': aop_id,
                'harmonized_event': event.get('harmonized_event', ''),
                'row_index': event.get('row_index', ''),
                'original_event_id': event.get('original_event_id', ''),
                'original_event_title': event.get('original_event_title', ''),
                'aop_one_event_count': '',
                'aop_two_event_count': '',
            })

    for aop_id, merged in validation_data.get('merged_original_events', {}).items():
        if not isinstance(merged, dict):
            continue
        for harmonized_title, original_events in merged.items():
            if not isinstance(original_events, list):
                continue
            for original in original_events:
                if not isinstance(original, dict):
                    continue
                rows.append({
                    'validation_type': 'merged_original_event',
                    'aop_pair': '',
                    'aop_id': aop_id,
                    'harmonized_event': harmonized_title,
                    'row_index': original.get('row_index', ''),
                    'original_event_id': original.get('original_event_id', ''),
                    'original_event_title': original.get('original_event_title', ''),
                    'aop_one_event_count': '',
                    'aop_two_event_count': '',
                })

    return rows


def _build_assays_by_aeid_rows(assays_by_aeid: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(assays_by_aeid, dict):
        return rows

    for aeid, details in assays_by_aeid.items():
        if not isinstance(details, dict):
            continue

        rows.append({
            'aeid': aeid,
            'assays': details.get('assays', []),
            'target_families': list(details.get('target_families', [])),
        })

    return rows


def _build_chemicals_by_casrn_rows(chemicals_by_casrn: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(chemicals_by_casrn, dict):
        return rows

    for casrn, details in chemicals_by_casrn.items():
        if not isinstance(details, dict):
            continue

        rows.append({
            'casrn': casrn,
            'chemical': details.get('chemical', ''),
            'direction_of_effect': details.get('direction_of_effect', ''),
            'pubchem_evidence': details.get('pubchem_evidence', ''),
            'parsed_citations': details.get('parsed_citations', []),
        })

    return rows


def _generate_filename(prefix: str, work_date_str: str, extension: str) -> str:
    """
    Generate filename with consistent pattern.
    
    Args:
        prefix: Filename prefix (e.g., 'extracted_seizure_aop_events')
        work_date_str: Formatted date string (MM-DD-YYYY)
        extension: File extension without dot (e.g., 'csv', 'json')
        
    Returns:
        Formatted filename
    """
    return f'{prefix}_{work_date_str}.{extension}'


def _get_seizure_export_meta(group_key: str, dataset_key: str) -> Dict[str, Any]:
    return SEIZURE_EXPORT_DECODER.get(group_key, {}).get(dataset_key, {})


def get_seizure_file_prefix(group_key: str, dataset_key: str) -> str:
    meta = _get_seizure_export_meta(group_key, dataset_key)
    return meta.get('file_prefix', f'{group_key}_{dataset_key}')


def get_seizure_sheet_name(group_key: str, dataset_key: str) -> str:
    meta = _get_seizure_export_meta(group_key, dataset_key)
    return meta.get('sheet_name', f'{group_key} - {dataset_key}')


def _group_has_export_type(seizure_content: Dict[str, Any], group_key: str, export_type: str) -> bool:
    group = seizure_content.get(group_key, {})
    export_types = group.get('export_types', [])
    return export_type in export_types


def _group_data(seizure_content: Dict[str, Any], group_key: str) -> Dict[str, Any]:
    group = seizure_content.get(group_key, {})
    data = group.get('data', {})
    return data if isinstance(data, dict) else {}


def _register_output_path(
    file_paths: Dict[str, str],
    logical_key: str,
    output_dir: str,
    filename: str,
) -> str:
    path = os.path.join(output_dir, filename)
    file_paths[logical_key] = path
    return path


def _write_json_dataset(
    file_paths: Dict[str, str],
    output_dir: str,
    work_date_str: str,
    group_key: str,
    dataset_key: str,
    dataset_value: Any,
) -> None:
    prefix = get_seizure_file_prefix(group_key, dataset_key)
    filename = _generate_filename(prefix, work_date_str, 'json')
    write_dict_to_json(dataset_value, output_dir, filename)
    _register_output_path(file_paths, f'{group_key}.{dataset_key}.json', output_dir, filename)


def _write_csv_dataset(
    file_paths: Dict[str, str],
    output_dir: str,
    work_date_str: str,
    group_key: str,
    dataset_key: str,
    dataset_value: Any,
    writer: Callable[[Any, str], None],
) -> None:
    prefix = get_seizure_file_prefix(group_key, dataset_key)
    filename = _generate_filename(prefix, work_date_str, 'csv')
    path = _register_output_path(file_paths, f'{group_key}.{dataset_key}.csv', output_dir, filename)
    writer(dataset_value, path)


def _write_harmonization_dict_csv(dataset_value: Any, output_path: str) -> None:
    write_seizure_aop_csv(dataset_value, output_path)


def _write_assays_csv(dataset_value: Any, output_path: str) -> None:
    write_csv(
        dataset_value,
        SEIZURE_ASSAY_FIELDS,
        output_path,
        sort_key='endpoint_name',
        reverse_sort=False,
    )


def _write_ke_description_mappings_csv(dataset_value: Any, output_path: str) -> None:
    write_csv(
        build_seizure_ke_desc_mapping_rows(dataset_value),
        SEIZURE_KE_DESC_MAPPING_FIELDS,
        output_path,
        sort_key='ke_description',
        reverse_sort=False,
    )


def write_seizure_aop_excel_workbook(
    seizure_content: Dict[str, Any],
    output_path: Union[str, Path]
) -> None:
    def _group_data(group_key: str) -> Dict[str, Any]:
        group = seizure_content.get(group_key, {})
        data = group.get('data', {})
        return data if isinstance(data, dict) else {}

    def _xlsx_enabled(group_key: str) -> bool:
        group = seizure_content.get(group_key, {})
        export_types = group.get('export_types', [])
        return 'xlsx' in export_types

    def _append_sheet(
        sheets: List[Dict[str, Any]],
        group_key: str,
        dataset_key: str,
        data: Union[Dict, List[Dict]],
        field_config: FieldConfigSet,
        sort_key: str | None,
        reverse_sort: bool,
    ) -> None:
        if not data:
            return
        sheets.append({
            'name': get_seizure_sheet_name(group_key, dataset_key),
            'data': data,
            'field_config': field_config,
            'sort_key': sort_key,
            'reverse_sort': reverse_sort,
        })

    sheets: List[Dict[str, Any]] = []

    if _xlsx_enabled('ready_for_emod'):
        ready_data = _group_data('ready_for_emod')
        _append_sheet(
            sheets,
            'ready_for_emod',
            'biological_target_families',
            [{'value': tf} for tf in ready_data.get('biological_target_families', [])],
            SEIZURE_READY_LIST_FIELDS,
            'value',
            False,
        )
        _append_sheet(
            sheets,
            'ready_for_emod',
            'harmonized_kes',
            [{'value': value} for value in ready_data.get('harmonized_kes', [])],
            SEIZURE_READY_LIST_FIELDS,
            'value',
            False,
        )
        _append_sheet(
            sheets,
            'ready_for_emod',
            'event_mappings_orig_to_harmonized',
            [
                {'event_id': event_id, 'harmonized_event': harmonized_event}
                for event_id, harmonized_event in ready_data.get('event_mappings_orig_to_harmonized', {}).items()
            ],
            SEIZURE_EVENT_TO_HARMONIZED_FIELDS,
            'event_id',
            False,
        )
        _append_sheet(
            sheets,
            'ready_for_emod',
            'aop_to_harmonized_events_dict',
            _build_aop_to_harmonized_rows(ready_data.get('aop_to_harmonized_events_dict', {})),
            SEIZURE_AOP_TO_HARMONIZED_FIELDS,
            'aop_id',
            False,
        )
        _append_sheet(
            sheets,
            'ready_for_emod',
            'assays_by_aeid',
            _build_assays_by_aeid_rows(ready_data.get('assays_by_aeid', {})),
            SEIZURE_ASSAYS_BY_AEID_FIELDS,
            'aeid',
            False,
        )
        _append_sheet(
            sheets,
            'ready_for_emod',
            'chemicals_by_casrn_with_seizure_details',
            _build_chemicals_by_casrn_rows(ready_data.get('chemicals_by_casrn_with_seizure_details', {})),
            SEIZURE_CHEMICALS_BY_CASRN_FIELDS,
            'casrn',
            False,
        )

    if _xlsx_enabled('to_analyze'):
        to_analyze_data = _group_data('to_analyze')
        _append_sheet(
            sheets,
            'to_analyze',
            'harmonization_dict',
            build_seizure_extracted_rows(to_analyze_data.get('harmonization_dict', {})),
            SEIZURE_AOP_EVENT_FIELDS,
            'aop_id',
            False,
        )
        _append_sheet(
            sheets,
            'to_analyze',
            'assays',
            to_analyze_data.get('assays', []),
            SEIZURE_ASSAY_FIELDS,
            'endpoint_name',
            False,
        )
        _append_sheet(
            sheets,
            'to_analyze',
            'ke_description_mappings_from_assays_df',
            build_seizure_ke_desc_mapping_rows(to_analyze_data.get('ke_description_mappings_from_assays_df', {})),
            SEIZURE_KE_DESC_MAPPING_FIELDS,
            'ke_description',
            False,
        )

    if _xlsx_enabled('enriched'):
        post_analysis_data = _group_data('enriched')
        _append_sheet(
            sheets,
            'enriched',
            'harmonized_aop_validation_results',
            _build_validation_rows(post_analysis_data.get('harmonized_aop_validation_results', {})),
            SEIZURE_AOP_VALIDATION_FIELDS,
            'validation_type',
            False,
        )
        _append_sheet(
            sheets,
            'enriched',
            'enriched_seizure_aop_events',
            flatten_harmonized_events(post_analysis_data.get('enriched_seizure_aop_events', {})),
            HARMONIZED_SEIZURE_AOP_EVENT_FIELDS,
            'lobo',
            False,
        )
        _append_sheet(
            sheets,
            'enriched',
            'harmonized_summary',
            build_seizure_summary_rows(post_analysis_data.get('harmonized_summary', {})),
            HARMONIZED_SEIZURE_AOP_SUMMARY_FIELDS,
            'harmonized_title',
            False,
        )
        _append_sheet(
            sheets,
            'enriched',
            'ke_description_to_harmonized_ke_mapping',
            build_seizure_ke_desc_to_harmonized_rows(post_analysis_data.get('ke_description_to_harmonized_ke_mapping', {})),
            SEIZURE_KE_DESC_TO_HARMONIZED_FIELDS,
            'match_score',
            True,
        )

    if sheets:
        write_excel_workbook(sheets, output_path)


def export_seizure_aop_results(
    seizure_content: Dict[str, Any],
    output_dir: str,
    work_date_str: str
) -> Dict[str, str]:
    """
    Export seizure AOP analysis results based on root-group export_types.

    For each root group in seizure_content:
        - If 'json' is in export_types, each dataset in group['data'] is exported to JSON.
        - If 'csv' is in export_types, supported datasets in group['data'] are exported to CSV.
        - If 'xlsx' is in export_types for any group, a workbook is written with sheets for
          datasets from xlsx-enabled groups.
    
    Args:
        seizure_content: Full parsed seizure content with root groups containing
                `data` and `export_types`
        output_dir: Directory for output files
        work_date_str: Formatted date string (MM-DD-YYYY) for filenames
        
    Returns:
        Dictionary mapping output types to file paths
    """
    output_dir = os.path.join(output_dir, work_date_str)
    os.makedirs(output_dir, exist_ok=True)

    file_paths: Dict[str, str] = {}

    # JSON exports: one file per dataset within each json-enabled group
    for group_key, group_value in seizure_content.items():
        if not isinstance(group_value, dict):
            continue
        if not _group_has_export_type(seizure_content, group_key, 'json'):
            continue

        for dataset_key, dataset_value in _group_data(seizure_content, group_key).items():
            _write_json_dataset(
                file_paths,
                output_dir,
                work_date_str,
                group_key,
                dataset_key,
                dataset_value,
            )

    # CSV exports: supported datasets only (declarative handlers)
    csv_handlers: Dict[str, Dict[str, Callable[[Any, str], None]]] = {
        'to_analyze': {
            'harmonization_dict': _write_harmonization_dict_csv,
            'assays': _write_assays_csv,
            'ke_description_mappings_from_assays_df': _write_ke_description_mappings_csv,
        },
    }

    for group_key, handlers in csv_handlers.items():
        if not _group_has_export_type(seizure_content, group_key, 'csv'):
            continue

        group_data = _group_data(seizure_content, group_key)
        for dataset_key, writer in handlers.items():
            dataset_value = group_data.get(dataset_key)
            if dataset_value:
                _write_csv_dataset(
                    file_paths,
                    output_dir,
                    work_date_str,
                    group_key,
                    dataset_key,
                    dataset_value,
                    writer,
                )

    # XLSX export: generate workbook if any group requests xlsx
    has_xlsx_export = any(
        isinstance(group_value, dict) and 'xlsx' in group_value.get('export_types', [])
        for group_value in seizure_content.values()
    )
    if has_xlsx_export:
        filename = _generate_filename('seizure_aop_events', work_date_str, 'xlsx')
        path = _register_output_path(file_paths, 'xlsx.workbook', output_dir, filename)
        write_seizure_aop_excel_workbook(seizure_content, path)

    return file_paths
