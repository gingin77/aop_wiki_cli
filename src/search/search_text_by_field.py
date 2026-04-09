"""
Search text fields in AOP-Wiki entity data for specified terms.

Supports term matching with word boundaries, co-occurrence detection, exclusion filtering,
and priority field flagging. Includes HTML parsing and snippet extraction.

FUNCTION CALL CHAIN:
====================

screen_aop_wiki_fields_for_input_terms()  ← Convenience wrapper (collects XML + searches)
    │
    ├─→ collect_xml_data() ────────────────→ (from get_aop_wiki_xml_data)
    ├─→ collect_kers_from_xml() ───────────→ (from parse_aop_wiki_xml_data)
    │
    └─→ search_entity_data() ──────────────← Main orchestrator for searching
            │
            ├─→ _perform_entity_search() ───────← Main search loop
            │       │
            │       ├─→ get_field_text() ────────← Extract field text
            │       ├─→ seek_search_phrase_in_field_text() ← Single field/term search
            │       │       │
            │       │       ├─→ parse_and_clean_text() ← HTML parsing
            │       │       ├─→ build_term_pattern() ──← Regex pattern building
            │       │       └─→ capture_snippet_around_term() ← Extract snippet
            │       │
            │       ├─→ check_term_co_occurrence() ──← Verify term pairs
            │       │       │
            │       │       ├─→ parse_and_clean_text() ← HTML parsing
            │       │       └─→ build_term_pattern() ──← Regex pattern building
            │       │
            │       └─→ add_search_result() ────────← Accumulate results
            │               └─→ is_overlapping_snippet() ← Check duplicates
            │
            ├─→ _calculate_co_occurrence_summary() ← Calculate statistics
            ├─→ _add_entity_metadata_and_flags() ───← Enrich with metadata
            │
            └─→ find_entities_with_exclusion_terms() ← Filter exclusions
                    │
                    ├─→ get_field_text() ────────────← Extract field text
                    ├─→ parse_and_clean_text() ──────← HTML parsing
                    └─→ build_term_pattern() ────────← Regex pattern building


HELPER FUNCTIONS:
=================

Text Processing:
- parse_and_clean_text() ────── Parse HTML and normalize whitespace
- build_term_pattern() ───────── Build regex with word boundaries
- get_field_text() ───────────── Handle nested dict structures

Filtering:
- find_entities_with_exclusion_terms() ─ Filter by exclusion terms


TYPICAL USAGE:
==============

1. With pre-collected (cached) data:
   >>> all_kers = collect_entity_with_cache('kers', ...)
   >>> search_params = {
   ...     "fields_to_search": ["empirical_support"], 
   ...     "terms": ["concordance"],
   ...     "exclusion_terms": ["discordance"]
   ... }
   >>> summary, results = search_entity_data(all_kers, search_params)

2. One-off search (collects fresh data):
   >>> search_params = {
   ...     "fields_to_search": ["description"], 
   ...     "terms": ["apoptosis"],
   ...     "title_exclusion_terms": ["liver"]
   ... }
   >>> results = screen_aop_wiki_fields_for_input_terms("events", search_params)

3. Direct single-field search:
   >>> result = seek_search_phrase_in_field_text(field_text, "concordance")
"""

import re
from datetime import date
from bs4 import BeautifulSoup

from src.parsers import (
    collect_aops_from_xml, 
    collect_events_from_xml, 
    collect_kers_from_xml,
    collect_entity_with_cache
)
from src.search.result_processors import serialize_search_results

TODAY = date.today()


# ============================================================================
# Helper Functions for Text Processing
# ============================================================================

def parse_and_clean_text(text):
    """Parse HTML and normalize whitespace."""
    soup = BeautifulSoup(text, 'html.parser')
    clean_text = soup.get_text()
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text


def build_term_pattern(term):
    """Build regex pattern for term with word boundaries and flexible whitespace."""
    escaped_term = re.escape(term.lower())
    return r"\b" + escaped_term.replace(r"\ ", r"\s+") + r"\b"


def get_field_text(entity_info, field):
    """Get field text, handling nested dict structures."""
    field_text = entity_info.get(field, "")
    if isinstance(field_text, dict):
        field_text = field_text.get("free_text", "")
    return field_text


def find_entities_with_exclusion_terms(entity_dict, search_results_dict, exclusion_terms, fields_to_check):
    """
    Find entities containing any exclusion terms in specified fields.
    
    Args:
        entity_dict: Dictionary of all entities
        search_results_dict: Dictionary of search results to check
        exclusion_terms: List of terms to exclude
        fields_to_check: List of field names to check (e.g., ['title'] or multiple fields)
    
    Returns:
        Set of entity IDs that should be excluded
    """
    entities_to_exclude = set()
    
    for entity_id in search_results_dict:
        entity_info = entity_dict.get(entity_id, {})
        
        # Check specified fields for exclusion terms
        for field in fields_to_check:
            field_text = get_field_text(entity_info, field) if field != "title" else entity_info.get("title", "")
            
            if not field_text:
                continue
            
            # Parse HTML and normalize whitespace
            clean_text = parse_and_clean_text(str(field_text))
            clean_text_lower = clean_text.lower()
            
            # Check if any exclusion term appears in this field (with word boundaries)
            for exclusion_term in exclusion_terms:
                pattern = build_term_pattern(exclusion_term)
                if re.search(pattern, clean_text_lower):
                    entities_to_exclude.add(entity_id)
                    break  # No need to check more exclusion terms for this field
            
            if entity_id in entities_to_exclude:
                break  # No need to check more fields for this entity
    
    return entities_to_exclude


def _perform_entity_search(entity_dict, fields_to_search, search_terms, co_occurrence_pairs, 
                          content_to_drop_by_field, summary):
    """
    Perform the main search across all entities and fields.
    
    Modifies summary dict in place.
    
    Returns:
        Tuple of (search_results_dict, entities_with_co_occurrences)
        - search_results_dict: Dict of entity_id -> search result data
        - entities_with_co_occurrences: Dict mapping co-occurrence pair keys to sets of entity IDs
    """
    search_results_dict = {}
    entities_with_co_occurrences = {str(pair): set() for pair in co_occurrence_pairs}
    
    # Search each entity's fields for terms
    for entity_id, entity_info in entity_dict.items():
        for field in fields_to_search:
            field_text = get_field_text(entity_info, field)
            
            if not field_text:
                continue
            
            # Strip content if specified for this field
            if field in content_to_drop_by_field:
                field_text = field_text.replace(content_to_drop_by_field[field], "")
                if not field_text:
                    continue
            
            # Search for each term in this field
            for term in search_terms:
                result = seek_search_phrase_in_field_text(field_text, term)
                
                if result['found']:
                    summary["terms_searched"][term] += 1
                    add_search_result(
                        entity_id, 
                        term, 
                        field, 
                        result['snippet'], 
                        search_results_dict
                    )
            
            # Check for co-occurrence pairs in this field
            for pair in co_occurrence_pairs:
                if check_term_co_occurrence(field_text, pair):
                    pair_key = str(pair)
                    summary["co_occurrence_matches"][pair_key]["total_instances"] += 1
                    entities_with_co_occurrences[pair_key].add(entity_id)
                    add_search_result(
                        entity_id,
                        None,  # No single term
                        field,
                        None,  # No snippet for now
                        search_results_dict,
                        co_occurrence_pair=pair
                    )
    
    return search_results_dict, entities_with_co_occurrences


def _calculate_co_occurrence_summary(entities_with_co_occurrences, summary):
    """Calculate and update co-occurrence summary statistics."""
    # Calculate unique entities for each co-occurrence pair
    for pair_key in entities_with_co_occurrences:
        summary["co_occurrence_matches"][pair_key]["unique_entities"] = len(entities_with_co_occurrences[pair_key])
    
    # Calculate total unique entities with any co-occurrence match
    all_entities_with_co_occurrences = set()
    for entity_set in entities_with_co_occurrences.values():
        all_entities_with_co_occurrences.update(entity_set)
    summary["total_entities_with_co_occurrence_matches"] = len(all_entities_with_co_occurrences)


def _add_entity_metadata_and_flags(entity_dict, search_results_dict, priority_field):
    """Add entity metadata (id, title) and priority field flags to search results."""
    for entity_id in search_results_dict:
        entity_info = entity_dict.get(entity_id, {})
        search_results_dict[entity_id]["entity_id"] = entity_id
        search_results_dict[entity_id]["title"] = entity_info.get("title", "")
        
        # Check if any search term was found in the priority field
        matched_fields = search_results_dict[entity_id].get("matched_fields", set())
        search_results_dict[entity_id]["has_priority_term_match"] = (
            priority_field in matched_fields if priority_field else False
        )
        
        # Check if co-occurrences were found in the priority field
        co_occurrence_fields = search_results_dict[entity_id].get("co_occurrence_fields", set())
        search_results_dict[entity_id]["has_priority_co_occurrence"] = (
            priority_field in co_occurrence_fields if priority_field else False
        )

def is_overlapping_snippet(new_snippet, existing_snippets):
    """
    Check if a snippet is a duplicate or substring of existing snippets.
    Uses direct string comparison to detect overlaps.
    """
    for existing in existing_snippets:
        # Check for substring overlap
        if new_snippet in existing or existing in new_snippet:
            return True
        
        # Check for exact match after normalization
        if new_snippet == existing:
            return True
    
    return False


def check_term_co_occurrence(field_text, term_pair):
    """
    Check if a pair of terms both occur in the same field text.
    
    Args:
        field_text: Text content to search in
        term_pair: List/tuple of two terms [term1, term2]
        
    Returns:
        Boolean indicating if both terms are present
    """
    if not field_text or len(term_pair) != 2:
        return False
    
    # Parse HTML and normalize whitespace
    clean_text = parse_and_clean_text(field_text)
    clean_text_lower = clean_text.lower()
    
    # Check if both terms exist using word boundaries
    term1_pattern = build_term_pattern(term_pair[0])
    term2_pattern = build_term_pattern(term_pair[1])
    
    term1_found = re.search(term1_pattern, clean_text_lower) is not None
    term2_found = re.search(term2_pattern, clean_text_lower) is not None
    
    return term1_found and term2_found


def add_search_result(entity_id, term, field, snippet, search_results, co_occurrence_pair=None):
    """
    Add a single search result to the results dictionary (modifies in place).
    Tracks snippets by field, terms found, and fields searched for an entity.
    Only stores snippets that are not duplicates of other snippets from the same field.
    Counts the term as found even if no complete snippet could be extracted.
    
    Args:
        entity_id: ID of the entity
        term: Search term that was found
        field: Field name where term was found
        snippet: Text snippet around the term (can be None)
        search_results: Dictionary to store results in
        co_occurrence_pair: Optional tuple of (term1, term2) if this is a co-occurrence match
    """
    # Initialize entity structure if not seen before
    if entity_id not in search_results:
        search_results[entity_id] = {
            "snippets_by_field": {},
            "terms_found": set(),
            "matched_fields": set(),
            "co_occurrences": set(),
            "co_occurrence_fields": set()
        }
    
    entity_data = search_results[entity_id]
    
    # Initialize field snippets container if not seen before
    if field not in entity_data["snippets_by_field"]:
        entity_data["snippets_by_field"][field] = set()
    
    # Add snippet if it's not None and not a duplicate within this field
    if snippet is not None:
        field_snippets = entity_data["snippets_by_field"][field]
        if not is_overlapping_snippet(snippet, field_snippets):
            field_snippets.add(snippet)
    
    # Always track term and field, even if snippet was None or duplicate
    if term:
        entity_data["terms_found"].add(term)
    entity_data["matched_fields"].add(field)
    
    # Track co-occurrence if provided
    if co_occurrence_pair:
        entity_data["co_occurrences"].add(tuple(sorted(co_occurrence_pair)))
        entity_data["co_occurrence_fields"].add(field)


def search_entity_data(entity_dict, search_params, content_to_drop_by_field=None):
    """
    Search entity data for specified terms in specified fields.
    
    Args:
        entity_dict: Dictionary of entities (keyed by entity ID)
        search_params: Dict with keys:
            - "fields_to_search": List of field names to search (optional if priority_field is provided)
            - "priority_field": Optional field name to use as default if fields_to_search not provided
            - "terms": List of search terms
            - "co_occurrence_pairs": Optional list of [term1, term2] pairs to check for co-occurrence
            - "exclusion_terms": Optional list of terms; entities containing any of these in searched fields will be excluded
            - "title_exclusion_terms": Optional list of terms; entities containing any of these in title only will be excluded
        content_to_drop_by_field: Optional dict mapping field names to content to strip before searching
    
    Returns:
        tuple: (summary dict, search_results dict)
    """
    content_to_drop_by_field = content_to_drop_by_field or {}
    co_occurrence_pairs = search_params.get("co_occurrence_pairs", [])
    
    # Determine fields to search: use fields_to_search if provided, otherwise use priority_field
    if "fields_to_search" in search_params:
        fields_to_search = search_params["fields_to_search"]
    elif "priority_field" in search_params:
        fields_to_search = [search_params["priority_field"]]
    else:
        raise ValueError("Either 'fields_to_search' or 'priority_field' must be provided in search_params")
    
    # Initialize summary dictionary
    summary = {
        "terms_searched": {term: 0 for term in search_params["terms"]},
        "fields_searched": fields_to_search,
        "total_entities_with_matches": 0,
        "total_entities_with_co_occurrence_matches": 0,
        "co_occurrence_matches": {
            str(pair): {"total_instances": 0, "unique_entities": 0} 
            for pair in co_occurrence_pairs
        }
    }
    
    # Step 1: Search all entities for terms and co-occurrences
    search_results_dict, entities_with_co_occurrences = _perform_entity_search(
        entity_dict, fields_to_search, search_params["terms"], 
        co_occurrence_pairs, content_to_drop_by_field, summary
    )
    
    # Step 2: Calculate co-occurrence summary statistics
    _calculate_co_occurrence_summary(entities_with_co_occurrences, summary)
    
    # Step 3: Add entity metadata and priority field flags
    priority_field = search_params.get("priority_field")
    _add_entity_metadata_and_flags(entity_dict, search_results_dict, priority_field)
    
    # Step 4: Apply exclusion filters (removes entities from search_results_dict)
    exclusion_terms = search_params.get("exclusion_terms", [])
    if exclusion_terms:
        # Filter by exclusion_terms in any searched field
        entities_to_exclude = find_entities_with_exclusion_terms(
            entity_dict, search_results_dict, exclusion_terms, fields_to_search
        )
        for entity_id in entities_to_exclude:
            del search_results_dict[entity_id]
    
    title_exclusion_terms = search_params.get("title_exclusion_terms", [])
    if title_exclusion_terms:
        # Filter by title_exclusion_terms in title field only
        entities_to_exclude = find_entities_with_exclusion_terms(
            entity_dict, search_results_dict, title_exclusion_terms, ["title"]
        )
        for entity_id in entities_to_exclude:
            del search_results_dict[entity_id]
    
    # Step 5: Finalize summary and return results
    summary["total_entities_with_matches"] = len(search_results_dict)
    return summary, search_results_dict

def screen_aop_wiki_fields_for_input_terms(entity, input_search_params, content_to_drop_by_field=None, 
                                           work_date=None, output_dir='outputs/search_cache', 
                                           force_refresh=False, logger=None):
    """
    Search AOP-Wiki fields for specified terms and return results with snippets.
    Uses cached entity data when available.
    
    :param entity: "events", "kers", or "aops"
    :param input_search_params: Dict with "fields_to_search" and "terms" keys
    :param content_to_drop_by_field: Optional dict mapping field names to content to strip
    :param work_date: Date for cache files (defaults to today)
    :param output_dir: Directory for cache files
    :param force_refresh: Force fresh data collection
    :param logger: Optional logger instance
    :return: Dict with "summary" and "search_results_by_entity_id"
    """
    work_date = work_date or TODAY
    content_to_drop_by_field = content_to_drop_by_field or {}
    
    # Map entity types to collection functions
    collection_functions = {
        "events": collect_events_from_xml,
        "aops": collect_aops_from_xml,
        "kers": collect_kers_from_xml
    }
    
    if entity not in collection_functions:
        raise ValueError(f"Entity type '{entity}' not supported. Choose from: {list(collection_functions.keys())}")
    
    # Collect data with automatic caching
    content_to_search = collect_entity_with_cache(
        entity, 
        collection_functions[entity],
        work_date,
        output_dir,
        force_refresh,
        logger
    )
    
    summary, search_results_dict = search_entity_data(
        content_to_search, 
        input_search_params,
        content_to_drop_by_field
    )
    
    # Convert sets to lists for serialization
    serialize_search_results(search_results_dict)
    
    return {
        "summary": summary,
        "search_results_by_entity_id": search_results_dict
    }

def capture_snippet_around_term(clean_text, term_index, term_end):
    """
    Capture a snippet of text around the term, bounded by sentence boundaries.
    Returns the snippet only if it's complete and not truncated.
    Returns None if the snippet ends with an abbreviation or incomplete pattern.
    """
    # Find sentence start (look backward for . ! ? followed by space and capital letter, or start of text)
    sentence_start = 0
    for i in range(term_index - 1, -1, -1):
        if clean_text[i] in '.!?':
            # Check if this is a real sentence boundary: punctuation followed by space(s) and capital letter
            j = i + 1
            while j < len(clean_text) and clean_text[j] == ' ':
                j += 1
            if j < len(clean_text) and clean_text[j].isupper() and j <= term_index:
                # Found a valid sentence boundary
                sentence_start = j
                break
    
    # Find sentence end (first occurrence of . ! ? after term, or end of text)
    sentence_end = len(clean_text)
    for i in range(term_end, len(clean_text)):
        if clean_text[i] in '.!?':
            sentence_end = i + 1
            break
    
    snippet = clean_text[sentence_start:sentence_end].strip()
    
    # Validate snippet completeness - return None if truncated or incomplete
    if snippet.endswith('(') or snippet.endswith('(www.'):
        return None
    
    if len(snippet) > 3:
        last_words = snippet[-4:].strip()
        incomplete_endings = ['No.', 'Jr.', 'Sr.', 'Dr.', 'Mr.', 'Ms.', 'etc.', 'vs.']
        if last_words in incomplete_endings:
            return None
    
    return snippet

def seek_search_phrase_in_field_text(field_text, term):
    """
    Cleans up input field_text and searches for the given term.
    Only returns results with complete, non-truncated snippets.
    
    Args:
        field_text (str): Text content of a specific field.
        term (str): The search phrase to look for within the field_text.
    Returns:
        dict: Dictionary with properties:
            found: Boolean indicating if term was found
            term: The term searched for
            snippet: A complete text snippet where the term was found (or None if incomplete)
            field_text: The text content where the term was found
    """
    result = {
        "term": term,
        "found": False,
        "snippet": None,
        "field_text": None
    }

    # Parse HTML and extract clean text
    clean_text = parse_and_clean_text(field_text)

    # Use word boundaries to avoid partial matches
    term_pattern = build_term_pattern(term)
    match = re.search(term_pattern, clean_text.lower())
    if match:
        result['found'] = True
        result['field_text'] = clean_text
        term_index = match.start()
        term_end = match.end()
        # Extract snippet around the term with sentence boundaries
        snippet = capture_snippet_around_term(clean_text, term_index, term_end)
        
        # Only add snippet if complete and not truncated
        if snippet:
            result['snippet'] = snippet
        else:
            result['snippet'] = None
    
    return result
