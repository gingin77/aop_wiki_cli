"""
Field transformation functions for CSV export.

These functions handle common data transformations needed when flattening
nested structures into CSV format. Each function is registered by name
and can be referenced in field configurations.

All transformers should:
- Accept a single value parameter
- Handle None/missing values gracefully
- Return a value suitable for CSV (string, number, or simple type)
"""

from typing import Any, List, Dict

from aop_wiki_cli.utilities.helpers import to_json_string


def clean_text(text: Any) -> str:
    """
    Remove newlines and extra whitespace from text.
    
    Args:
        text: Input text (any type)
        
    Returns:
        Cleaned single-line string
    """
    if not isinstance(text, str):
        return str(text) if text is not None else ''
    # Replace newlines and multiple spaces with single space
    return ' '.join(text.split())


def round_2(value: Any) -> str:
    """
    Round numeric value to 2 decimal places.
    
    Args:
        value: Numeric value to round
        
    Returns:
        Formatted string with 2 decimal places
    """
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return str(value) if value is not None else ''


def yes_no(value: Any) -> str:
    """
    Convert boolean value to Yes/No string.
    
    Args:
        value: Boolean or truthy value
        
    Returns:
        'Yes' or 'No'
    """
    return 'Yes' if value else 'No'


def join_list(value: Any, separator: str = ', ') -> str:
    """
    Join list or set items into a single string.
    
    Args:
        value: List, set, or other iterable
        separator: String to use between items
        
    Returns:
        Joined string
    """
    if isinstance(value, (list, set, tuple)):
        # Filter out None and empty values
        items = [str(v) for v in value if v not in (None, '', [])]
        return separator.join(items)
    return str(value) if value is not None else ''


def extract_key_value_from_dicts(value: Any, key: str = 'title', separator: str = ', ') -> str:
    """
    Extract specified key from list of dictionaries and join them.
    
    First designed for taxonomy_applicability and similar fields where each item
    is a dict with 'source', 'source-id', and 'title' keys.
    
    Args:
        value: List of dicts containing the specified key, or other value
        key: Key to extract from each dictionary
        separator: String to use between extracted values
        
    Returns:
        Joined string of extracted values
    """
    if isinstance(value, (list, set, tuple)):
        extracted_values = []
        for item in value:
            if isinstance(item, dict):
                extracted_value = item.get(key, '')
                if extracted_value:
                    extracted_values.append(str(extracted_value))
            elif item:  # Handle non-dict items
                extracted_values.append(str(item))
        return separator.join(extracted_values)
    return str(value) if value is not None else ''


def extract_titles_from_dicts(value: Any) -> str:
    return extract_key_value_from_dicts(value, key='title')


def extract_sources_from_dicts(value: Any) -> str:
    return extract_key_value_from_dicts(value, key='source')


def format_term_with_source(value: Any) -> str:
    """
    Format cell_term/organ_term dictionaries as 'source: term'.
    
    Args:
        value: Dict with 'source' and 'term' keys, or string
        
    Returns:
        Formatted string like "UBERON: lung"
    """
    if isinstance(value, dict):
        source = value.get('source')
        term = value.get('term')
        if source and term:
            return f"{source}: {term}"
        elif term:
            return term
    return str(value) if value else ""


def _extract_ec_component(ecs: Any, component_key: str) -> str:
    """
    Generic extractor for Event Component fields.
    
    Args:
        ecs: List of EC dictionaries
        component_key: Key to extract ('biological_object', 'biological_action', 'biological_process')
        
    Returns:
        Comma-separated string of component terms
    """
    if not isinstance(ecs, list):
        return ""
    
    terms = []
    for ec in ecs:
        if isinstance(ec, dict):
            component = ec.get(component_key, {})
            if isinstance(component, dict) and component.get('term'):
                terms.append(component['term'])
    
    return ", ".join(terms)


def extract_ec_objects(ecs: Any) -> str:
    return _extract_ec_component(ecs, 'biological_object')


def extract_ec_actions(ecs: Any) -> str:
    return _extract_ec_component(ecs, 'biological_action')


def extract_ec_processes(ecs: Any) -> str:
    return _extract_ec_component(ecs, 'biological_process')
    

def _format_event(ev: Dict) -> str:
    """
    Format a single event as 'event_id:title'.
    
    Args:
        ev: Event dictionary with 'event_id' and 'title' keys
        
    Returns:
        Formatted string like "123:Event title"
    """
    if not isinstance(ev, dict):
        return ""
    event_id = ev.get('event_id', '')
    title = ev.get('title', '')
    return f"{event_id}:{title}"


def _format_event_sequence(events_dict: Dict) -> List[str]:
    """
    Format a sequence of events from a dictionary.
    
    Args:
        events_dict: Dictionary of events (event order -> event data)
        
    Returns:
        List of formatted event strings
    """
    formatted = []
    for ev in events_dict.values():
        if isinstance(ev, dict):
            formatted.append(_format_event(ev))
    return formatted


def flatten_ordered_events(ordered_events: Any) -> str:
    """
    Convert ordered_events structure to a readable string representation.
    
    Handles different AOP event ordering structures:
    - Linear paths (path_to_ao)
    - Branched paths with convergence
    - String messages (e.g., for orphaned events)
    
    Args:
        ordered_events: Dict or string containing event ordering
        
    Returns:
        Human-readable string representation of event order
    """
    if not ordered_events:
        return ""
    
    # If it's a string message (e.g., for orphaned events), return as-is
    if isinstance(ordered_events, str):
        return ordered_events
    
    if not isinstance(ordered_events, dict):
        return ""
    
    # Handle linear path structure
    if "path_to_ao" in ordered_events:
        events = _format_event_sequence(ordered_events["path_to_ao"])
        return " → ".join(events)
    
    # Handle branched path structure with convergence
    elif "path_before_branching" in ordered_events:
        parts = []
        
        # Path before branching
        if ordered_events.get("path_before_branching"):
            before_events = _format_event_sequence(ordered_events["path_before_branching"])
            if before_events:
                parts.append(" → ".join(before_events))
        
        # Divergent branches
        if ordered_events.get("divergent_branches"):
            branch_strs = []
            for branch in ordered_events["divergent_branches"]:
                branch_events = _format_event_sequence(branch.get("events", {}))
                if branch_events:
                    branch_strs.append(" → ".join(branch_events))
            if branch_strs:
                parts.append("[BRANCHES: " + " | ".join(branch_strs) + "]")
        
        # Path after branching (convergence)
        if ordered_events.get("path_after_branching"):
            after_events = _format_event_sequence(ordered_events["path_after_branching"])
            if after_events:
                parts.append(" → ".join(after_events))
        
        return " ".join(parts)
    
    return ""


# Registry of transformer functions by name
TRANSFORMERS = {
    'clean_text': clean_text,
    'round_2': round_2,
    'yes_no': yes_no,
    'join_list': join_list,
    'to_json_string': to_json_string,
    'extract_key_value_from_dicts': extract_key_value_from_dicts,
    'extract_titles_from_dicts': extract_titles_from_dicts,
    'extract_sources_from_dicts': extract_sources_from_dicts,
    'format_term_with_source': format_term_with_source,
    'extract_ec_objects': extract_ec_objects,
    'extract_ec_actions': extract_ec_actions,
    'extract_ec_processes': extract_ec_processes,
    'flatten_ordered_events': flatten_ordered_events,
}


def prepare_concordance_results_for_export(search_results: Dict[str, Dict], all_kers: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Prepare concordance search results for export (JSON/CSV).
    
    Performs two operations:
    1. Enriches results with KER metadata (upstream_ke, downstream_ke, aops)
    2. Converts sets to sorted lists for JSON serialization
    
    Modifies search_results in place.
    
    Args:
        search_results: Dictionary of search results keyed by KER ID
        all_kers: Dictionary of all KER data
    
    Returns:
        Modified search_results dictionary (same reference)
    """
    for ker_id, result in search_results.items():
        # Enrich with KER metadata
        ker_data = all_kers.get(ker_id, {})
        result['upstream_ke'] = ker_data.get('upstream_ke', {}).get('title', 'N/A')
        result['downstream_ke'] = ker_data.get('downstream_ke', {}).get('title', 'N/A')
        result['aops'] = ker_data.get('aop_ids', [])
        
        # Convert sets to sorted lists for JSON serialization
        for field in result.get("snippets_by_field", {}):
            if isinstance(result["snippets_by_field"][field], set):
                result["snippets_by_field"][field] = sorted(list(result["snippets_by_field"][field]))
        
        if isinstance(result.get("terms_found"), set):
            result["terms_found"] = sorted(list(result["terms_found"]))
        if isinstance(result.get("matched_fields"), set):
            result["matched_fields"] = sorted(list(result["matched_fields"]))
        if isinstance(result.get("co_occurrences"), set):
            result["co_occurrences"] = sorted([list(pair) for pair in result["co_occurrences"]])
        if isinstance(result.get("co_occurrence_fields"), set):
            result["co_occurrence_fields"] = sorted(list(result["co_occurrence_fields"]))
    
    return search_results


def get_transformer(name: str):
    """
    Get transformer function by name.
    
    Args:
        name: Name of the transformer function
        
    Returns:
        Transformer function or None if not found
    """
    return TRANSFORMERS.get(name)


def build_aop_to_ker_mapping(aop_info: dict) -> dict:
    """
    Build reverse mapping from AOP IDs to KER IDs.
    
    Transforms AOP data structure where each AOP has a 'kers' dict
    into a simpler mapping of AOP ID -> list of KER IDs.
    
    Args:
        aop_info: Dictionary of AOP data with 'kers' field
                  (aop_info[aop_id]['kers'] is a dict with KER IDs as keys)
        
    Returns:
        Dict mapping aop_id -> list of ker_ids
        
    Example:
        >>> aop_info = {'1': {'kers': {'123': {...}, '456': {...}}}}\n        >>> build_aop_to_ker_mapping(aop_info)
        {'1': ['123', '456']}
    """
    aop_to_ker_dict = {}
    for aop_id, aop_data in aop_info.items():
        ker_dict = aop_data.get('kers', {})
        if ker_dict:
            aop_to_ker_dict[aop_id] = list(ker_dict.keys())
    return aop_to_ker_dict


def build_submitted_title_by_event_id(title_entries: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build mapping from event_id to preprocessed submitted title.

    Args:
        title_entries: List of entries with keys `event_id` and `submitted_title`.

    Returns:
        Dict mapping string event IDs to non-empty submitted titles.
    """
    return {
        str(record["event_id"]): record.get("submitted_title", "")
        for record in title_entries
        if record.get("event_id") is not None and record.get("submitted_title")
    }

def build_seizure_extracted_rows(seizure_aop_curations: Dict[str, Dict[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for aop_id, events in seizure_aop_curations.items():
        for event_index, event_data in events.items():
            rows.append({
                'aop_id': aop_id,
                'event_index': event_data.get('event_index', event_index),
                'row_index': event_data.get('row_index', ''),
                'event_id': event_data.get('event_id', ''),
                'title': event_data.get('title', ''),
                'harmonized_event': event_data.get('harmonized_event', ''),
                'event_match': event_data.get('event_match', False),
                'title_from_wiki': event_data.get('title_from_wiki', ''),
                'references': event_data.get('references', ''),
                'target_family': event_data.get('target_family', ''),
            })
    return rows


def build_seizure_ke_desc_mapping_rows(ke_description_mappings: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            'ke_description': ke_desc,
            'assays': mapping.get('assays', []),
            'target_families': list(mapping.get('target_families', set()))
        }
        for ke_desc, mapping in ke_description_mappings.items()
    ]


def build_seizure_summary_rows(harmonized_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for harmonized_title, details in harmonized_summary.get('harmonized_kes', {}).items():
        rows.append({
            'harmonized_title': harmonized_title,
            'total_events': details.get('total_events', 0),
            'lobo_count': details.get('lobo_count', 0),
            'lobos': details.get('lobos', []),
            'event_ids': details.get('event_ids', []),
            'aop_ids': details.get('aop_ids', []),
            'references': details.get('references', []),
            'target_families': details.get('target_families', []),
        })
    return rows


def build_seizure_ke_desc_to_harmonized_rows(ke_description_to_harmonized: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build rows from reviewed KE description to harmonized KE mapping.
    
    Args:
        ke_description_to_harmonized: List of reviewed mapping dicts from review_matches()
    """
    return [
        {
            'ke_description': mapping.get('input_term', ''),
            'harmonized_ke_match': mapping.get('matched_term', ''),
            'match_score': mapping.get('match_score', ''),
            'human_verified': mapping.get('human_verified', ''),
            'suggested_match': mapping.get('suggested_match', ''),
        }
        for mapping in ke_description_to_harmonized
    ]


def flatten_harmonized_events(harmonized_events: Dict[str, Dict[str, Dict[int, Dict]]]) -> List[Dict[str, Any]]:
    """
    Flatten nested harmonized seizure AOP events structure into list of row dictionaries.
    
    This shared helper eliminates duplicate flattening logic used by CSV and Excel exports.
    
    Args:
        harmonized_events: Nested dictionary structure:
            {harmonized_title: {
                event_id: {
                    row_index: {event_data}
                }
            }}
            
    Returns:
        List of flat dictionaries suitable for CSV/Excel export
    """
    rows = []
    for harmonized_title, events_dict in harmonized_events.items():
        for event_id, row_indices in events_dict.items():
            for row_index, event_data in row_indices.items():
                row_data = {
                    'harmonized_title': harmonized_title,
                    'aop_id': event_data.get('aop_id', ''),
                    'event_id': event_id,
                    'row_index': row_index,
                    'event_index': event_data.get('event_index', ''),
                    'title': event_data.get('title', ''),
                    'title_from_wiki': event_data.get('title_from_wiki', ''),
                    'lobo': event_data.get('lobo', ''),
                    'event_match': event_data.get('event_match', False),
                    'references': event_data.get('references', ''),
                    'target_family': event_data.get('target_family', ''),
                }
                rows.append(row_data)
    return rows
