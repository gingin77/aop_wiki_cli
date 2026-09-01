"""
Event-first iterative search functionality.

Supports finding the entities attached to a key event by searching KE titles
first, then collecting what contains those events -- the AOPs they belong to
(find_aops_containing_events) or the KERs they are an endpoint of
(find_kers_containing_events). This enables flexible "event-first" searches
using term lists instead of hard-coded event IDs.
"""
import re
from datetime import date

from src.parsers import collect_events_from_xml, collect_aops_from_xml, collect_entity_with_cache
from src.search.search_text_by_field import build_term_pattern, parse_and_clean_text


def find_events_by_title_terms(events_dict, title_terms, case_sensitive=False):
    """
    Find events whose titles match any of the given terms.
    
    Args:
        events_dict: Dictionary of events keyed by event ID
        title_terms: List of terms to search for in event titles
        case_sensitive: Whether to perform case-sensitive matching
        
    Returns:
        dict: Matching events with match metadata
              {event_id: {"event_info": {...}, "matched_terms": [...]}}
    """
    matched_events = {}
    
    for event_id, event_info in events_dict.items():
        title = event_info.get("title", "")
        if not title:
            continue
        
        # Clean and prepare title for matching
        clean_title = parse_and_clean_text(title)
        
        matched_terms = []
        for term in title_terms:
            pattern = build_term_pattern(term)
            search_text = clean_title if case_sensitive else clean_title.lower()
            
            if re.search(pattern, search_text):
                matched_terms.append(term)
        
        if matched_terms:
            matched_events[event_id] = {
                "event_info": event_info,
                "matched_terms": matched_terms,
                "title": title,
            }
    
    return matched_events


def find_aops_containing_events(aops_dict, event_ids):
    """
    Find AOPs that contain any of the specified events.
    
    Args:
        aops_dict: Dictionary of AOPs keyed by AOP ID
        event_ids: List/set of event IDs to search for
        
    Returns:
        dict: Matching AOPs with source event mapping
              {aop_id: {"aop_info": {...}, "source_events": [...]}}
    """
    event_ids_str = {str(eid) for eid in event_ids}
    matched_aops = {}
    
    for aop_id, aop_info in aops_dict.items():
        aop_event_ids = {str(eid) for eid in aop_info.get("event_ids", [])}
        
        # Find intersection of AOP's events with our target events
        source_events = aop_event_ids & event_ids_str
        
        if source_events:
            matched_aops[aop_id] = {
                "aop_info": aop_info,
                "source_events": list(source_events),
                "title": aop_info.get("title", ""),
                "num_matching_events": len(source_events),
                "total_events": len(aop_event_ids),
            }
    
    return matched_aops


def find_kers_containing_events(kers_dict, event_ids):
    """
    Find KERs that have any of the specified events as an endpoint.

    A KER has exactly two endpoints, so a KER is returned when either its
    upstream or its downstream KE is in event_ids. Both endpoints can match
    when the search covers a run of connected events.

    Args:
        kers_dict: Dictionary of KERs keyed by KER ID
        event_ids: List/set of event IDs to search for

    Returns:
        dict: Matching KERs with endpoint role mapping
              {ker_id: {"ker_info": {...}, "source_events": [...],
                        "roles": {event_id: "upstream" | "downstream"},
                        "title": "upstream title -> downstream title",
                        "upstream_ke_id": ..., "downstream_ke_id": ...}}
    """
    event_ids_str = {str(eid) for eid in event_ids}
    matched_kers = {}

    for ker_id, ker_info in kers_dict.items():
        upstream = ker_info.get("upstream_ke", {})
        downstream = ker_info.get("downstream_ke", {})
        upstream_id = str(upstream.get("id", ""))
        downstream_id = str(downstream.get("id", ""))

        # Record which side each target event sits on; a KE can be the
        # upstream of one KER and the downstream of another. A KER missing an
        # endpoint yields an empty ID, which must never count as a match.
        roles = {}
        if upstream_id and upstream_id in event_ids_str:
            roles[upstream_id] = "upstream"
        if downstream_id and downstream_id in event_ids_str:
            roles[downstream_id] = "downstream"

        if roles:
            matched_kers[ker_id] = {
                "ker_info": ker_info,
                "source_events": list(roles.keys()),
                "roles": roles,
                "title": f'{upstream.get("title", "?")} -> {downstream.get("title", "?")}',
                "upstream_ke_id": upstream_id,
                "downstream_ke_id": downstream_id,
            }

    return matched_kers


def filter_aops_by_title_exclusion(aops_dict, exclusion_terms):
    """
    Filter out AOPs whose titles contain any exclusion terms.
    
    Args:
        aops_dict: Dictionary from find_aops_containing_events()
        exclusion_terms: List of terms to exclude
        
    Returns:
        dict: Filtered AOPs dictionary
    """
    if not exclusion_terms:
        return aops_dict
    
    filtered = {}
    for aop_id, aop_data in aops_dict.items():
        title = aop_data.get("title", "")
        clean_title = parse_and_clean_text(title).lower()
        
        should_exclude = False
        for term in exclusion_terms:
            pattern = build_term_pattern(term)
            if re.search(pattern, clean_title):
                should_exclude = True
                break
        
        if not should_exclude:
            filtered[aop_id] = aop_data
    
    return filtered


def search_events_to_aops(search_params, work_date=None, cache_dir='outputs/cache',
                          force_refresh=False, logger=None):
    """
    Main entry point for event-to-AOP iterative search.
    
    Search flow:
    1. Collect all events and AOPs from cache or XML
    2. Find events matching title terms
    3. Find AOPs containing those events  
    4. Apply exclusion filters
    
    Args:
        search_params: Dict with search configuration:
            - "ke_title_terms": List of terms to search in event titles
            - "aop_title_exclusion_terms": Optional list of terms to exclude from AOP titles
            - "oecd_status_filter": Optional list of OECD statuses to include
        work_date: Date for cache files (defaults to today)
        cache_dir: Directory for cache files  
        force_refresh: Force fresh data collection
        logger: Optional logger instance
        
    Returns:
        dict with keys:
            - "summary": Search statistics
            - "matched_events": Events matching title terms
            - "matched_aops": AOPs containing matched events
    """
    work_date = work_date or date.today()
    ke_title_terms = search_params.get("ke_title_terms", [])
    
    if not ke_title_terms:
        raise ValueError("search_params must include 'ke_title_terms' list")
    
    # Step 1: Collect entities
    if logger:
        logger.info(f"Collecting events and AOPs from cache or XML...")
    
    events_dict = collect_entity_with_cache(
        'events', collect_events_from_xml, work_date, cache_dir, force_refresh, logger
    )
    aops_dict = collect_entity_with_cache(
        'aops', collect_aops_from_xml, work_date, cache_dir, force_refresh, logger
    )
    
    # Step 2: Find events by title terms
    if logger:
        logger.info(f"Searching event titles for terms: {ke_title_terms}")
    
    matched_events = find_events_by_title_terms(events_dict, ke_title_terms)
    
    if logger:
        logger.info(f"Found {len(matched_events)} events matching title terms")
    
    # Step 3: Find AOPs containing matched events
    matched_event_ids = list(matched_events.keys())
    matched_aops = find_aops_containing_events(aops_dict, matched_event_ids)
    
    if logger:
        logger.info(f"Found {len(matched_aops)} AOPs containing matched events")
    
    # Step 4: Apply exclusion filters
    aop_exclusion_terms = search_params.get("aop_title_exclusion_terms", [])
    if aop_exclusion_terms:
        before_count = len(matched_aops)
        matched_aops = filter_aops_by_title_exclusion(matched_aops, aop_exclusion_terms)
        if logger:
            logger.info(f"Filtered to {len(matched_aops)} AOPs after exclusion ({before_count - len(matched_aops)} excluded)")
    
    # Optional: Filter by OECD status
    oecd_filter = search_params.get("oecd_status_filter")
    if oecd_filter:
        filtered_aops = {}
        for aop_id, aop_data in matched_aops.items():
            status = aop_data["aop_info"].get("oecd_status", "")
            if status in oecd_filter:
                filtered_aops[aop_id] = aop_data
        matched_aops = filtered_aops
        if logger:
            logger.info(f"Filtered to {len(matched_aops)} AOPs with OECD status in {oecd_filter}")
    
    # Build summary
    summary = {
        "search_mode": "event_to_aop",
        "ke_title_terms": ke_title_terms,
        "total_events_searched": len(events_dict),
        "total_aops_searched": len(aops_dict),
        "total_events_matched": len(matched_events),
        "total_aops_matched": len(matched_aops),
        "matched_event_ids": matched_event_ids,
        "matched_aop_ids": list(matched_aops.keys()),
        "event_totals_by_term": _count_events_by_term(matched_events),
    }
    
    return {
        "summary": summary,
        "matched_events": matched_events,
        "matched_aops": matched_aops,
        "events_dict": events_dict,
    }


def _count_events_by_term(matched_events):
    """Count how many events matched each search term."""
    term_counts = {}
    for event_id, event_data in matched_events.items():
        for term in event_data.get("matched_terms", []):
            term_counts[term] = term_counts.get(term, 0) + 1
    return term_counts
