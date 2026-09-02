"""Excel workbook creation orchestration for harmonized KER evidence."""

import os
from aop_wiki_cli.parsers import collect_entity_with_cache, collect_aops_from_xml
from aop_wiki_cli.data_export.export_harmonized_kers_to_excel import transform_outputs_for_excel
from aop_wiki_cli.data_export.transformers import build_aop_to_ker_mapping


def initiate_workbook_creation_for_harmonized_kers(harmonized_kers, today, output_dir, aops_selected, logger, cache_dir=None):
    """
    Orchestrate creation of Excel workbooks for harmonized KER evidence.
    
    This function:
    1. Collects AOP metadata (with caching)
    2. Transforms AOP data to build AOP-to-KER mapping
    3. Calls Excel writer for main workbook
    4. Calls Excel writer for each AOP-specific workbook
    
    Args:
        harmonized_kers: Dictionary of harmonized KER evidence (each KER has 'aop_ids' field)
        today: Date object for file naming
        output_dir: Directory to write output files
        aops_selected: Dictionary of selected AOP IDs and descriptions
        logger: Logger instance
        cache_dir: Directory for caching raw XML data (defaults to output_dir for backward compatibility)
    """
    # Use cache_dir if provided, otherwise fall back to output_dir for backward compatibility
    cache_directory = cache_dir if cache_dir is not None else output_dir
    
    # Collect AOP info (cached - no redundant XML parsing)
    aop_info = collect_entity_with_cache('aops', collect_aops_from_xml, today, cache_directory, False, logger)

    # Build AOP-to-KER mapping (transformation)
    aop_to_ker_dict = build_aop_to_ker_mapping(aop_info)
    
    # Create main workbook
    excel_f_name = f'kers_with_harmonized_evidence_tables_{today}.xlsx'
    excel_f_path = os.path.join(output_dir, excel_f_name)
    
    transform_outputs_for_excel(harmonized_kers, excel_f_path, aops_selected, aop_to_ker_dict=aop_to_ker_dict, aop_info=aop_info)
    
    # Create AOP-specific workbooks using derived mapping
    for aop_id in aops_selected.keys():
        create_aop_specific_harmonized_ker_workbook(
            today, harmonized_kers, aop_to_ker_dict, logger, aop_id, output_dir
        )


def create_aop_specific_harmonized_ker_workbook(today, harmonized_kers, aop_to_ker_dict, logger, aop_id, output_dir):
    """
    Define any AOP-specific properties for creating standalone workbooks.
    
    Args:
        today: Date object for filename
        harmonized_kers: Dict of harmonized KER evidence
        aop_to_ker_dict: Mapping of AOP IDs to KER IDs
        logger: Logger instance
        aop_id: AOP ID to create workbook for
        output_dir: Output directory path
    """
    aop_f_name = f'AOP_{aop_id}_KERs_{today}.xlsx'
    aop_f_path = os.path.join(output_dir, aop_f_name)

    kers_in_aop = aop_to_ker_dict[str(aop_id)] if str(aop_id) in aop_to_ker_dict else []
    aop_kers = {ker_id: harmonized_kers[ker_id] for ker_id in kers_in_aop if ker_id in harmonized_kers}
    if aop_kers:
        transform_outputs_for_excel(aop_kers, aop_f_path, ker_pages_only=True)
    else:
        logger.warning(f"No KERs found for AOP {aop_id} to create workbook.")
