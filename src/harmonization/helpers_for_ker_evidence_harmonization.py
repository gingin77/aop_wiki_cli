"""Helper functions for KER evidence harmonization."""

import os
from src.utilities import write_dict_to_json, generic_cache_wrapper
from src.harmonization.harmonize_tabulated_evidence import harmonize_evidence_headers


def harmonize_kers_with_cache(kers_with_tables, work_date, output_dir, force_refresh=False, logger=None):
    """
    Harmonize KER evidence with caching support.
    
    Checks for cached harmonized KER data before performing harmonization.
    If cache exists and force_refresh is False, returns cached data.
    Otherwise harmonizes evidence headers and caches the result.
    
    Args:
        kers_with_tables: Dictionary of KERs that have tabulated evidence
        work_date: Date object for file naming
        output_dir: Directory to store cached files
        force_refresh: If True, ignore cache and harmonize fresh data
        logger: Optional logger instance for status messages
        
    Returns:
        Dictionary of harmonized KER evidence
    """
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_key = f'kers_with_harmonized_evi_tables_{work_date_str}'
    
    return generic_cache_wrapper(
        cache_key,
        output_dir,
        lambda: harmonize_evidence_headers(kers_with_tables),
        force_refresh,
        logger
    )
