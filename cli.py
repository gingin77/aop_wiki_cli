"""CLI interface for AOP-Wiki CLI using Typer."""
import typer
import os
import logging
import importlib
import json
import pprint as pp
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.utilities import set_up_logger, write_dict_to_json, get_dated_cache_dir
from src.analysis import (
    get_average_completion_score,
    filter_kers_by_tables,
    map_ke_descriptions_to_harmonized_kes,
    organize_and_enrich_harmonized_events,
    enrich_target_families,
    map_assays_to_events_via_target_families,
)
from src.analysis.manual_match_review import review_matches, calculate_review_summary
from src.analysis.collect_event_rankings import collect_and_rank_events
from src.data_export import (
    write_csv,
    write_concordance_csv,
    export_seizure_aop_results,
    write_summary_stats_csv,
    EVENT_FIELDS_MIN,
    prepare_concordance_results_for_export,
    export_search_results_to_json,
    write_search_results_csv,
    write_combined_search_events_csv,
    generate_search_results_filename,
    initiate_workbook_creation_for_harmonized_kers,
)
from src.parsers import (
    collect_aops_from_xml,
    collect_events_from_xml,
    collect_kers_from_xml,
    collect_entity_with_cache,
)
from src.parsers.parse_behl_seizure_aop_workbook import parse_seizure_aop_workbook
from src.collection.collect_associated_aop_wiki_entities import collect_events_from_matched_aops
from src.search import (
    search_entity_data,
    serialize_search_results,
    filter_by_co_occurrence,
    sort_by_priority_field,
    search_events_to_aops,
    find_events_by_title_terms,
    find_kers_containing_events,
)

from configs.harmonize_ker_evidence import (
    AOPS_SELECTED_FOR_HARMONIZED_KERS_WORKBOOKS, CONCORDANCE_SEARCH_PARAMS
)
from src.harmonization import harmonize_kers_with_cache

app = typer.Typer(pretty_exceptions_enable=False)

# Shared logger for all CLI commands
logger = set_up_logger('aop-wiki-cli', level=logging.INFO)

# Today's date
today = date.today()

# Output directories
CACHE_DIR_ROOT = 'outputs/cache/'
EVENT_RANKINGS_OUTPUT_DIR = 'outputs/event_rankings'
KER_HARMONIZATION_OUTPUT_DIR = 'outputs/ker_evidence'
KER_LOOKUP_OUTPUT_DIR = 'outputs/ker_lookups'


@app.command()
def collect_event_integration_rankings(
    cache_date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Date of cached data to use (YYYY-MM-DD). Defaults to today."
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-f",
        help="Force fresh data collection, ignoring cached files"
    )
):
    """Collect all events from AOP-Wiki and calculate integration ranking scores.
    
    This command fetches fresh XML data, collects all events with AOP associations,
    calculates completion scores, applies integration ranking logic, and exports results.
    Supports caching - reuses existing data files for the same date unless --force-refresh is used.
    """
    # Setup: work_date (as date object), output_dir, and formatted date string
    work_date = datetime.strptime(cache_date, '%m-%d-%Y').date() if cache_date else today
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)
    output_dir = EVENT_RANKINGS_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    # Collect and rank events (handles caching internally)
    event_dict, summary = collect_and_rank_events(work_date, cache_dir, output_dir, logger, force_refresh)
    
    # Display summary to console
    _print_event_summary(summary)
    
    # Write summary and rankings CSVs
    summary_csv = Path(output_dir) / f"event_rankings_{work_date_str}_summary.csv"
    write_summary_stats_csv(summary, summary_csv)
    
    rankings_csv = Path(output_dir) / f"event_rankings_{work_date_str}_rankings.csv"
    write_csv(event_dict, EVENT_FIELDS_MIN, rankings_csv)
    
    typer.echo(f"\n✓ Outputs written:")
    typer.echo(f"  - {output_dir}/event_rankings_{work_date_str}.json")
    typer.echo(f"  - {summary_csv}")
    typer.echo(f"  - {rankings_csv}")


@app.command()
def collect_ker_analytics(
    cache_date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Date of cached data to use (MM-DD-YYYY). Defaults to today."
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force fresh data collection, ignoring cached files"
    )
):
    """Collect KER data and basic analytics from AOP-Wiki XML exports.
    
    This is a simpler analysis focused on KER metadata, completion scores,
    and basic statistics. Use this before diving into harmonization.
    
    Prints its statistics and writes nothing; the collected KERs are still
    cached under outputs/cache/<date>/ for later KER commands to reuse.
    """
    # Setup
    work_date = datetime.strptime(cache_date, '%m-%d-%Y').date() if cache_date else today
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)
    
    # Collect all KERs with automatic caching from centralized cache
    all_kers = collect_entity_with_cache('kers', collect_kers_from_xml, work_date, cache_dir, force_refresh, logger)
    
    # Segregate KERs with and without tables using helper
    kers_with_tables = filter_kers_by_tables(all_kers, has_tables=True)
    kers_without_tables = filter_kers_by_tables(all_kers, has_tables=False)
    
    # Calculate statistics using helper functions
    stats = {
        'collection_date': work_date_str,
        'total_kers': len(all_kers),
        'kers_with_tables': len(kers_with_tables),
        'kers_without_tables': len(kers_without_tables),
        'average_completion_score': get_average_completion_score(all_kers),
        'average_completion_score_kers_with_tables': get_average_completion_score(kers_with_tables),
        'average_completion_score_kers_without_tables': get_average_completion_score(kers_without_tables)
    }
    
    _print_ker_statistics(stats)

@app.command()
def find_kers_for_events(
    ke_ids: Optional[str] = typer.Option(
        None,
        "--ke-ids",
        help="Comma-separated key event IDs, e.g. 1346,55"
    ),
    ke_terms: Optional[str] = typer.Option(
        None,
        "--ke-terms",
        help="Comma-separated terms matched against key event titles, e.g. 'oxidative stress,cell death'"
    ),
    limit: int = typer.Option(
        25,
        "--limit",
        "-l",
        help="Maximum number of KERs to print; all matches are still written to JSON"
    ),
    cache_date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Date of cached data to use (MM-DD-YYYY). Defaults to today."
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force fresh data collection, ignoring cached files"
    )
):
    """Find the KERs that have a given key event as an upstream or downstream endpoint.

    Takes key events either directly by ID (--ke-ids) or by searching KE titles
    (--ke-terms); exactly one of the two is required. Each matched KER reports
    which side the key event sits on, so the results separate what a KE leads to
    from what leads to it.

    Note that KER collection parses the full XML the first time it runs for a
    given date, which is slow; later runs for that date read the cache.
    """
    if bool(ke_ids) == bool(ke_terms):
        typer.echo("❌ Provide exactly one of --ke-ids or --ke-terms")
        raise typer.Exit(code=1)

    # Setup
    work_date = datetime.strptime(cache_date, '%m-%d-%Y').date() if cache_date else today
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)
    output_dir = f'{KER_LOOKUP_OUTPUT_DIR}/{work_date_str}'

    # Resolve the key events to search for. Term matching reuses the same
    # title search that drives the event_to_aop search mode.
    if ke_terms:
        title_terms = [term.strip() for term in ke_terms.split(',') if term.strip()]
        all_events = collect_entity_with_cache(
            'events', collect_events_from_xml, work_date, cache_dir, force_refresh, logger
        )
        matched_events = find_events_by_title_terms(all_events, title_terms)
        # Coerce to str: event IDs are only summarized and joined for display
        # here, so this command must not depend on the key type of whatever
        # events_dict it was handed
        event_ids = [str(event_id) for event_id in matched_events]
    else:
        title_terms = []
        event_ids = [ke_id.strip() for ke_id in ke_ids.split(',') if ke_id.strip()]
        matched_events = {}

    if not event_ids:
        typer.echo(f"❌ No key events matched terms: {', '.join(title_terms)}")
        raise typer.Exit(code=1)

    # Collect all KERs with automatic caching from centralized cache
    all_kers = collect_entity_with_cache(
        'kers', collect_kers_from_xml, work_date, cache_dir, force_refresh, logger
    )

    matched_kers = find_kers_containing_events(all_kers, event_ids)

    summary = {
        'collection_date': work_date_str,
        'ke_title_terms': title_terms,
        'key_event_ids': event_ids,
        'total_kers_searched': len(all_kers),
        'total_kers_matched': len(matched_kers),
        'kers_by_key_event': _count_kers_by_key_event(matched_kers),
    }

    _print_ker_lookup_summary(summary, matched_kers, limit)

    output_data = {
        'summary': summary,
        'matched_events': matched_events,
        'matched_kers': matched_kers,
    }
    write_dict_to_json(output_data, output_dir, f'ker_lookup_{work_date_str}.json')

@app.command()
def search_kers_for_concordance_text(
    cache_date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Date of cached data to use (MM-DD-YYYY). Defaults to today."
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-f",
        help="Force fresh data collection, ignoring cached files"
    )
):
    """Search for concordance evidence in KER data.
    
    This command loads cached KER data and searches for concordance evidence.
    Run 'harmonize-ker-evidence' first to generate the cache, or use --force-refresh.
    """
    # Setup
    work_date = datetime.strptime(cache_date, '%m-%d-%Y').date() if cache_date else today
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)
    output_dir = KER_HARMONIZATION_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    # Collect KER data with automatic caching from centralized cache
    all_kers = collect_entity_with_cache('kers', collect_kers_from_xml, work_date, cache_dir, force_refresh, logger)
    
    # Search for concordance evidence
    logger.info("Searching for concordance terms in KER evidence fields...")
    
    # Prepare search params from config
    search_params = {
        "fields_to_search": list(CONCORDANCE_SEARCH_PARAMS["content_to_drop_by_field"].keys()),
        "terms": CONCORDANCE_SEARCH_PARAMS["terms_to_search"]
    }
    
    summary, kers_describing_concordance = search_entity_data(
        all_kers,
        search_params,
        CONCORDANCE_SEARCH_PARAMS["content_to_drop_by_field"]
    )
    
    # Prepare results for export (enrich + serialize)
    prepare_concordance_results_for_export(kers_describing_concordance, all_kers)
    
    # Display search summary
    _print_search_summary(summary, entity_type="KERs", search_type="concordance")
    
    # Write outputs
    json_filename = f'kers_with_concordance_mentioned_{work_date_str}.json'
    csv_path = os.path.join(output_dir, f'kers_with_concordance_mentioned_{work_date_str}.csv')
    
    write_dict_to_json(kers_describing_concordance, output_dir, json_filename)
    write_concordance_csv(kers_describing_concordance, csv_path)


@app.command()
def harmonize_ker_evidence(
    cache_date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Date of cached data to use (MM-DD-YYYY). Defaults to today."
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-f",
        help="Force fresh data collection, ignoring cached files"
    )
):
    """Harmonize KER evidence table data from AOP-Wiki XML exports.
    
    This command collects KER evidence, harmonizes it, and creates Excel workbooks.
    The all_kers data is automatically cached for use by search-concordance-evidence.
    """
    # Setup: work_date (as date object), output_dir, and formatted date string
    work_date = datetime.strptime(cache_date, '%m-%d-%Y').date() if cache_date else today
    output_dir = KER_HARMONIZATION_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)

    # Collect all KERs with automatic caching from centralized cache
    all_kers = collect_entity_with_cache('kers', collect_kers_from_xml, work_date, cache_dir, force_refresh, logger)
    kers_with_tables = filter_kers_by_tables(all_kers, has_tables=True)
    
    # Harmonize evidence headers with caching
    harmonized_kers = harmonize_kers_with_cache(kers_with_tables, work_date, output_dir, force_refresh, logger)
    
    # Create Excel workbooks
    initiate_workbook_creation_for_harmonized_kers(
        harmonized_kers, work_date, output_dir, 
        AOPS_SELECTED_FOR_HARMONIZED_KERS_WORKBOOKS, logger, cache_dir
    )

    typer.echo(f"✓ Harmonization complete. Outputs in {output_dir}")


@app.command()
def search_with_config(
    config: str = typer.Argument(
        ...,
        help="Config file name from configs/ directory (e.g., 'lung_and_immune_aops', 'regulatory_relevance', 'methods_nams')"
    ),
    cache_date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Date of cached data to use (MM-DD-YYYY). Defaults to today."
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-f",
        help="Force fresh data collection, ignoring cached files"
    ),
    co_occurrence_only: bool = typer.Option(
        False,
        "--co-occurrence-only",
        "-c",
        help="Return only entities with co-occurrence matches (filters out entities with only individual term matches)"
    )
):
    """Search AOP-Wiki entities using parameters from a config file.
    
    Available configs:
    - lung_and_immune_aops: Search AOPs for lung/immune co-occurrences
    - regulatory_relevance: Search events for regulatory terms
    - methods_nams: Search events for NAMs measurement methods
    
    Example:
        uv run python cli.py search-with-config lung_and_immune_aops
        uv run python cli.py search-with-config lung_and_immune_aops --co-occurrence-only
    """
    # Load the config module dynamically
    try:
        config_module = importlib.import_module(f'configs.{config}')
        search_params = config_module.SEARCH_PARAMS
        output_config = config_module.OUTPUT_CONFIG
    except (ImportError, AttributeError) as e:
        typer.echo(f"❌ Error loading config '{config}': {e}")
        typer.echo("Available configs: lung_and_immune_aops, regulatory_relevance, methods_nams, fibrosis_aops")
        raise typer.Exit(code=1)
    
    # Setup
    work_date = datetime.strptime(cache_date, '%m-%d-%Y').date() if cache_date else today
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)
    
    # Check for event_to_aop search mode (iterative search)
    search_mode = search_params.get("search_mode")
    if search_mode == "event_to_aop":
        _run_event_to_aop_search(config, search_params, output_config, work_date, work_date_str, cache_dir, force_refresh)
        return

    # Check for entities_and_fields mode (multi-entity search with cross-comparison)
    if "entities_and_fields" in search_params:
        _run_entities_and_fields_search(config, search_params, output_config, work_date, work_date_str, cache_dir, force_refresh)
        return

    entity_types = search_params.get("entity", ["events"])
    
    # Map entity types to collection functions
    collection_functions = {
        "events": collect_events_from_xml,
        "kers": collect_kers_from_xml,
        "aops": collect_aops_from_xml
    }
    
    for entity_type in entity_types:
        if entity_type not in collection_functions:
            typer.echo(f"❌ Unknown entity type: {entity_type}")
            raise typer.Exit(code=1)
    
    # Create output directory
    output_dir = output_config["directory"]
    os.makedirs(output_dir, exist_ok=True)
    
    # Collect entity data with automatic caching from centralized cache
    logger.info(f"Collecting {entity_type} data...")
    entities = collect_entity_with_cache(
        entity_type, 
        collection_functions[entity_type], 
        work_date, 
        cache_dir, 
        force_refresh, 
        logger
    )
    
    # Run search
    logger.info(f"Searching {entity_type} with config '{config}'...")
    summary, results = search_entity_data(entities, search_params)

    # Serialize for export (JSON/CSV)
    results = serialize_search_results(results)
    
    # Filter and sort if co-occurrence-only flag is set
    priority_count = 0
    if co_occurrence_only:
        results = filter_by_co_occurrence(results, entity_type, logger)
        
    priority_field = search_params.get("priority_field")
    if priority_field:
        results, priority_count = sort_by_priority_field(results, priority_field, entity_type, logger)
    
    # Display search summary
    _print_search_summary(summary, entity_type=entity_type, search_type=config.replace('_', ' ').upper())
    
    # Display filtering and co-occurrence details
    if co_occurrence_only:
        typer.echo(f"\n⚠️  Filtered to co-occurrence matches only: {len(results)}/{summary['total_entities_with_matches']} {entity_type}")
        
        if priority_count > 0:
            typer.echo(f"   ⭐ {priority_count} have co-occurrences in priority field (listed first)")
    
    # Display co-occurrence summary if present
    if "co_occurrence_matches" in summary and summary["co_occurrence_matches"]:
        typer.echo(f"\nCo-occurrence matches:")
        for pair, counts in summary["co_occurrence_matches"].items():
            if counts["unique_entities"] > 0:
                typer.echo(f"  - {pair}: {counts['unique_entities']} unique {entity_type} ({counts['total_instances']} total instances)")
    
    # Generate filenames with appropriate suffixes
    csv_filename = generate_search_results_filename(
        config, work_date_str, co_occurrence_only, search_params, extension="csv"
    )
    json_filename = generate_search_results_filename(
        config, work_date_str, co_occurrence_only, search_params, extension="json"
    )
    
    # Export results
    json_path = os.path.join(output_dir, json_filename)
    csv_path = os.path.join(output_dir, csv_filename)
    
    export_search_results_to_json(results, summary, json_path, config, work_date_str, co_occurrence_only)
    write_search_results_csv(results, csv_path, entity_type, entities)
    
    typer.echo(f"✓ Search complete. Results in {output_dir}")


@app.command()
def collect_harmonized_seizure_aops(
    cache_date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="Date of cached data to use (MM-DD-YYYY). Defaults to today."
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-f",
        help="Force fresh data collection from the AOP-Wiki XML, ignoring cached files"
    ),
    skip_curated: bool = typer.Option(
        False,
        "--skip-curated",
        "-s",
        help="Skip curated inputs and regenerate via fuzzy matching + review"
    )
):
    """Collect, harmonize, and analyze seizure AOP data with human-in-the-loop review.
    
    This command orchestrates a multi-stage workflow:
    
    1. Parses the seizure AOP workbook (inputs/seizure_aops/behl_seizure_supp_data.xlsx)
    2. Maps KE descriptions to harmonized KE titles via fuzzy matching
    3. Enriches target families with AOP-Wiki event data
    4. Compares extracted content against AOP-Wiki XML data for validation
    
    Human Review Stages:
        - Stage 1: Review fuzzy matches between KE descriptions and harmonized KE titles
        - Stage 2: Review fuzzy matches between target family labels and event titles
        
        For each match below the confidence threshold (0.9), you'll be prompted to:
        - Accept (y): Confirm the match is correct
        - Reject (n): Mark as incorrect, optionally suggest a better match
        - Quit (q): Save progress and exit the review
    
    Caching:
        The workflow checks for curated input files in outputs_for_vc/. If present,
        interactive review is skipped. These must be manually placed there after review if updated.
        Use --skip-curated to bypass curated inputs and run interactive review.
    
    Outputs:
        Results are written to outputs/seizure_aops/{date}/ including:
        - harmonized_events_{date}.csv: Harmonized key events
        - assays_{date}.csv: Assay data mapped to events
        - seizure_aop_events_{date}.xlsx: Combined Excel workbook
        - Various JSON files with mappings and validation results
    
    Examples:
        uv run python cli.py collect-harmonized-seizure-aops
        uv run python cli.py collect-harmonized-seizure-aops --date 03-12-2026
        uv run python cli.py collect-harmonized-seizure-aops --skip-curated --force-refresh
    
    # TODO: Add option to pass a file path for the curated inputs.
    """
    # Setup
    work_date = datetime.strptime(cache_date, '%m-%d-%Y').date() if cache_date else today
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)
    output_dir = 'outputs/seizure_aops'
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info("Parsing seizure AOP workbook...")
    
    # Parse the workbook and collect all seizure AOP content into a structured dictionary
    workbook_path = 'inputs/seizure_aops/behl_seizure_supp_data.xlsx'

    # `parse_seizure_aop_workbook()` returns a dict of many properties, organized into differnt formats for different purposes.
    seizure_content = parse_seizure_aop_workbook(workbook_path)
    
    """
    Behl mapped assays to KE descriptions, rather than exact KE titles. Therefore, use fuzzy matching to find best 
    harmonized KE title match for each KE description.
    """

    # Extract specific properties for further processing, and then pass to map_ke_descriptions_to_harmonized_kes()
    # First, check if reviewed file already exists from a previous run, and if so, use that as input to preserve human-reviewed matches
    path_to_reviewed_matches = "outputs_for_vc/reviewed_ke_description_to_harmonized_ke_mapping.json"
    if not skip_curated and os.path.exists(path_to_reviewed_matches):
        print("Using reviewed input for KE description to harmonized KE mapping...")
        with open(path_to_reviewed_matches, 'r') as f:
            reviewed_data = json.load(f)
            # Extract results list from wrapper structure {"summary": {...}, "results": [...]}
            reviewed_enhanced_ke_description_mapping = reviewed_data.get('results', reviewed_data)
    else:
        ke_description_mapping = seizure_content.get('mappings_generated', {}).get('data', {}).get('ke_description_mappings_from_assays_df', {})
        harmonized_kes_list = seizure_content.get('ready_for_emod', {}).get('data', {}).get('harmonized_kes', [])
        enhanced_ke_description_mapping = map_ke_descriptions_to_harmonized_kes(
            ke_description_mapping,
            harmonized_kes_list,
            threshold=0.6
        )
        # Human-in-Loop Part 1: Review fuzzy matches between KE descriptions and Harmonized KE titles
        print("\n" + "="*120)
        print("Manually review fuzzy matches between Event descriptions and Event titles...")
        print("="*120)
        reviewed_enhanced_ke_description_mapping = review_matches(enhanced_ke_description_mapping, score_threshold=0.9)

    """
    The Behl content should be compared to content the AOP-Wiki to enrich the content and for quality control.
    """
    # Collect cached AOP and event data for comparison from centralized cache
    all_aops = collect_entity_with_cache('aops', collect_aops_from_xml, work_date, cache_dir, force_refresh, logger)
    all_events = collect_entity_with_cache('events', collect_events_from_xml, work_date, cache_dir, force_refresh, logger)

    # Add the enhanced mapping back to seizure_content for export & print match metrics to terminal
    seizure_content['enriched']['data']['ke_description_to_harmonized_ke_mapping'] = reviewed_enhanced_ke_description_mapping
    target_families_to_h_events_and_assays = seizure_content.get('to_analyze', {}).get("data", {}).get('target_families_to_h_events_and_assays', {})
    
    path_to_curated_events_to_target_families = "outputs_for_vc/curated_event-target_family_mappings.json"
    if not skip_curated and os.path.exists(path_to_curated_events_to_target_families):
        print("Using curated input for event-to-target-family mappings...")
        with open(path_to_curated_events_to_target_families, 'r') as f:
            enriched_target_families_reviewed = json.load(f)
    else:
        tfs_to_events = enrich_target_families(
            target_families_to_h_events_and_assays,
            all_events
        )

        # Human Review Part 2: Review fuzzy matches between Target Family labels and Event titles
        print("\n" + "="*120)
        print("Manually review fuzzy matches between Target Family labels and Event titles...")
        print("="*120)

        enriched_target_families_reviewed = review_matches(tfs_to_events, score_threshold=0.9)
        # Rename fields for clarity: input_term -> target_family, matched_term -> event, suggested_match -> suggested_event
        enriched_target_families_reviewed = [
            {
                'target_family': item.pop('input_term', None),
                'event': item.pop('matched_term', None),
                'suggested_event': item.pop('suggested_match', None),
                **item
            }
            for item in enriched_target_families_reviewed
        ]
    
    # Map assays to events through target families
    assay_event_mappings = map_assays_to_events_via_target_families(
        enriched_target_families_reviewed,
        target_families_to_h_events_and_assays
    )

    seizure_content['enriched']['data']['biological_target_families_enriched'] = enriched_target_families_reviewed
    seizure_content['enriched']['data']['event_to_assays_via_target_families'] = assay_event_mappings['event_to_assays']
    seizure_content['enriched']['data']['event_to_assays_summary'] = assay_event_mappings['summary']
    

    seizure_aop_curations = seizure_content['to_analyze']['data']['harmonization_dict']
    _, enriched_seizure_aop_events, harmonized_summary = organize_and_enrich_harmonized_events(
        seizure_aop_curations, all_aops, all_events
    )
    seizure_content['enriched']['data']['enriched_seizure_aop_events'] = enriched_seizure_aop_events
    seizure_content['enriched']['data']['harmonized_summary'] = harmonized_summary
    
    # TODO: compare_assay_metadata_to_comptox_data - will pass seizure_content['to_analyze']['assays']

    print("\n" + "="*60)
    print("Seizure analysis exports being generated...")
    print("="*60)

    # Export all results - pass full seizure_content instead of just harmonization_dict
    export_seizure_aop_results(
        seizure_content,
        output_dir,
        work_date_str
    )


@app.command()
def manually_review_matches(
    input_file: Path = typer.Argument(
        ...,
        help="Path to JSON file with match results to review"
    ),
    score_threshold: float = typer.Option(
        0.0,
        "--threshold",
        "-t",
        help="Only review matches below this score (0.0-1.0). Default 0.0 reviews all."
    )
):
    """Interactively review and accept/reject term matches from fuzzy matching or other approach.
    First iteration of function was developed for evaluating fuzzy matches.

    Developed to serve 2 main use cases in the seizure AOP project. To test this function, run 
    with:
    
    uv run python cli.py manually-review-matches outputs/seizure_aops/{date}/mapping_ke_description_to_harmonized_ke_{date}.json --threshold 0.9

    Input JSON structure (dict or list):
        Dict: { "<key>": { "input_term": ..., "matched_term": ..., "match_score": ... } }
        List: [ { "input_term": ..., "matched_term": ..., "match_score": ... }, ... ]
    
    Output adds 'human_verified': true/false to each reviewed entry.
    """
    # Load input JSON
    with open(input_file, 'r') as f:
        input_json = json.load(f)

    # Convert list to dict if needed (review_matches expects dict)
    if isinstance(input_json, list):
        input_json = {item.get('input_term', str(i)): item for i, item in enumerate(input_json)}

    # Review matches using modular function
    results = review_matches(input_json, score_threshold=score_threshold)
    summary_metrics = calculate_review_summary(results)
    
    typer.echo(f"Summary metrics: {summary_metrics}")

    # Wrap results with summary for export
    output_data = {
        "summary": summary_metrics,
        "results": results
    }

    # Save results to output file
    output_file = input_file.parent / f"{input_file.stem}_reviewed{input_file.suffix}"
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    typer.echo(f"Reviewed results saved to {output_file}")


# TODO: Add search reference functionality
# - Command to search for specific references in AOP-Wiki XML
# - Use aop_wiki_xml_ref_search.py and search_references.py
# - Export results to CSV/JSON


def _run_entities_and_fields_search(config, search_params, output_config, work_date, work_date_str, cache_dir, force_refresh):
    """
    Run multi-entity search with cross-comparison between events and AOPs.

    This search mode:
    1. Searches events using event-specific fields → directly matched events
    2. Searches AOPs using AOP-specific fields → matched AOPs
    3. Collects all event_ids from matched AOPs → AOP-linked events
    4. Compares sets: events found in both, only via text search, or only via AOP membership
    """
    entities_and_fields = search_params["entities_and_fields"]
    output_dir = output_config["directory"]
    os.makedirs(output_dir, exist_ok=True)

    # --- Step 1: Search events ---
    events_dict = collect_entity_with_cache(
        "events", collect_events_from_xml, work_date, cache_dir, force_refresh, logger
    )
    event_search_params = {**search_params, "fields_to_search": entities_and_fields.get("events", [])}
    event_summary, event_results_raw = search_entity_data(events_dict, event_search_params)
    event_results = serialize_search_results(event_results_raw)
    # collect_events_from_matched_aops stringifies its keys, so normalize this
    # side too rather than relying on both dicts happening to agree on key type
    matched_event_ids = {str(event_id) for event_id in event_results}

    # --- Step 2: Search AOPs ---
    aops_dict = collect_entity_with_cache(
        "aops", collect_aops_from_xml, work_date, cache_dir, force_refresh, logger
    )
    aop_search_params = {**search_params, "fields_to_search": entities_and_fields.get("aops", [])}
    aop_summary, aop_results_raw = search_entity_data(aops_dict, aop_search_params)
    aop_results = serialize_search_results(aop_results_raw)

    # --- Step 3: Collect all events from matched AOPs ---
    aop_events = collect_events_from_matched_aops(aop_results, events_dict, aops_dict=aops_dict)
    aop_event_ids = {str(event_id) for event_id in aop_events}

    # --- Step 4: Compare ---
    events_in_both = matched_event_ids & aop_event_ids
    events_text_only = matched_event_ids - aop_event_ids
    events_aop_only = aop_event_ids - matched_event_ids

    # Print summary
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  {config.replace('_', ' ').upper()} — ENTITIES AND FIELDS SEARCH")
    typer.echo(f"{'='*60}")
    typer.echo(f"  Events matched by text search:        {len(matched_event_ids)}")
    typer.echo(f"  AOPs matched by text search:          {len(aop_results)}")
    typer.echo(f"  Unique events in matched AOPs:        {len(aop_event_ids)}")
    typer.echo(f"  Events found by both routes:          {len(events_in_both)}")
    typer.echo(f"  Events matched by text only:          {len(events_text_only)}")
    typer.echo(f"  Events in matched AOPs only:          {len(events_aop_only)}")
    typer.echo(f"{'='*60}\n")

    # Export JSON
    output_data = {
        "search_config": config,
        "search_date": work_date_str,
        "summary": {
            "event_search": event_summary,
            "aop_search": aop_summary,
            "matched_event_count": len(matched_event_ids),
            "matched_aop_count": len(aop_results),
            "aop_linked_event_count": len(aop_event_ids),
            "events_in_both_count": len(events_in_both),
            "events_text_only_count": len(events_text_only),
            "events_aop_only_count": len(events_aop_only),
        },
        "matched_events": event_results,
        "matched_aops": aop_results,
        "comparison": {
            "events_in_both": sorted(events_in_both),
            "events_text_only": sorted(events_text_only),
            "events_aop_only": sorted(events_aop_only),
        },
    }
    json_filename = f"{config}_{work_date_str}.json"
    json_path = os.path.join(output_dir, json_filename)
    write_dict_to_json(output_data, output_dir, json_filename)
    typer.echo(f"✓ JSON written to {json_path}")

    # Export CSVs
    events_csv_path = os.path.join(output_dir, f"{config}_events_{work_date_str}.csv")
    write_combined_search_events_csv(event_results, aop_events, events_dict, events_csv_path)

    aops_csv_path = os.path.join(output_dir, f"{config}_aops_{work_date_str}.csv")
    write_search_results_csv(aop_results, aops_csv_path, "aops", aops_dict)

    typer.echo(f"✓ Search complete. Results in {output_dir}")


def _run_event_to_aop_search(config, search_params, output_config, work_date, work_date_str, cache_dir, force_refresh):
    """
    Run iterative event-to-AOP search and export results.
    
    This search mode:
    1. Finds events matching title terms
    2. Finds AOPs containing those events
    3. Collects all events associated with matched AOPs
    4. Exports event and AOP results
    """
    output_dir = output_config["directory"]
    os.makedirs(output_dir, exist_ok=True)
    
    # Run the iterative search
    results = search_events_to_aops(
        search_params, 
        work_date=work_date, 
        cache_dir=cache_dir,
        force_refresh=force_refresh,
        logger=logger
    )
    
    summary = results["summary"]
    matched_events = results["matched_events"]
    matched_aops = results["matched_aops"]
    events_dict = results["events_dict"]
    
    # Collect all events from matched AOPs
    aop_events = collect_events_from_matched_aops(matched_aops, events_dict)
    
    # Add aop_events count to summary
    summary["total_aop_events"] = len(aop_events)
    
    # Print summary
    _print_event_to_aop_summary(summary, len(aop_events))
    
    # Export results
    output_data = {
        "search_config": config,
        "search_date": work_date_str,
        "summary": summary,
        "matched_events": matched_events,
        "matched_aops": matched_aops,
        "aop_events": aop_events,
    }
    
    json_filename = f"{config}_{work_date_str}.json"
    json_path = os.path.join(output_dir, json_filename)
    print(f"Exporting results to {json_path}...")
    write_dict_to_json(output_data, output_dir, json_filename)
    
    logger.info(f"✓ Results written to {json_path}")
    
    # Print matched events info
    if matched_events:
        typer.echo(f"\nMatched Events ({len(matched_events)}):")
        for event_id, event_data in list(matched_events.items())[:10]:
            typer.echo(f"  - KE{event_id}: {event_data['title'][:60]}...")
        if len(matched_events) > 10:
            typer.echo(f"  ... and {len(matched_events) - 10} more")
    
    # Print matched AOPs info
    if matched_aops:
        typer.echo(f"\nMatched AOPs ({len(matched_aops)}):")
        for aop_id, aop_data in list(matched_aops.items())[:10]:
            typer.echo(f"  - AOP{aop_id}: {aop_data['title'][:60]}... (via {len(aop_data['source_events'])} events)")
        if len(matched_aops) > 10:
            typer.echo(f"  ... and {len(matched_aops) - 10} more")
    
    # Print all AOP events info
    if aop_events:
        typer.echo(f"\nAll Events from Matched AOPs ({len(aop_events)}):")
        for event_id, event_data in list(aop_events.items())[:10]:
            title = event_data['title'][:55] if event_data['title'] else 'Unknown'
            num_aops = len(event_data['found_in_aops'])
            typer.echo(f"  - KE{event_id}: {title}... (in {num_aops} AOP{'s' if num_aops > 1 else ''})")
        if len(aop_events) > 10:
            typer.echo(f"  ... and {len(aop_events) - 10} more")
    
    typer.echo(f"\n✓ Search complete. Results in {output_dir}")



# ============================================================================
# Console Output Helpers
# ============================================================================

def _print_event_to_aop_summary(summary, total_aop_events=0):
    """Print formatted event-to-AOP search summary to console."""
    typer.echo(f"\n{'='*60}")
    typer.echo(f"EVENT-TO-AOP ITERATIVE SEARCH SUMMARY")
    typer.echo(f"{'='*60}")
    typer.echo(f"Search terms: {', '.join(summary['ke_title_terms'])}")
    typer.echo(f"Total events searched: {summary['total_events_searched']}")
    typer.echo(f"Total AOPs searched: {summary['total_aops_searched']}")
    typer.echo(f"Total Events matched: {summary['total_events_matched']}")
    typer.echo(f"Total AOPs matched: {summary['total_aops_matched']}")
    typer.echo(f"Total Events in matched AOPs: {total_aop_events}")
    
    if summary.get('event_totals_by_term'):
        typer.echo(f"\nEvents by search term:")
        for term, count in summary['event_totals_by_term'].items():
            typer.echo(f"  - '{term}': {count} events")
    typer.echo(f"{'='*60}\n")


def _count_kers_by_key_event(matched_kers):
    """Count how many KERs each key event was found in, split by endpoint role."""
    counts = {}
    for ker_data in matched_kers.values():
        for event_id, role in ker_data["roles"].items():
            tally = counts.setdefault(event_id, {"upstream": 0, "downstream": 0})
            tally[role] += 1
    return counts


def _print_ker_lookup_summary(summary: dict, matched_kers: dict, limit: int) -> None:
    """Print formatted key-event-to-KER lookup summary to console."""
    typer.echo(f"\n{'='*60}")
    typer.echo(f"KERS CONTAINING KEY EVENTS")
    typer.echo(f"{'='*60}")
    if summary['ke_title_terms']:
        typer.echo(f"KE title terms: {', '.join(summary['ke_title_terms'])}")
    typer.echo(f"Key events: {', '.join(summary['key_event_ids'])}")
    typer.echo(f"Total KERs searched: {summary['total_kers_searched']}")
    typer.echo(f"Total KERs matched: {summary['total_kers_matched']}")

    typer.echo(f"\nKERs by key event:")
    for event_id, tally in summary['kers_by_key_event'].items():
        typer.echo(
            f"  - KE{event_id}: upstream in {tally['upstream']} KERs, "
            f"downstream in {tally['downstream']} KERs"
        )

    if matched_kers:
        typer.echo(f"\nMatched KERs ({len(matched_kers)}):")
        for ker_id, ker_data in list(matched_kers.items())[:limit]:
            roles = ', '.join(f'KE{eid} {role}' for eid, role in ker_data['roles'].items())
            typer.echo(f"  - KER{ker_id}: {ker_data['title'][:70]} ({roles})")
        if len(matched_kers) > limit:
            typer.echo(f"  ... and {len(matched_kers) - limit} more (raise --limit to see them)")
    typer.echo(f"{'='*60}\n")


def _print_search_summary(summary: dict, entity_type: str = "entities", search_type: str = "SEARCH") -> None:
    """
    Print formatted search summary to console.
    
    Args:
        summary: Dictionary with 'terms_searched', 'fields_searched', 'total_entities_with_matches'
        entity_type: Type of entities searched (e.g., "KERs", "events", "AOPs")
        search_type: Description of search type (e.g., "CONCORDANCE", "APOPTOSIS")
    """
    typer.echo(f"\n{'='*60}")
    typer.echo(f"{search_type.upper()} SEARCH SUMMARY")
    typer.echo(f"{'='*60}")
    typer.echo(f"Fields searched: {', '.join(summary['fields_searched'])}")
    typer.echo(f"Terms searched: {', '.join(summary['terms_searched'].keys())}")
    for term, count in summary['terms_searched'].items():
        typer.echo(f"  - '{term}': found in {count} {entity_type}")
    typer.echo(f"Total {entity_type} with matches: {summary['total_entities_with_matches']}")
    typer.echo(f"{'='*60}\n")

def _print_event_summary(summary: dict) -> None:
    """Print formatted event collection summary to console."""
    typer.echo(f"\n{'='*60}")
    typer.echo(f"EVENT INTEGRATION RANKING SUMMARY")
    typer.echo(f"{'='*60}")
    typer.echo(f"Total events: {summary['total_events']}")
    typer.echo(f"Average completion: {summary['average_completion_percent']}%")
    typer.echo(f"Average integration score: {summary['average_integration_score']}")
    typer.echo(f"Events with methods: {summary['events_with_methods']}")
    typer.echo(f"Events only open for adoption: {summary['events_only_open_for_adoption']}")
    typer.echo(f"Events in OECD AOP program: {summary['events_in_oecd_program']}")
    typer.echo(f"OECD endorsed events: {summary['events_oecd_endorsed']}")
    typer.echo(f"Events (non-OECD, non-open-adoption): {summary['events_non_oecd_non_adoption']}")
    typer.echo(f"{'='*60}\n")

def _print_ker_statistics(stats: dict) -> None:
    """Print formatted KER statistics summary to console."""
    typer.echo(f"\n{'='*60}")
    typer.echo(f"KER ANALYTICS SUMMARY")
    typer.echo(f"{'='*60}")
    typer.echo(f"Total KERs: {stats['total_kers']}")
    typer.echo(f"KERs with tables: {stats['kers_with_tables']}")
    typer.echo(f"KERs without tables: {stats['kers_without_tables']}")
    typer.echo(f"Average completion score (all KERs): {stats['average_completion_score']}%")
    typer.echo(f"Average completion score (KERs with tables): {stats['average_completion_score_kers_with_tables']}%")
    typer.echo(f"Average completion score (KERs without tables): {stats['average_completion_score_kers_without_tables']}%")
    typer.echo(f"{'='*60}\n")

def _print_match_metrics(metrics: dict) -> None:
    """Print formatted KE description to harmonized KE matching report."""
    typer.echo(f"\n{'='*60}")
    typer.echo(f"KE DESCRIPTION TO HARMONIZED KE MATCHING REPORT")
    typer.echo(f"{'='*60}")
    typer.echo(f"Total KE descriptions: {metrics['total_ke_descriptions']}")
    typer.echo(f"Fuzzy matches: {metrics['fuzzy_matches']}")
    print(f"No matches: {metrics['no_matches']}")
    print(f"Match rate: {metrics['match_rate']:.1%}")
    if metrics['fuzzy_matches'] > 0:
        print(f"Average match score: {metrics['average_match_score']:.2f}")
    if metrics['unmatched_descriptions']:
        print(f"\nUnmatched KE descriptions:")
        for desc in metrics['unmatched_descriptions']:
            print(f"  - {desc}")
    print("="*60 + "\n")

if __name__ == "__main__":
    app()
