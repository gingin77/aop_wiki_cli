"""
Analysis Module
===============

Post-extraction analytics and statistical operations for AOP-Wiki data.

This module provides:
- Event ranking and filtering logic
- Statistical summaries of event collections
- Metadata helpers for averaging and filtering
- Seizure AOP content analysis and harmonization
- KE description fuzzy matching to harmonized KE titles

Public API
----------

Ranking & Filtering:
    apply_ranking_to_events_dict: Apply integration rankings to events
    filter_kers_by_tables: Filter KERs by presence of tabulated evidence

Event Statistics:
    calculate_event_summary_statistics: Generate summary stats for event collections
    collect_and_rank_events: Collect events from XML with rankings and stats

Seizure AOP Analysis:
    organize_and_enrich_harmonized_events: Analyze and enrich seizure AOP data with AOP-Wiki matches
    
KE Description Mapping:
    map_ke_descriptions_to_harmonized_kes: Fuzzy match KE descriptions to harmonized titles
    generate_match_metrics: Generate statistics on matching results
    map_assays_to_events_via_target_families: Link assays to events through target family associations

MIE/AO Pairing:
    build_mie_ao_pairs: Pair each AOP's MIEs with its AOs, one row per combination
    summarize_mie_ao_pairs: Summary counts over a set of pair rows
    filter_kers_by_aop_ids: Select the KERs belonging to a set of AOPs
    render_mie_ao_markdown_table: Render pair rows as a markdown table

Metadata Helpers:
    get_average_completion_score: Calculate average completion across entities
    
Note: 
    - calculate_event_summary_statistics was moved from event_statistics.py to meta_data_helpers.py
    - Completion scoring functions moved to src.parsers.completion_score (tightly coupled to XML parsing)
"""

# Ranking and filtering
from aop_wiki_cli.analysis.meta_data_helpers import (
    apply_ranking_to_events_dict,
    filter_kers_by_tables,
    get_average_completion_score,
    calculate_event_summary_statistics,
)

# Seizure AOP content analysis
from aop_wiki_cli.analysis.analyze_seizure_aop_content import (
    organize_and_enrich_harmonized_events
)

# KE description mapping
from aop_wiki_cli.analysis.map_ke_descriptions_to_harmonized import (
    map_ke_descriptions_to_harmonized_kes,
    generate_match_metrics,
    enrich_target_families,
    map_assays_to_events_via_target_families,
)

# MIE/AO pairing
from aop_wiki_cli.analysis.pair_mies_and_aos import (
    build_mie_ao_pairs,
    summarize_mie_ao_pairs,
    filter_kers_by_aop_ids,
    render_mie_ao_markdown_table,
    MIE_AO_PAIR_COLUMNS,
)

# Note: collect_and_rank_events not exposed to avoid circular import
# Import directly: from aop_wiki_cli.analysis.collect_event_rankings import collect_and_rank_events

__all__ = [
    # Ranking & filtering
    'apply_ranking_to_events_dict',
    'filter_kers_by_tables',
    'get_average_completion_score',
    # Event statistics
    'calculate_event_summary_statistics',
    # Seizure AOP content analysis
    'organize_and_enrich_harmonized_events',
    # KE description mapping
    'map_ke_descriptions_to_harmonized_kes',
    'generate_match_metrics',
    'enrich_target_families',
    'map_assays_to_events_via_target_families',
    # MIE/AO pairing
    'build_mie_ao_pairs',
    'summarize_mie_ao_pairs',
    'filter_kers_by_aop_ids',
    'render_mie_ao_markdown_table',
    'MIE_AO_PAIR_COLUMNS',
]
