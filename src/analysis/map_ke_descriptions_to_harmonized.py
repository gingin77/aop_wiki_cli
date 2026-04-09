"""
Map KE descriptions from assays sheet to harmonized KE titles from harmonization sheet.

This module provides fuzzy matching capabilities to link KE descriptions mentioned 
in the assays sheet to the actual harmonized KE titles defined in the harmonization sheet.
"""
import pprint as pp
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple, Optional

# Generic suffixes that shouldn't drive match scores
GENERIC_SUFFIXES = {'receptor', 'receptors', 'transporter', 'transporters', 
                    'channel', 'channels', 'enzyme', 'enzymes', 'kinase', 'kinases',
                    'r', 'activity', 'binding', 'inhibition', 'activation'}


def calculate_similarity(str1: str, str2: str) -> float:
    """Calculate similarity ratio between two strings (0.0 to 1.0)."""
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()


def calculate_similarity_weighted(str1: str, str2: str) -> float:
    """
    Calculate similarity with prefix weighting.
    
    Strips generic suffixes (receptor, transporter, etc.) and averages
    the full-string score with the prefix-only score. This prevents
    matches driven solely by common suffixes.
    """
    base_score = SequenceMatcher(None, str1.lower(), str2.lower()).ratio()
    
    # Extract prefix by removing generic suffixes
    words1 = str1.lower().split()
    words2 = str2.lower().split()
    prefix1 = ' '.join(w for w in words1 if w not in GENERIC_SUFFIXES)
    prefix2 = ' '.join(w for w in words2 if w not in GENERIC_SUFFIXES)
    
    # If both have meaningful prefixes, weight the prefix match
    if prefix1 and prefix2:
        prefix_score = SequenceMatcher(None, prefix1, prefix2).ratio()
        return (base_score + prefix_score) / 2
    
    return base_score


def fuzzy_match_ke_description(
    ke_description: str,
    harmonized_kes: List[str] | Dict[str, Any],
    threshold: float = 0.6,
    use_weighted: bool = True
) -> Optional[Tuple[str, float] | Tuple[str, Any, float]]:
    """
    Find the best matching harmonized KE for a given KE description.
    
    Args:
        ke_description: KE description from assays sheet
        harmonized_kes: List of harmonized KE titles, OR dict of {title: id}
        threshold: Minimum similarity score to consider a match (0.0-1.0)
        use_weighted: Use prefix-weighted similarity (default True)
        
    Returns:
        If input is list: Tuple of (matched_ke, similarity_score) or None
        If input is dict: Tuple of (matched_ke, matched_id, similarity_score) or None
    """
    best_match = None
    best_id = None
    best_score = 0.0
    
    similarity_fn = calculate_similarity_weighted if use_weighted else calculate_similarity
    
    # Handle both list and dict inputs
    if isinstance(harmonized_kes, dict):
        items = harmonized_kes.items()
    else:
        items = [(ke, None) for ke in harmonized_kes]
    
    for title, item_id in items:
        score = similarity_fn(ke_description, title)
        if score > best_score:
            best_score = score
            best_match = title
            best_id = item_id
    
    if best_score >= threshold:
        if isinstance(harmonized_kes, dict):
            return (best_match, best_id, best_score)
        return (best_match, best_score)
    return None

def generate_match_metrics(enhanced_mapping: Dict[str, Dict]) -> Dict[str, Any]:
    """
    Generate a summary report of KE description matching results.
    
    Args:
        enhanced_mapping: Mapping with match information
        
    Returns:
        Dictionary with matching statistics
    """
    total = len(enhanced_mapping)
    
    matched_scores = [
        v.get('match_score') 
        for v in enhanced_mapping.values() 
        if v.get('match_score') is not None
    ]
    matched_count = len(matched_scores)
    avg_score = sum(matched_scores) / matched_count if matched_count > 0 else 0.0
    
    unmatched_descriptions = [
        ke_desc for ke_desc, data in enhanced_mapping.items() 
        if data.get('match_score') is None
    ]
    
    return {
        'total_ke_descriptions': total,
        'fuzzy_matches': matched_count,
        'no_matches': len(unmatched_descriptions),
        'match_rate': (total - len(unmatched_descriptions)) / max(total, 1),
        'average_match_score': avg_score,
        'unmatched_descriptions': unmatched_descriptions
    }

# Main orchestration function to map KE descriptions to harmonized KEs
def map_ke_descriptions_to_harmonized_kes(
    ke_description_to_assays_mapping: Dict[str, Dict],
    harmonized_kes_list: List[str],
    threshold: float = 0.6
) -> Dict[str, Dict]:
    """
    Map KE descriptions to harmonized KE titles with fuzzy matching.
    
    Args:
        ke_description_to_assays_mapping: {ke_description: metadata_dict}
        harmonized_kes_list: List of harmonized KE titles to match against
        threshold: Minimum similarity score (0.0-1.0)
        
    Returns:
        Same mapping with 'harmonized_ke_match' and 'match_score' added to each entry.
    """
    enhanced_mapping = {}
    
    for ke_desc, mapping_data in ke_description_to_assays_mapping.items():
        enhanced_entry = mapping_data.copy()
        enhanced_entry["input_term"] = ke_desc
        
        matched_ke = None
        match_score = None
        
        # Use fuzzy matching to find the best harmonized KE match for the KE description
        fuzzy_result = fuzzy_match_ke_description(ke_desc, harmonized_kes_list, threshold)
        if fuzzy_result:
            matched_ke, match_score = fuzzy_result
        
        enhanced_entry['matched_term'] = matched_ke
        enhanced_entry['match_score'] = match_score
        
        enhanced_mapping[ke_desc] = enhanced_entry
    
    return enhanced_mapping


def enrich_target_families(target_families_to_h_events_and_assays, all_events):
    """
    Using fuzzy matching for TF as input, with multiple match options
    - KE Titles
    - Optional, EC Objects
    - Optional, EC Processes
    """
    # For reference, path to input for all_events outputs/cache/03-11-2026/all_events_03-11-2026.json
    tfs_to_events = {}
    event_title_to_id_dict = {event_data['title']: event_id for event_id, event_data in all_events.items()}
    for tf, data in target_families_to_h_events_and_assays.items():
        tfs_to_events[tf] = {
            'input_term': tf,
            'match_with_h_event': False,
            'h_events': [],
            'matched_term': None,
            'match_score': None,
            'matched_event_id': None,
        }
        h_events = data.get('h_events', [])

        if h_events != []:
            tfs_to_events[tf]['match_with_h_event'] = True
            tfs_to_events[tf]['h_events'] = h_events
            continue
        
        # Try to find matches for the TF name in the KE descriptions
        fuzzy_result = fuzzy_match_ke_description(tf, event_title_to_id_dict, threshold=0.5)
        if fuzzy_result:
            matched_event_title, matched_event_id, match_score = fuzzy_result
            tfs_to_events[tf]['matched_term'] = matched_event_title
            tfs_to_events[tf]['match_score'] = match_score
            tfs_to_events[tf]['matched_event_id'] = matched_event_id

    # Sort tfs_to_events by match_score (descending)
    tfs_to_events_sorted = dict(sorted(
        tfs_to_events.items(),
        key=lambda x: x[1].get('match_score') or 0,
        reverse=True
    ))
    for tf, data in tfs_to_events_sorted.items():
        if data.get('match_with_h_event'):
            print(f"TF: {tf} was manually matched to harmonized events: {data.get('h_events')}")
        elif data.get('matched_term') is not None:
            print(f"Score: {data.get('match_score')} TF: {tf} {data.get('matched_event_id')}: {data.get('matched_term')}")
        else:
            print(f"No match for TF: {tf}")
    return tfs_to_events_sorted


def map_assays_to_events_via_target_families(
    enriched_target_families_reviewed: List[Dict],
    target_families_to_h_events_and_assays: Dict[str, Dict]
) -> Dict[str, Dict]:
    """
    Map events to assays through their shared target family associations.
    
    This function bridges events to assays using target families as an intermediate link:
    1. Target families have associated assays (from target_families_to_h_events_and_assays)
    2. Target families have associated events (from enriched_target_families_reviewed)
    3. Therefore, events can be linked to assays through their common target family
    
    Args:
        enriched_target_families_reviewed: List of reviewed target family mappings with event matches.
            Each item has keys: target_family, h_events, event, matched_event_id, human_verified, suggested_event
        target_families_to_h_events_and_assays: Dict mapping target family names to their assays and h_events.
            Each value has keys: h_events (list), assays (list)
    
    Returns:
        Dict with:
        - 'event_to_assays': Maps each event title to its linked assays and target families
        - 'summary': Statistics on mappings
    """
    event_to_assays = {}
    
    # Build target family to events lookup from reviewed data
    tf_to_events_lookup = {}
    for item in enriched_target_families_reviewed:
        tf_name = item.get('target_family')
        if not tf_name:
            continue
            
        events = []
        
        # Include pre-existing harmonized event mappings from workbook
        h_events = item.get('h_events', [])
        if h_events:
            events.extend([{'title': e, 'source': 'harmonized_workbook', 'event_id': None} for e in h_events])
        
        # Include fuzzy-matched event only if human accepted the match
        if item.get('human_verified', False):
            matched_event = item.get('event')
            matched_event_id = item.get('matched_event_id')
            if matched_event:
                events.append({
                    'title': matched_event,
                    'source': 'fuzzy_matched',
                    'event_id': matched_event_id,
                    'match_score': item.get('match_score')
                })
        
        # Include suggested event if manually provided (regardless of human_verified status)
        suggested = item.get('suggested_event')
        if suggested:
            events.append({
                'title': suggested,
                'source': 'manual_suggestion',
                'event_id': None
            })
        
        tf_to_events_lookup[tf_name] = events
    
    # Map events to assays through target families
    for tf_name, tf_data in target_families_to_h_events_and_assays.items():
        assays = tf_data.get('assays', [])
        events = tf_to_events_lookup.get(tf_name, [])
        
        for event in events:
            event_key = event['title']
            if event_key not in event_to_assays:
                event_to_assays[event_key] = {
                    'event_title': event['title'],
                    'event_id': event.get('event_id'),
                    'source_of_event_to_tf_mapping': event.get('source'),
                    'assays': [],
                    'target_families': []
                }
            
            # Add assays and target family
            for assay in assays:
                if assay not in event_to_assays[event_key]['assays']:
                    event_to_assays[event_key]['assays'].append(assay)
            if tf_name not in event_to_assays[event_key]['target_families']:
                event_to_assays[event_key]['target_families'].append(tf_name)
    
    # Generate summary stats
    summary = {
        'total_events_with_assay_links': len(event_to_assays)
    }
    
    print("\n" + "="*60)
    print("EVENT TO ASSAY MAPPING SUMMARY (via Target Families)")
    print("="*60)
    print(f"Events with assay links: {summary['total_events_with_assay_links']}")

    
    return {
        'event_to_assays': event_to_assays,
        'summary': summary
    }