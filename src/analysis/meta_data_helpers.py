
from src.utilities import get_dict_from_json
import pprint as pp

def get_average_completion_score(entities_dict):
    """
    Calculate the average completion score across a dictionary of entities.
    Works for KERs, Events, or AOPs - any entity with a completion_score field.

    Args:
        entities_dict: Dictionary of entity_id -> entity data

    Returns:
        Average completion percentage (0-100), rounded to 2 decimal places
    """
    if not entities_dict:
        return 0
    
    completion_scores = [
        entity.get('completion_score', {}).get('percent', 0)
        for entity in entities_dict.values()
    ]
    
    average = sum(completion_scores) / len(completion_scores)
    return round(average, 2)

def apply_ranking_to_events_dict(events_dict):
    """
    Applies a retention ranking score to each event in the events_dict based on percent complete,
    OECD status, license type, and match to search terms if applicable. A lower score indicates 
    lower priority for retention.
    """
    for event_id, event in events_dict.items():
        score_for_retention = 0
        max_score = 0
        percent_complete = event['completion_score']['percent']
        oecd_program = event['summary_oecd_statuses']['in_oecd_aop_program']
        oecd_endorsed = event['summary_oecd_statuses']['any_oecd_endorsed']

        license_only_open_adoption = event["summary_licenses"]["only_open_for_adoption"]
        
        # Demote events that are only associated with AOPs with Open for Adoption licenses
        max_score += 2
        if license_only_open_adoption:
            score_for_retention -= 4

        # Promote Events that have high aop_counts
        aop_count = event.get('aop_count', 0)
        score_for_retention += aop_count
        
        # Promote Events based on percent complete
        max_score += 3
        if percent_complete >= 80:
            score_for_retention += 3
        elif percent_complete >= 50:
            score_for_retention += 2
        elif percent_complete >= 25:
            score_for_retention += 1

        # Promote Events based on AOP being in OECD program and being OECD endorsed
        max_score += 3
        if oecd_program and not oecd_endorsed:
            score_for_retention += 2
        elif oecd_program and oecd_endorsed:
            score_for_retention += 3
        
        # Promote Events that have text in the methods section
        method = event.get('measurement_method', None)
        max_score += 1
        has_method = method is not None and method.strip() != ""
        if has_method:
            score_for_retention += 1
        
        # Promote Events based on how well they meet any search criteria
        search_source = event.get('source', None)
        if search_source is not None:
            max_score += 2
            if search_source == 'title_search':
                score_for_retention += 2
            elif search_source == 'full_text_search':
                score_for_retention += 1

        events_dict[event_id]['integration_score'] = score_for_retention
        events_dict[event_id]['max_i_score_sans_aop_count'] = max_score
        events_dict[event_id]['has_method'] = has_method

    return events_dict

def filter_kers_by_tables(all_kers, has_tables=True):
    """
    Filter KERs by presence or absence of tabulated evidence.
    
    Args:
        all_kers: Dictionary of KER data
        has_tables: If True, return KERs with tables; if False, return KERs without tables
        
    Returns:
        Filtered dictionary of KERs
    """
    return {
        ker_id: ker_data 
        for ker_id, ker_data in all_kers.items() 
        if ker_data.get('has_any_tables', False) == has_tables
    }

def calculate_event_summary_statistics(event_dict):
    """Calculate summary statistics from a dictionary of events.
    
    Args:
        event_dict: Dictionary of events with retention scores and metadata
        
    Returns:
        Dictionary with summary statistics
    """
    total_events = len(event_dict)
    
    if total_events == 0:
        return {
            'total_events': 0,
            'average_completion_percent': 0,
            'average_integration_score': 0,
            'events_with_methods': 0,
            'events_only_open_for_adoption': 0,
            'events_in_oecd_program': 0,
            'events_oecd_endorsed': 0,
            'events_non_oecd_non_adoption': 0
        }
    
    # Calculate averages
    avg_completion = round(
        sum(e.get('completion_score', {}).get('percent', 0) for e in event_dict.values()) / total_events, 
        2
    )
    avg_retention = round(
        sum(e.get('integration_score', 0) for e in event_dict.values()) / total_events, 
        2
    )
    
    # Count specific categories
    events_with_methods = sum(
        1 for e in event_dict.values() 
        if e.get('has_method', False)
    )
    
    only_open_for_adoption = sum(
        1 for e in event_dict.values() 
        if e.get('summary_licenses', {}).get('only_open_for_adoption', False)
    )
    
    oecd_program_events = sum(
        1 for e in event_dict.values() 
        if e.get('summary_oecd_statuses', {}).get('in_oecd_aop_program', False)
    )
    
    oecd_endorsed_events = sum(
        1 for e in event_dict.values() 
        if e.get('summary_oecd_statuses', {}).get('any_oecd_endorsed', False)
    )
    
    # Events NOT open for adoption AND NOT in OECD program AND NOT endorsed
    non_oecd_non_adoption_count = sum(
        1 for e in event_dict.values()
        if not e.get('summary_licenses', {}).get('only_open_for_adoption', False)
        and not e.get('summary_oecd_statuses', {}).get('in_oecd_aop_program', False)
        and not e.get('summary_oecd_statuses', {}).get('any_oecd_endorsed', False)
    )
    
    return {
        'total_events': total_events,
        'average_completion_percent': avg_completion,
        'average_integration_score': avg_retention,
        'events_with_methods': events_with_methods,
        'events_only_open_for_adoption': only_open_for_adoption,
        'events_in_oecd_program': oecd_program_events,
        'events_oecd_endorsed': oecd_endorsed_events,
        'events_non_oecd_non_adoption': non_oecd_non_adoption_count
    }

if __name__ == "__main__":
    input_event_file = "outputs/depression_aops/depression_events_2025-12-16.json"
    events_dict = get_dict_from_json(input_event_file)["key_events"]
    events_dict = apply_ranking_to_events_dict(events_dict)
    
    ranked_events = sorted(events_dict.items(), key=lambda x: x[1]['percent_integration_score'], reverse=True)
    for event_id, event in ranked_events:
        print(f"{event_id}: {event.get('title', 'N/A')}, %Score: {event['percent_integration_score']}, Has Method: {event['has_method']}, AOP Count: {event.get('aop_count', 0)}, %Complete: {event['completion_score']['percent']}")

    # Example output line:
    # 1532: Decrease, Cardiac contractility , %Score: 90.0, Has Method: False, AOP Count: 6, %Complete: 27.27