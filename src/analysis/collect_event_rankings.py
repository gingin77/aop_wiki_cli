"""Module for collecting and organizing event rankings from AOP-Wiki XML."""
import os
import json

from src.utilities import write_dict_to_json
from src.parsers import collect_entity_with_cache, collect_events_from_xml
from src.analysis.meta_data_helpers import calculate_event_summary_statistics


def collect_and_rank_events(
    work_date,
    cache_dir,
    output_dir,
    logger,
    force_refresh=False
):
    """
    Collect and rank events from XML, with caching support.
    
    Uses collect_entity_with_cache() for efficient event collection.
    Calculates summary statistics and saves combined output for convenience.
    
    Args:
        work_date: Date object (datetime.date)
        cache_dir: Directory for caching raw XML data (all_events_{date}.json)
        output_dir: Directory to write processed output files (event_rankings_{date}.json)
        logger: Logger instance for status messages
        force_refresh: If True, ignore cached files and collect fresh data
        
    Returns:
        tuple: (event_dict, summary_dict)
    """
    # Format date for filenames
    work_date_str = work_date.strftime('%m-%d-%Y')
    
    # Use new caching pattern to collect events from centralized cache
    # This saves to all_events_{date}.json in the cache directory
    event_dict = collect_entity_with_cache(
        entity_type='events',
        collection_function=collect_events_from_xml,
        work_date=work_date,
        output_dir=cache_dir,
        force_refresh=force_refresh,
        logger=logger
    )
    
    # Calculate summary statistics
    summary = calculate_event_summary_statistics(event_dict)
    
    # Sort events by retention score
    event_dict = dict(sorted(
        event_dict.items(),
        key=lambda x: x[1].get('integration_score', 0),
        reverse=True
    ))
    
    # Save combined output (events + summary) for convenience
    # This is separate from the basic all_events_{date}.json cache
    output_file = f'event_rankings_{work_date_str}.json'
    output_data = {
        'collection_date': work_date_str,
        'summary': summary,
        'events': event_dict
    }
    
    write_dict_to_json(output_data, output_dir, output_file)
    logger.info(f"Event rankings written to {output_file} in {output_dir}")
    
    return event_dict, summary
