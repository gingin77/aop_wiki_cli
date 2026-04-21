"""
completion_score.py
-------------------
Python script to compute completion scores for AOPs, Events, and Relationships (KERs).
"""

from src.utilities import get_dict_from_json


# ============================================================================
# Shared Helpers
# ============================================================================

def _has_content(value):
    """Check if a value has meaningful content."""
    if not value:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


# ============================================================================
# Event Completion Scoring
# ============================================================================

def _score_event_lobo_fields(event, empty_struct):
    """Score level of biological organization and related fields (organ/cell).
    
    Returns:
        tuple: (score increment, max_score increment)
    """
    lobo = event.get('level_of_biological_organization')
    if not lobo:
        empty_struct.append('lobo')
        return 0, 0
    
    score = 1
    max_increment = 0
    
    if lobo == 'Tissue':
        max_increment = 1
        organ_term = event.get('organ_term', {})
        if organ_term and organ_term.get('term'):
            score += 1
        else:
            empty_struct.append('organ')
    elif lobo in ('Cellular', 'Molecular'):
        max_increment = 1
        cell_term = event.get('cell_term', {})
        if cell_term and cell_term.get('term'):
            score += 1
        else:
            empty_struct.append('cell')
    
    return score, max_increment


def event_completion_score(event):
    """Calculate completion score for an event based on presence of key fields.
    
    Args:
        event: Dictionary representing an event
        
    Returns:
        Dictionary with 'percent', 'raw_score', 'max_score', 'empty_free_text', 'empty_structured'
    """
    free_text_fields = [
        'title', 'short_name', 'description', 'doa_free_text',
        'measurement_method', 'references',
    ]
    
    # Structured fields with nested access patterns
    structured_fields = [
        ('taxonomy_terms', event.get('taxonomy_terms')),
        ('life_stage_terms', event.get('life_stage_terms')),
        ('sex_terms', event.get('sex_terms')),
        ('sub_events', event.get('ecs'))
    ]
    
    # Initialize tracking
    score = 0
    empty_free = []
    empty_struct = []
    ao_max_increment = 0
    
    # Check free text fields
    for field in free_text_fields:
        if _has_content(event.get(field)):
            score += 1
        else:
            empty_free.append(field)

    # Score AO examples only when this event is an adverse outcome.
    # In parsed event data this AO examples field is stored as regulatory_relevance.
    if (event.get('is_ao')):
        ao_max_increment = 1
        if _has_content(event.get('regulatory_relevance')):
            score += 1
        else:
            empty_free.append('regulatory_relevance')
    
    # Score lobo and related fields (organ/cell) - has conditional max_score
    lobo_score, lobo_max_increment = _score_event_lobo_fields(event, empty_struct)
    score += lobo_score
    
    # Score structured fields
    for field_name, field_value in structured_fields:
        if _has_content(field_value):
            score += 1
        else:
            empty_struct.append(field_name)
    
    # Calculate max score (free text + lobo base + lobo conditional + structured fields)
    max_score = len(free_text_fields) + ao_max_increment + 1 + lobo_max_increment + len(structured_fields)
    percent = round(100 * score / max_score, 2) if max_score else 0
    
    return {
        'percent': percent,
        'raw_score': score,
        'max_score': max_score,
        'empty_free_text': empty_free,
        'empty_structured': empty_struct
    }

# ============================================================================
# KER Completion Scoring
# ============================================================================

def ker_completion_score(ker):
    """Calculate completion score for a KER based on presence of fields.
    
    Args:
        ker: Dictionary representing a KER
        
    Returns:
        Dictionary with 'percent', 'raw_score', 'max_score', 'empty_free_text', 'empty_structured'
    """
    # Free text fields in KER
    free_text_fields = [
        'description', 'modulating_factors', 'doa_free_text', 'uncertainties',
        'response_relationship', 'time_scale', 'known_loops',
        'evidence_collection_strategy', 'references'
    ]
    
    # Structured fields (nested dicts, lists, or complex objects)
    structured_fields = [
        'aop_ids', 'weight_of_evidence', 'empirical_support',
        'biological_plausibility', 'quantitative_understanding',
        'sex_terms', 'life_stage_terms', 'taxonomy_terms'
    ]
    
    score = 0
    empty_free = []
    empty_struct = []
    
    # Check free text fields
    for field in free_text_fields:
        if _has_content(ker.get(field)):
            score += 1
        else:
            empty_free.append(field)
    
    # Check structured fields
    for field in structured_fields:
        if _has_content(ker.get(field)):
            score += 1
        else:
            empty_struct.append(field)
    
    max_score = len(free_text_fields) + len(structured_fields)
    percent = round(100 * score / max_score, 2) if max_score else 0
    
    return {
        'percent': percent,
        'raw_score': score,
        'max_score': max_score,
        'empty_free_text': empty_free,
        'empty_structured': empty_struct
    }

def add_completion_score_to_events(events):
    for event_id, event in events.items():
        events[event_id]['completion_score'] = event_completion_score(event)
    
    return events

def add_completion_score_to_kers(kers):
    for ker_id, ker in kers.items():
        kers[ker_id]['completion_score'] = ker_completion_score(ker)
    
    return kers


# ============================================================================
# AOP Completion Scoring
# ============================================================================

def aop_completion_score(aop):
    """Calculate completion score for an AOP based on presence of key fields.
    
    Conditionally excludes development_strategy and known_modulating_factors
    from scoring for AOPs with handbook version < 2.5, but still tracks them
    in empty fields list.
    
    Args:
        aop: Dictionary representing an AOP
        
    Returns:
        Dictionary with 'percent', 'raw_score', 'max_score', 'empty_free_text', 'empty_structured'
    """
    # Check handbook version to determine which fields to score
    handbook_version = aop.get('handbook_version')
    is_new_handbook = handbook_version is not None and handbook_version >= 2.5
    
    # Core fields that should be present in every AOP
    required_free_text_fields = [
        'title', 'short_name', 'abstract', 'authors', 'background',
        'overall_assessment_description', 'doa_free_text',
        'ke_essentiality', 'woe_evidence', 'quantitative_considerations',
        'potential_applications'
    ]
    
    # Handbook 2.5+ fields that are tracked but only scored for new handbooks
    conditional_fields = ['development_strategy', 'known_modulating_factors']
    
    required_structured_fields = [
        'event_ids', 'kers', 'stressors',
        'sex_applicability', 'life_stage_applicability', 'taxonomy_applicability'
    ]
    # Max score includes conditional fields only for new handbooks
    max_score = len(required_free_text_fields) + len(required_structured_fields)
    if is_new_handbook:
        max_score += len(conditional_fields)
    
    score = 0
    empty_free = []
    empty_struct = []
    
    # Check free text fields
    for field in required_free_text_fields:
        if _has_content(aop.get(field)):
            score += 1
        else:
            empty_free.append(field)
    
    # Check conditional fields (always track, only score for new handbooks)
    for field in conditional_fields:
        if _has_content(aop.get(field)):
            if is_new_handbook:
                score += 1
            else:
                empty_free.append(field)
    
    # Check structured fields
    for field in required_structured_fields:
        if _has_content(aop.get(field)):
            score += 1
        else:
            empty_struct.append(field)
    
    percent = round(100 * score / max_score, 2) if max_score else 0
    
    return {
        'percent': percent,
        'raw_score': score,
        'max_score': max_score,
        'empty_free_text': empty_free,
        'empty_structured': empty_struct
    }

def add_completion_score_to_aops(aops):
    """Add completion scores to all AOPs in the dictionary.
    
    Args:
        aops: Dictionary of AOP data keyed by AOP ID
        
    Returns:
        Dictionary of AOPs with completion scores added
    """
    for aop_id, aop in aops.items():
        aops[aop_id]['completion_score'] = aop_completion_score(aop)
    
    return aops


# ============================================================================
# Demo/Testing
# ============================================================================

if __name__ == '__main__':
    # Example usage for testing
    events_from_json = get_dict_from_json("outputs/depression_aops/depression_events_2025-12-07.json")
    events = add_completion_score_to_events(events_from_json["key_events"])
    print(f"Scored {len(events)} events")