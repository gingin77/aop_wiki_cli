"""
Collection Module
=================

Data fetching and initial collection from AOP-Wiki sources.

This module provides functions for:
- Downloading and parsing AOP-Wiki XML data
- Filtering and organizing entities (AOPs, Events, KERs)
- Entity collection workflows

Public API
----------

XML Data Collection:
    collect_xml_data: Download and parse AOP-Wiki XML data

Entity Collection Workflows:
    capture_related_entities_for_event_ids: Collect AOPs and KERs related to specific events
    collect_filtered_events: Filter events by title/functional term
    collect_aops_for_input_event_ids: Get AOPs containing specific events
"""

# XML data collection (no circular import)
from src.collection.get_aop_wiki_xml_data import collect_xml_data

# Entity collection workflows - delayed import to avoid circular dependency
# Import these directly from the module when needed:
# from src.collection.collect_aops_and_kers_from_events import ...

__all__ = [
    # XML collection
    'collect_xml_data',
    # Entity workflows - import directly from submodule to avoid circular imports
    # 'capture_related_entities_for_event_ids',
    # 'collect_filtered_events',
    # 'collect_aops_for_input_event_ids',
]
