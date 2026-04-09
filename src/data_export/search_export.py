"""
Export functions for search results.

Provides JSON and CSV export for config-based searches.
"""
import json
import os
from pathlib import Path
from typing import Dict, Union, Optional

from .csv_writer import write_csv
from .field_definitions import SEARCH_RESULTS_AOP_FIELDS, SEARCH_RESULTS_EVENT_FIELDS


def generate_search_results_filename(
    config_name: str,
    work_date_str: str,
    co_occurrence_only: bool = False,
    search_params: Optional[Dict] = None,
    extension: str = "csv"
) -> str:
    """
    Generate a filename for search results with appropriate suffixes.
    
    Builds filename following pattern: {config}_results_{suffixes}_{date}.{ext}
    
    Args:
        config_name: Name of the search config
        work_date_str: Date string (MM-DD-YYYY)
        co_occurrence_only: Whether results are filtered to co-occurrence only
        search_params: Search parameters dict (checks for priority_field usage)
        extension: File extension (default: "csv")
    
    Returns:
        Filename string with appropriate suffixes
        
    Examples:
        >>> generate_search_results_filename("lung_and_immune_aops", "02-15-2026")
        'lung_and_immune_aops_results_02-15-2026.csv'
        
        >>> generate_search_results_filename("lung_and_immune_aops", "02-15-2026", 
        ...                                   co_occurrence_only=True)
        'lung_and_immune_aops_results_co_occurrence_only_02-15-2026.csv'
    """
    filename_parts = [config_name, "results"]
    
    # Add co-occurrence-only suffix if applicable
    if co_occurrence_only:
        filename_parts.append("co_occurrence_only")
    
    # Add priority-field-only suffix if priority_field used without fields_to_search
    if search_params and "priority_field" in search_params and "fields_to_search" not in search_params:
        filename_parts.append("priority_field_only")
    
    filename_parts.append(work_date_str)
    return "_".join(filename_parts) + f".{extension}"


def export_search_results_to_json(
    results: Dict[str, Dict],
    summary: Dict,
    output_path: Union[str, Path],
    config_name: str,
    work_date_str: str,
    co_occurrence_only: bool = False
) -> None:
    """
    Export search results to JSON with metadata.
    
    Args:
        results: Dictionary of search results by entity ID
        summary: Search summary statistics
        output_path: Path where JSON will be saved
        config_name: Name of the search config used
        work_date_str: Date string (MM-DD-YYYY)
        co_occurrence_only: Whether results were filtered to co-occurrence only
    """
    output_data = {
        "config": config_name,
        "search_date": work_date_str,
        "co_occurrence_only": co_occurrence_only,
        "summary": summary,
        "results": results
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)


def write_search_results_csv(
    results: Dict[str, Dict],
    output_path: Union[str, Path],
    entity_type: str,
    entity_dict: Dict[str, Dict] = None
) -> None:
    """
    Write search results to CSV using appropriate field configuration.
    
    Transforms results into rows and uses field configs to define columns.
    Follows the pattern used by write_concordance_csv.
    
    Args:
        results: Dictionary with structure:
            {entity_id: {
                'entity_id': id,
                'title': title,
                'terms_found': [terms],
                'matched_fields': [fields],
                'co_occurrences': [[term1, term2], ...],
                'has_priority_co_occurrence': bool,
                'co_occurrence_fields': [fields],
                'snippets_by_field': {field: [snippets]}
            }}
        output_path: Path where CSV will be saved
        entity_type: Type of entities ("aops", "events", or "kers")
        entity_dict: Optional dictionary of full entity data (needed for applicability fields)
    """
    entity_dict = entity_dict or {}
    # Prepare rows with appropriate transformations
    rows = []
    
    if entity_type == "aops":
        # AOPs: Include co-occurrence information and applicability
        for entity_id, result in results.items():
            # Format co-occurrences as readable string
            co_occ_str = "; ".join(
                [f"{pair[0]} + {pair[1]}" for pair in result.get("co_occurrences", [])]
            ) if result.get("co_occurrences") else ""
            
            # Count total snippets
            snippet_count = sum(
                len(snippets) 
                for snippets in result.get("snippets_by_field", {}).values()
            )
            
            # Get applicability data from full entity dict
            entity_info = entity_dict.get(entity_id, {})
            
            row_data = {
                'entity_id': result.get('entity_id', entity_id),
                'title': result.get('title', 'N/A'),
                'sex_applicability': entity_info.get('sex_applicability', []),
                'life_stage_applicability': entity_info.get('life_stage_applicability', []),
                'taxonomy_applicability': entity_info.get('taxonomy_applicability', []),
                'terms_found': result.get('terms_found', []),
                'co_occurrences_str': co_occ_str,
                'has_priority_term_match': result.get('has_priority_term_match', False),
                'has_priority_co_occurrence': result.get('has_priority_co_occurrence', False),
                'co_occurrence_fields': result.get('co_occurrence_fields', []),
                'matched_fields': result.get('matched_fields', []),
                'snippet_count': snippet_count
            }
            rows.append(row_data)
        
        # Sort AOPs: priority co-occurrences first, then by snippet_count descending
        rows.sort(key=lambda x: (not x['has_priority_co_occurrence'], -x['snippet_count']))
        
        field_config = SEARCH_RESULTS_AOP_FIELDS
        
    else:  # events or kers
        # Events/KERs: Simpler structure without co-occurrence details
        for entity_id, result in results.items():
            # Count total snippets
            snippet_count = sum(
                len(snippets) 
                for snippets in result.get("snippets_by_field", {}).values()
            )
            
            row_data = {
                'entity_id': result.get('entity_id', entity_id),
                'title': result.get('title', 'N/A'),
                'terms_found': result.get('terms_found', []),
                'matched_fields': result.get('matched_fields', []),
                'snippet_count': snippet_count
            }
            rows.append(row_data)
        
        field_config = SEARCH_RESULTS_EVENT_FIELDS
    
    # Use standard write_csv with prepared data
    # Note: AOP rows are pre-sorted by priority co-occurrence, then entity_id
    # Event/KER rows will be sorted by entity_id in write_csv
    write_csv(
        data=rows,
        field_config=field_config,
        output_path=output_path,
        sort_key='entity_id' if entity_type != 'aops' else None
    )
