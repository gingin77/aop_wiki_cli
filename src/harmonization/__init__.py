"""
Harmonization Module
====================

KER evidence table harmonization and standardization.

This module provides functions for:
- Harmonizing column headers in KER evidence tables
- Standardizing terminology across evidence tables
- Caching harmonized data for reuse
- Supporting evidence integration workflows

Public API
----------

Evidence Harmonization:
    harmonize_evidence_headers: Harmonize column headers in KER evidence tables
    harmonize_kers_with_cache: Harmonize KER evidence with caching support

Column Mapping:
    COLUMN_HARMONIZER: Standard mapping of evidence table column headers
"""

# Core harmonization functions
from src.harmonization.harmonize_tabulated_evidence import (
    harmonize_evidence_headers,
    COLUMN_HARMONIZER,
)

# Caching and workflow helpers
from src.harmonization.helpers_for_ker_evidence_harmonization import (
    harmonize_kers_with_cache,
)

__all__ = [
    # Harmonization functions
    'harmonize_evidence_headers',
    'harmonize_kers_with_cache',
    # Column mapping
    'COLUMN_HARMONIZER',
]
