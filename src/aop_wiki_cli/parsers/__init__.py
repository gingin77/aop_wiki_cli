"""
XML parsing and entity extraction from AOP-Wiki data.

This module provides functions for parsing AOP-Wiki XML exports and extracting
structured data for AOPs, Key Events (Events), and Key Event Relationships (KERs).

Main Functions:
    - collect_events_from_xml: Extract all events with completion scores and rankings
    - collect_aops_from_xml: Extract all AOPs with completion scores
    - collect_kers_from_xml: Extract all KERs with completion scores
    - collect_entity_with_cache: Generic cached entity collection with force refresh
    - collect_references_from_aops_kers_and_events: Extract reference data

Completion Scoring:
    - add_completion_score_to_events: Add completion scores to event dictionaries
    - add_completion_score_to_kers: Add completion scores to KER dictionaries
    - add_completion_score_to_aops: Add completion scores to AOP dictionaries
    - event_completion_score: Calculate score for single event
    - ker_completion_score: Calculate score for single KER
    - aop_completion_score: Calculate score for single AOP

XML Processing Helpers:
    - collect_ker_to_aop_mapping_from_xml: Build KER-to-AOP relationship mapping
    - collect_tables_from_field: Extract tabulated evidence from XML fields

Reference Parsing:
    - get_structured_references: Parse and structure reference citations

Example:
    >>> from aop_wiki_cli.parsers import collect_entity_with_cache, collect_events_from_xml
    >>> from datetime import date
    >>> 
    >>> events = collect_entity_with_cache(
    ...     'events', 
    ...     collect_events_from_xml, 
    ...     date.today(), 
    ...     outputs_dir(),  # from aop_wiki_cli.paths
    ...     False, 
    ...     logger
    ... )
"""

from aop_wiki_cli.parsers.parse_aop_wiki_xml_data import (
    collect_events_from_xml,
    collect_aops_from_xml,
    collect_kers_from_xml,
    collect_entity_with_cache,
    collect_references_from_aops_kers_and_events,
)

from aop_wiki_cli.parsers.xml_processing_helpers import (
    collect_ker_to_aop_mapping_from_xml,
    collect_tables_from_field,
)

from aop_wiki_cli.parsers.parse_references import (
    get_structured_references,
)

from aop_wiki_cli.parsers.completion_score import (
    add_completion_score_to_events,
    add_completion_score_to_kers,
    add_completion_score_to_aops,
    event_completion_score,
    ker_completion_score,
    aop_completion_score,
)

from aop_wiki_cli.parsers.aop_wiki_content_parsers import (
    strip_event_titles,
)

__all__ = [
    # Main entity collectors
    'collect_events_from_xml',
    'collect_aops_from_xml',
    'collect_kers_from_xml',
    'collect_entity_with_cache',
    'collect_references_from_aops_kers_and_events',
    
    # XML processing utilities
    'collect_ker_to_aop_mapping_from_xml',
    'collect_tables_from_field',
    
    # Reference parsing
    'get_structured_references',
    
    # Completion scoring
    'add_completion_score_to_events',
    'add_completion_score_to_kers',
    'add_completion_score_to_aops',
    'event_completion_score',
    'ker_completion_score',
    'aop_completion_score',

    # AOP-Wiki content parsing
    'strip_event_titles',
]
