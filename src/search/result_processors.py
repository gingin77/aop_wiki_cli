"""
Result processors for search operations.

Functions to process, filter, and transform search results after the initial search.
"""
from typing import Dict, Tuple, Optional
import logging


def serialize_search_results(results: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Convert sets to lists in search results for serialization.
    
    Prepares results for export to any format (JSON, CSV, etc.).
    Modifies results in-place and returns them for chaining.
    
    Args:
        results: Dictionary of search results with entity IDs as keys
        
    Returns:
        The same results dictionary with sets converted to sorted lists
    """
    for entity_id, result in results.items():
        # Convert snippets by field structure
        for field in result["snippets_by_field"]:
            result["snippets_by_field"][field] = sorted(list(result["snippets_by_field"][field]))
        
        # Convert other sets to lists
        result["terms_found"] = sorted(list(result["terms_found"]))
        result["matched_fields"] = sorted(list(result["matched_fields"]))
        result["co_occurrences"] = sorted([list(pair) for pair in result["co_occurrences"]])
        
        # Convert co_occurrence_fields if present
        if "co_occurrence_fields" in result:
            result["co_occurrence_fields"] = sorted(list(result["co_occurrence_fields"]))
    
    return results


def filter_by_co_occurrence(
    results: Dict[str, Dict], 
    entity_type: str, 
    logger: Optional[logging.Logger] = None
) -> Dict[str, Dict]:
    """
    Filter results to only entities with co-occurrence matches.
    
    Args:
        results: Dictionary of search results
        entity_type: Type of entities (for logging) e.g., "aops", "events"
        logger: Optional logger instance
        
    Returns:
        Filtered dictionary containing only entities with co-occurrences
    """
    filtered = {
        entity_id: result 
        for entity_id, result in results.items() 
        if len(result["co_occurrences"]) > 0
    }
    
    if logger:
        logger.info(f"Filtered to {len(filtered)} {entity_type} with co-occurrence matches")
    
    return filtered


def sort_by_priority_field(
    results: Dict[str, Dict], 
    priority_field: str,
    entity_type: str,
    logger: Optional[logging.Logger] = None
) -> Tuple[Dict[str, Dict], int]:
    """
    Sort results by priority field co-occurrence.
    
    Entities with co-occurrences in the priority field are listed first,
    followed by others. Within each group, sorted by entity_id numerically.
    
    Args:
        results: Dictionary of search results
        priority_field: Name of the priority field
        entity_type: Type of entities (for logging)
        logger: Optional logger instance
        
    Returns:
        Tuple of (sorted_results_dict, priority_count)
    """
    # Sort by has_priority_co_occurrence (True first), then by entity_id
    sorted_results = dict(sorted(
        results.items(),
        key=lambda x: (not x[1].get("has_priority_co_occurrence", False), int(x[0]))
    ))
    
    # Count priority matches
    priority_count = sum(1 for r in sorted_results.values() if r.get("has_priority_co_occurrence", False))
    
    if logger and priority_count > 0:
        logger.info(f"Found {priority_count} {entity_type} with co-occurrences in priority field '{priority_field}'")
    
    return sorted_results, priority_count
