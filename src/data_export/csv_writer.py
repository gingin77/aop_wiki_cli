"""
Unified CSV writing functions.

This module provides the core CSV writing functionality that works with
field configurations to produce consistent, well-formatted CSV files.

Key features:
- Automatic nested dict value extraction
- Configurable field transformations
- Built-in sorting support
- Consistent error handling
"""

import csv
from pathlib import Path
from typing import Dict, List, Any, Union, Optional
from .field_definitions import FieldConfigSet
from .transformers import get_transformer, flatten_harmonized_events


def get_nested_value(data: Dict, key_path: str, default: Any = None) -> Any:
    """
    Get value from nested dictionary using dot notation.
    
    Examples:
        get_nested_value(data, 'title') -> data['title']
        get_nested_value(data, 'completion_score.percent') -> data['completion_score']['percent']
    
    Args:
        data: Source dictionary
        key_path: Key path with dot notation for nested access
        default: Default value if key not found
        
    Returns:
        Value from nested dict or default
    """
    keys = key_path.split('.')
    value = data
    
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key, default)
            if value is None:
                return default
        else:
            return default
    
    return value if value is not None else default


def _transform_row(data: Dict, field_config: FieldConfigSet) -> Dict[str, Any]:
    """
    Transform a data dictionary into a flat CSV row using field configuration.
    
    Internal helper function for write_csv().
    
    This function:
    1. Extracts values from nested dicts using source_key
    2. Applies any specified transformers
    3. Uses default values for missing data
    4. Returns a flat dict ready for CSV writing
    
    Args:
        data: Source data dictionary
        field_config: Field configuration set defining the transformation
    
    Returns:
        Flat dictionary with keys matching CSV column names
    """
    row = {}
    
    for field in field_config.fields:
        # Get value from source (handles nested dicts)
        value = get_nested_value(data, field.source_key, field.default)
        
        # Apply transformer if specified
        if field.transformer:
            if callable(field.transformer):
                # Direct function reference
                value = field.transformer(value)
            elif isinstance(field.transformer, str):
                # String name lookup
                transformer_func = get_transformer(field.transformer)
                if transformer_func:
                    value = transformer_func(value)
        
        row[field.name] = value
    
    return row


def write_concordance_csv(
    concordance_kers: Dict[str, Dict],
    output_path: Union[str, Path]
) -> None:
    """
    Write concordance search results to CSV.
    
    Flattens the nested structure where each KER has multiple snippets
    across multiple fields. Creates one row per snippet.
    
    Args:
        concordance_kers: Dictionary with structure:
            {ker_id: {
                'snippets_by_field': {field: [snippets]},
                'terms_found': [terms],
                'fields': [fields],
                'upstream_ke': title,
                'downstream_ke': title,
                'aops': [aop_ids]
            }}
        output_path: Path where CSV will be saved
    """
    from .field_definitions import CONCORDANCE_KER_FIELDS
    
    # Flatten nested structure into rows
    rows = []
    for ker_id, result in concordance_kers.items():
        # Iterate through each field that had matches
        for field in result.get('snippets_by_field', {}):
            snippets = result['snippets_by_field'][field]
            # Create a row for each snippet
            for snippet in snippets:
                row_data = {
                    'ker_id': ker_id,
                    'upstream_ke': result.get('upstream_ke', 'N/A'),
                    'downstream_ke': result.get('downstream_ke', 'N/A'),
                    'aops': result.get('aops', []),
                    'terms_found': result.get('terms_found', []),
                    'field': field,
                    'snippet': snippet
                }
                rows.append(row_data)
    
    # Use standard write_csv with flattened data
    write_csv(
        data=rows,
        field_config=CONCORDANCE_KER_FIELDS,
        output_path=output_path,
        sort_key=None
    )


def write_seizure_aop_csv(
    seizure_aop_curations: Dict[str, Dict],
    output_path: Union[str, Path]
) -> None:
    """
    Write seizure AOP curations to CSV.
    
    Flattens the nested structure where each AOP has multiple events.
    Creates one row per event with its AOP context.
    
    Args:
        seizure_aop_curations: Dictionary with structure:
            {aop_id: {
                event_index: {
                    'row_index': int,
                    'event_index': int,
                    'title': str,
                    'event_id_from_sheet': str or None,
                    'harmonized_event': str or None,
                    'event_match': bool,
                    'title_from_wiki': str or None
                }
            }}
        output_path: Path where CSV will be saved
    """
    from .field_definitions import SEIZURE_AOP_EVENT_FIELDS
    
    # Flatten nested structure into rows
    rows = []
    for aop_id, events in seizure_aop_curations.items():
        for event_index, event_data in events.items():
            row_data = {
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
            }
            rows.append(row_data)
    
    # Use standard write_csv with flattened data, sorted by AOP ID and event index
    write_csv(
        data=rows,
        field_config=SEIZURE_AOP_EVENT_FIELDS,
        output_path=output_path,
        sort_key='aop_id',
        reverse_sort=False
    )


def write_harmonized_seizure_aop_csv(
    harmonized_kes: Dict[str, Dict[str, Dict[int, Dict]]],
    output_path: Union[str, Path]
) -> None:
    """
    Write harmonized seizure AOP events to CSV.
    
    Flattens the nested structure where events are organized by harmonized title.
    Creates one row per event occurrence with harmonized context.
    
    Args:
        harmonized_kes: Dictionary with structure:
            {harmonized_title: {
                event_id: {
                    row_index: {
                        'row_index': int,
                        'event_index': int,
                        'title': str,
                        'event_id': str or None,
                        'harmonized_event': str or None,
                        'event_match': bool,
                        'title_from_wiki': str or None,
                        'lobo': str or None,
                        ... (other event data fields)
                    }
                }
            }}
        output_path: Path where CSV will be saved
    """
    from .field_definitions import HARMONIZED_SEIZURE_AOP_EVENT_FIELDS
    
    # Flatten nested structure using shared helper
    rows = flatten_harmonized_events(harmonized_kes)
    
    # Use standard write_csv with flattened data, sorted by LOBO
    write_csv(
        data=rows,
        field_config=HARMONIZED_SEIZURE_AOP_EVENT_FIELDS,
        output_path=output_path,
        sort_key='lobo',
        reverse_sort=False
    )


def write_summary_harmonized_seizure_aop_csv(
    harmonized_summary: Dict[str, Any],
    output_path: Union[str, Path]
) -> None:
    """
    Write harmonized seizure AOP summary to CSV.
    
    Creates one row per harmonized title with aggregate statistics.
    
    Args:
        harmonized_summary: Dictionary with structure:
            {
                'count_unique_harmonized_kes': int,
                'excluded_count': int,
                'nan_count': int,
                'harmonized_kes': {
                    harmonized_title: {
                        'total_events': int,
                        'event_ids': list,
                        'lobos': list,
                        'lobo_count': int
                    }
                }
            }
        output_path: Path where CSV will be saved
    """
    from .field_definitions import HARMONIZED_SEIZURE_AOP_SUMMARY_FIELDS
    
    # Flatten the harmonized_kes dictionary into rows
    rows = []
    harmonized_kes = harmonized_summary.get('harmonized_kes', {})
    
    for harmonized_title, details in harmonized_kes.items():
        row_data = {
            'harmonized_title': harmonized_title,
            'total_events': details.get('total_events', 0),
            'lobo_count': details.get('lobo_count', 0),
            'lobos': details.get('lobos', []),
            'event_ids': details.get('event_ids', []),
            'aop_ids': details.get('aop_ids', []),
            'references': details.get('references', []),
            'target_families': details.get('target_families', []),
        }
        rows.append(row_data)
    
    # Use standard write_csv with flattened data, sorted by harmonized title
    write_csv(
        data=rows,
        field_config=HARMONIZED_SEIZURE_AOP_SUMMARY_FIELDS,
        output_path=output_path,
        sort_key='harmonized_title',
        reverse_sort=False
    )


def write_ke_description_to_harmonized_mapping_csv(
    ke_description_to_harmonized_mapping: Dict[str, Dict],
    output_path: Union[str, Path]
) -> None:
    """
    Write KE description to harmonized KE mapping to CSV.
    
    Creates one row per KE description with fuzzy matching results showing:
    - Original KE description from assays sheet
    - Matched harmonized KE title
    - Match score and type
    - Associated assays and target families
    
    Args:
        ke_description_to_harmonized_mapping: Dictionary with structure:
            {
                ke_description: {
                    'harmonized_ke_match': str or None,
                    'match_score': float or None,
                }
            }
        output_path: Path where CSV will be saved
    """
    from .field_definitions import SEIZURE_KE_DESC_TO_HARMONIZED_FIELDS
    
    # Flatten the mapping dictionary into rows
    rows = []
    for ke_desc, mapping in ke_description_to_harmonized_mapping.items():
        row_data = {
            'ke_description': ke_desc,
            'harmonized_ke_match': mapping.get('harmonized_ke_match', ''),
            'match_score': mapping.get('match_score', ''),
        }
        rows.append(row_data)
    
    # Sort by match score descending (best matches first)
    write_csv(
        data=rows,
        field_config=SEIZURE_KE_DESC_TO_HARMONIZED_FIELDS,
        output_path=output_path,
        sort_key='match_score',
        reverse_sort=True
    )


def write_csv(
    data: Union[Dict, List[Dict]],
    field_config: FieldConfigSet,
    output_path: Union[str, Path],
    sort_key: Optional[str] = None,
    reverse_sort: bool = True
) -> None:
    """
    Write data to CSV file using field configuration.
    
    This is the main CSV writing function. It handles:
    - Automatic directory creation
    - Dict or list input
    - Optional sorting
    - Row transformation
    - Progress feedback
    
    Args:
        data: Dictionary of items (keyed by ID) or list of items
        field_config: Field configuration set defining columns and transformations
        output_path: Path to output CSV file
        sort_key: Optional key to sort by (supports dot notation, e.g., 'completion_score.percent')
        reverse_sort: Whether to sort in descending order (default True)
    
    Example:
        write_csv(
            data=aop_dict,
            field_config=AOP_FIELDS_MIN,
            output_path='outputs/aops.csv',
            sort_key='completion_score.percent'
        )
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert dict to list if needed
    if isinstance(data, dict):
        items = list(data.values())
    else:
        items = data
    
    if not items:
        print(f"⚠ No data to write to {output_path}")
        return
    
    # Sort if requested
    if sort_key:
        try:
            items = sorted(
                items,
                key=lambda x: get_nested_value(x, sort_key, 0),
                reverse=reverse_sort
            )
        except (TypeError, KeyError) as e:
            print(f"⚠ Warning: Could not sort by '{sort_key}': {e}")
    
    # Transform all rows
    rows = [_transform_row(item, field_config) for item in items]
    
    # Write CSV
    fieldnames = field_config.get_field_names()
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"✓ CSV written to {output_path} ({len(rows)} rows)")


def write_summary_stats_csv(
    stats: Dict[str, Any],
    output_path: Union[str, Path],
    metric_label: str = 'Metric',
    value_label: str = 'Value'
) -> None:
    """
    Write simple key-value summary statistics to CSV.
    
    Creates a two-column CSV with metric names and their values.
    Automatically formats float values to 2 decimal places.
    
    Args:
        stats: Dictionary of metric name -> value
        output_path: Path to output CSV file
        metric_label: Header for the metric column (default 'Metric')
        value_label: Header for the value column (default 'Value')
    
    Example:
        write_summary_stats_csv(
            stats={'total_aops': 523, 'average_score': 67.45},
            output_path='outputs/summary_stats.csv'
        )
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([metric_label, value_label])
        
        for metric, value in stats.items():
            # Format floats nicely
            if isinstance(value, float):
                value = f"{value:.2f}"
            writer.writerow([metric, value])
    
    print(f"✓ Summary statistics written to {output_path} ({len(stats)} metrics)")
