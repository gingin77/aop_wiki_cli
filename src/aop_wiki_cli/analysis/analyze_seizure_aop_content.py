

import pprint as pp

# Excluded harmonized title values
EXCLUDED_HARMONIZED_TITLES = {"E", "nan"}

def _summarize_results(enriched_results):
    result_summary = {}
    unique_events = set()
    for aop_id, events in enriched_results.items():
        unique_events.update(events.keys())
        result_summary[aop_id] = {
            'total_events': len(events),
            'unique_events': 0,  # Placeholder, will be updated after processing all entities
            'matched_events': sum(1 for e in events.values() if e.get('event_match')),
            'unmatched_events': sum(1 for e in events.values() if not e.get('event_match')),
            "excluded_events": sum(1 for e in events.values() if e.get('harmonized_event') == "E"),
            "nan_events": sum(1 for e in events.values() if e.get('harmonized_event') == "nan"),
        }

    result_summary['unique_events'] = len(unique_events)

    return result_summary

def add_wiki_content(seizure_aop_events, cached_aops, cached_events):
    print("\n" + "="*60)
    print("Comparing extracted seizure AOP events with cached AOP Wiki XML data...")
    print("="*60)
    
    enriched_results = {}
    result_summary = {}
    print(f"\n*** The output that follows supported manual QC check of title string differences ***\n")
    for aop_id, seiz_events in seizure_aop_events.items():
        # Check for the AOP ID in the cached AOPs from the Wiki XML data
        enriched_results[aop_id] = {}
        if aop_id not in cached_aops:
            print(f"  No match found for AOP {aop_id} in cached AOPs.")
            continue

        # Check each event and add match metadata
        for seiz_event_id, seiz_event_details in seiz_events.items():
            enriched_event = seiz_event_details.copy()
            enriched_event['aop_id'] = aop_id

            # Remove title from Behl for cleaner export; functions below make comparisons between 
            # Behl Title and Wiki title for each KE ID.
            enriched_event.pop('title', None)  
            
            # Check for matching events based on Event ID
            str_event_id = str(seiz_event_id)
            event_match_by_id = str_event_id in cached_events
            enriched_event['event_match'] = event_match_by_id

            if event_match_by_id:
                wiki_event = cached_events[str_event_id]
                behl_title_str = seiz_event_details.get('title', '').strip().lower()
                wiki_title_str = wiki_event.get('title', '').strip().lower()

                if behl_title_str != wiki_title_str:
                    # TODO add fuzzy matching to quantify title similarity with more transparency.
                    # For now, just printing out the differences for manual review leads me to be confident that
                    # the title string differences do not consistitute meaningful curation differences.
                    print(f"Title string difference for event ID {seiz_event_id}:")
                    print(f"    Behl title: '{behl_title_str}'")
                    print(f"    Wiki title: '{wiki_title_str}'")
                enriched_event['title_from_wiki'] = wiki_event["title"]
                enriched_event['lobo'] = wiki_event["level_of_biological_organization"]
            else:
                enriched_event['title_from_wiki'] = None
                enriched_event['lobo'] = None

            enriched_results[aop_id][seiz_event_id] = enriched_event
    
    result_summary = _summarize_results(enriched_results)

    return enriched_results, result_summary

def analyze_harmonized_kes(enriched_results):
    """Pivot event data from AOP-centric to harmonization-centric organization.

    Reorganizes events from {AOP ID -> event ID} to {harmonized title -> event ID -> row index},
    grouping wiki events that map to the same harmonized concept.

    Aggregates metadata (LOBOs, AOP IDs, references, target families) across all events
    sharing a harmonized title and summarizes how many distinct wiki events collapse into
    each harmonized KE. Events marked as excluded ("E") or unassigned ("nan") are separated
    from valid harmonizations.

    Args:
        enriched_results: Dict of {aop_id: {event_id: event_data}} from add_wiki_content.

    Returns:
        Tuple of (harmonized_kes, summary) where:
        - harmonized_kes: Dict of {harmonized_title: {event_id: {row_index: event_data}}}
        - summary: Dict with counts and per-harmonized-KE metadata aggregations
    """
    harmonized_kes = {}
    for events in enriched_results.values():
        for event_id, event_data in events.items():
            harmonized_title = event_data.get('harmonized_event')
            row_index = event_data.get('row_index')
            
            harmonized_kes.setdefault(harmonized_title, {})
            harmonized_kes[harmonized_title].setdefault(event_id, {})[row_index] = event_data

    harmonized_titles = [title for title in harmonized_kes.keys() if title not in EXCLUDED_HARMONIZED_TITLES]

    summary = {
        'count_unique_harmonized_kes': len(harmonized_titles),
        "excluded_count": len(harmonized_kes.get("E", {})),
        "nan_count": len(harmonized_kes.get("nan", {})),
        "harmonized_kes": {},
    }
    for title in sorted(harmonized_titles):
        pre_harmonized_events = harmonized_kes[title]
        total_events = len(pre_harmonized_events)
        lobos = set(
            event_data.get('lobo') 
            for row_indices in pre_harmonized_events.values() 
            for event_data in row_indices.values() 
            if event_data.get('lobo')
        )
        lobo_count = len(lobos)
        aop_ids = set(
            event_data.get('aop_id')
            for row_indices in pre_harmonized_events.values()
            for event_data in row_indices.values()
            if event_data.get('aop_id')
        )
        references = set(
            event_data.get('references')
            for row_indices in pre_harmonized_events.values()
            for event_data in row_indices.values()
            if event_data.get('references') and event_data.get('references') not in ('nan', '', 'None')
        )
        target_families = set(
            event_data.get('target_family')
            for row_indices in pre_harmonized_events.values()
            for event_data in row_indices.values()
            if event_data.get('target_family') and event_data.get('target_family') not in ('nan', '', 'None')
        )
        summary["harmonized_kes"][title] = {
            'total_events': total_events,
            'event_ids': list(pre_harmonized_events.keys()),
            'lobos': list(lobos),
            'lobo_count': lobo_count,
            'aop_ids': list(aop_ids),
            'references': list(references),
            'target_families': list(target_families)
        }

    return harmonized_kes, summary


def organize_and_enrich_harmonized_events(seizure_aop_events, cached_aops, cached_events):
    """Main entry point for seizure AOP analysis.

    Orchestrates the full analysis pipeline:
    1. Enriches Behl workbook events with AOP-Wiki XML metadata (titles, LOBOs)
    2. Reorganizes events by harmonized KE title for cross-AOP aggregation

    Args:
        seizure_aop_events: Dict of {aop_id: {event_id: event_data}} from workbook parser
        cached_aops: Dict of AOP data from parsed Wiki XML
        cached_events: Dict of event data from parsed Wiki XML, keyed by event ID

    Returns:
        Tuple of (extraction_summary, enriched_results_by_harmonized_kes, harmonized_summary):
        - extraction_summary: Per-AOP counts of matched/unmatched/excluded events
        - enriched_results_by_harmonized_kes: Events reorganized by harmonized title
        - harmonized_summary: Aggregated metadata per harmonized KE
    """
    enriched_results, extraction_summary = add_wiki_content(seizure_aop_events, cached_aops, cached_events)

    enriched_results_by_harmonized_kes, harmonized_summary = analyze_harmonized_kes(enriched_results)

    return extraction_summary, enriched_results_by_harmonized_kes, harmonized_summary