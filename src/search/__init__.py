"""
Search Module

Provides text and reference searching functionality for AOP-Wiki entities.

Public API:
    - search_entity_data: Main entity text search function
    - find_kers_containing_events: KERs having a given key event as an endpoint
    - screen_aop_wiki_fields_for_input_terms: Search specific fields with term parameters
    - search_citations_by_field: Search references by single field
    - search_citations_cross_field: Search references across multiple fields
    - search_citations_by_combination: Search references with AND/OR logic
    
Note: seek_search_phrase_in_field_text and add_search_result are internal functions.
For testing, import directly from src.search.search_text_by_field to avoid circular imports.
"""

from src.search.search_text_by_field import (
    search_entity_data,
    screen_aop_wiki_fields_for_input_terms,
)

from src.search.result_processors import (
    serialize_search_results,
    filter_by_co_occurrence,
    sort_by_priority_field,
)

from src.search.search_references import (
    search_citations_by_field,
    search_citations_cross_field,
    search_citations_by_combination,
)

from src.search.event_first_search import (
    search_events_to_aops,
    find_events_by_title_terms,
    find_aops_containing_events,
    find_kers_containing_events,
)

__all__ = [
    'search_entity_data',
    'screen_aop_wiki_fields_for_input_terms',
    'search_citations_by_field',
    'search_citations_cross_field',
    'search_citations_by_combination',
    'search_events_to_aops',
    'find_events_by_title_terms',
    'find_aops_containing_events',
    'find_kers_containing_events',
]
