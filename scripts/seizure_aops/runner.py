"""Typer app for the single-use seizure-AOP workflow (issue #28).

These two commands were previously `collect-harmonized-seizure-aops` and
`manually-review-matches` on the main `aop-wiki-cli` app. They process the Behl
seizure supplementary workbook — one specific input, not reusable — so they now
live in this standalone runner outside the installed library. They still use
the reusable `aop_wiki_cli.*` library for XML collection, paths and exports.

Run from the repository root::

    $ uv run python -m scripts.seizure_aops collect-harmonized-seizure-aops
    $ uv run python -m scripts.seizure_aops collect-harmonized-seizure-aops --date 03-12-2026
    $ uv run python -m scripts.seizure_aops manually-review-matches <file.json> --threshold 0.9
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import typer

from aop_wiki_cli.utilities import set_up_logger, get_dated_cache_dir
from aop_wiki_cli.paths import (
    cache_root,
    curated_input_path,
    ensure_dir,
    outputs_dir,
    seizure_workbook_path,
)
from aop_wiki_cli.parsers import (
    collect_aops_from_xml,
    collect_events_from_xml,
    collect_entity_with_cache,
)

from scripts.seizure_aops.parse_behl_seizure_aop_workbook import parse_seizure_aop_workbook
from scripts.seizure_aops.map_ke_descriptions_to_harmonized import (
    map_ke_descriptions_to_harmonized_kes,
    enrich_target_families,
    map_assays_to_events_via_target_families,
)
from scripts.seizure_aops.manual_match_review import review_matches, calculate_review_summary
from scripts.seizure_aops.analyze_seizure_aop_content import organize_and_enrich_harmonized_events
from scripts.seizure_aops.seizure_aop_export import export_seizure_aop_results

app = typer.Typer(help="Single-use seizure-AOP harmonization workflow.")

logger = set_up_logger('aop-wiki-cli-seizure', level=logging.INFO)
today = date.today()


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

    1. Parses the seizure AOP workbook (behl_seizure_supp_data.xlsx, shipped with the tool
       unless overridden at <data-dir>/inputs/seizure_aops/)
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
        The workflow uses the curated review files shipped with the tool unless copies
        exist in <data-dir>/curated/, which take precedence. If a curated file is found,
        interactive review is skipped. Use --skip-curated to bypass curated inputs and run
        interactive review.

    Outputs:
        Results are written to <data-dir>/outputs/seizure_aops/{date}/ including:
        - harmonized_events_{date}.csv: Harmonized key events
        - assays_{date}.csv: Assay data mapped to events
        - seizure_aop_events_{date}.xlsx: Combined Excel workbook
        - Various JSON files with mappings and validation results

    Examples:
        uv run python -m scripts.seizure_aops collect-harmonized-seizure-aops
        uv run python -m scripts.seizure_aops collect-harmonized-seizure-aops --date 03-12-2026
        uv run python -m scripts.seizure_aops collect-harmonized-seizure-aops --skip-curated --force-refresh

    # TODO: Add option to pass a file path for the curated inputs.
    """
    # Setup
    work_date = datetime.strptime(cache_date, '%m-%d-%Y').date() if cache_date else today
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_dir = get_dated_cache_dir(cache_root(), work_date)
    output_dir = ensure_dir(outputs_dir('seizure_aops'))

    logger.info("Parsing seizure AOP workbook...")

    # Parse the workbook and collect all seizure AOP content into a structured dictionary
    workbook_path = seizure_workbook_path()

    # `parse_seizure_aop_workbook()` returns a dict of many properties, organized into differnt formats for different purposes.
    seizure_content = parse_seizure_aop_workbook(workbook_path)

    """
    Behl mapped assays to KE descriptions, rather than exact KE titles. Therefore, use fuzzy matching to find best
    harmonized KE title match for each KE description.
    """

    # Extract specific properties for further processing, and then pass to map_ke_descriptions_to_harmonized_kes()
    # First, check if reviewed file already exists from a previous run, and if so, use that as input to preserve human-reviewed matches
    path_to_reviewed_matches = curated_input_path(
        "reviewed_ke_description_to_harmonized_ke_mapping.json"
    )
    if not skip_curated and path_to_reviewed_matches.exists():
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

    path_to_curated_events_to_target_families = curated_input_path(
        "curated_event-target_family_mappings.json"
    )
    if not skip_curated and path_to_curated_events_to_target_families.exists():
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

    uv run python -m scripts.seizure_aops manually-review-matches <data-dir>/outputs/seizure_aops/{date}/mapping_ke_description_to_harmonized_ke_{date}.json --threshold 0.9

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


if __name__ == "__main__":
    app()
