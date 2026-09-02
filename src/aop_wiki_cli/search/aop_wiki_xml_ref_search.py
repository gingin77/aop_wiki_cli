"""
Purpose: Search AOP-Wiki XML files for references to specific publications.
This script parses AOP-Wiki XML exports to find references matching given search terms,
and outputs the relevant AOP, KE, and KER information along with the matching references.
"""

import datetime
import os
import pprint as pp

from aop_wiki_cli.collection import collect_xml_data
from aop_wiki_cli.parsers import collect_references_from_aops_kers_and_events, get_structured_references
from aop_wiki_cli.paths import outputs_dir
from aop_wiki_cli.utilities import write_dict_to_json
from aop_wiki_cli.search import (
    search_citations_by_field,
    search_citations_by_combination,
    search_citations_cross_field
)
from aop_wiki_cli.data_export import export_search_results_to_csv


def _perform_search(structured_references, search_terms, search_field='all'):
    """
    Core search logic - searches structured references for matching citations.
    
    Args:
        structured_references: Dict of parsed citations by entity type
        search_terms: Dict with search parameters
        search_field: Which field to search ('all', 'title', 'authors', 'journal', 'year', 'raw')
    
    Returns:
        Tuple of (matched_content, term_type_map)
    """
    matched_content = {}
    term_type_map = {}
    
    # Determine search type based on search_terms structure
    # Cross-field search: multiple criteria (e.g., author + year + title)
    # Single-field search: one criterion type (e.g., just author)
    field_types = set(search_terms.keys())
    recognized_fields = {'year', 'author', 'authors', 'publication_year', 'title', 'journal', 'phrase', 'terms', 'all'}
    is_cross_field_search = len(field_types) > 1 and all(f in recognized_fields for f in field_types)
    
    # BRANCH 1: Cross-field search (e.g., author='Smith' AND year='2020' AND title='toxicity')
    if is_cross_field_search:
        pp.pprint(f"Cross-field search for: {dict(search_terms)}")
        
        # Search each entity type (AOP, KE, KER) for citations matching ALL criteria
        for entity_type, entities in structured_references.items():
            matches = search_citations_cross_field(entities, search_terms)
            
            # Collect matching citations and the criteria they matched
            for entity_id, matching_citations_with_terms in matches.items():
                if entity_id not in matched_content:
                    matched_content[entity_id] = {
                        'entity_type': entity_type,
                        'matched_field': 'cross-field',
                        'citations': []
                    }
                
                for citation, matched_criteria in matching_citations_with_terms:
                    if not any(isinstance(c, tuple) and c[0].get('raw_citation') == citation.get('raw_citation')
                              or isinstance(c, dict) and c.get('raw_citation') == citation.get('raw_citation')
                             for c in matched_content[entity_id]['citations']):
                        matched_content[entity_id]['citations'].append((citation, matched_criteria))
                
                pp.pprint(f"Match found in {entity_type} ID {entity_id}")
        
        # Map each term to its field type for display purposes
        for field_key, terms in search_terms.items():
            display_type = field_key.replace('publication_', '')
            for term in terms:
                term_type_map[term] = display_type
    
    # BRANCH 2: Single-field search (e.g., just author='Smith' or just title terms)
    else:
        VALID_FIELDS = {'all', 'phrase', 'title', 'authors', 'author', 'journal', 'year', 'publication_year', 'raw'}
        
        # Process each term type in search_terms (usually just one for single-field)
        for term_type, terms in search_terms.items():
            # Determine which field to search: use search_field param or infer from term_type
            field_to_search = search_field if search_field != 'all' else term_type
            
            # Normalize field names (handle aliases)
            field_mapping = {
                'phrase': 'all',
                'author': 'authors',
                'publication_year': 'year',
                'terms': 'all'
            }
            
            if field_to_search in field_mapping:
                field_to_search = field_mapping[field_to_search]
            
            # Fallback to 'all' if invalid field
            if field_to_search not in VALID_FIELDS and field_to_search not in field_mapping.values():
                field_to_search = 'all'
            
            # Map terms to their display type for output
            display_type = 'phrase' if field_to_search == 'all' else field_to_search
            for term in terms:
                term_type_map[term] = display_type
            
            # Multiple terms = combination search (match any); single term = exact search
            use_combination = len(terms) > 1
            
            pp.pprint(f"Searching in {field_to_search} field for terms: {terms} (combination: {use_combination})")
            
            # Search each entity type (AOP, KE, KER) using appropriate method
            for entity_type, entities in structured_references.items():
                # Use combination search for multiple terms, field search for single term
                if use_combination:
                    matches = search_citations_by_combination(entities, terms, field_to_search, min_matches=1)
                else:
                    matches = search_citations_by_field(entities, terms, field_to_search)
                
                # Collect matching citations and avoid duplicates
                for entity_id, matching_citations_with_terms in matches.items():
                    if entity_id not in matched_content:
                        matched_content[entity_id] = {
                            'entity_type': entity_type,
                            'matched_field': field_to_search,
                            'citations': []
                        }
                    
                    for citation, matched_term in matching_citations_with_terms:
                        if not any(isinstance(c, tuple) and c[0].get('raw_citation') == citation.get('raw_citation')
                                  or isinstance(c, dict) and c.get('raw_citation') == citation.get('raw_citation')
                                 for c in matched_content[entity_id]['citations']):
                            matched_content[entity_id]['citations'].append((citation, matched_term))
                    
                    pp.pprint(f"Match found in {entity_type} ID {entity_id}")
    
    return matched_content, term_type_map


def _load_structured_references(today):
    """
    Load or generate structured references for the given date.
    Handles XML collection, parsing, and caching.
    
    Returns:
        Dict of structured references by entity type
    """
    root, xml_namespace, refs = collect_xml_data(today)
    
    reference_search_dir = outputs_dir('reference_search_results')
    parsed_refs_path = reference_search_dir / f'parsed_references_{today}.json'
    
    if not os.path.exists(parsed_refs_path):
        references_for_core_entities = collect_references_from_aops_kers_and_events(root, xml_namespace, refs)
        write_dict_to_json(references_for_core_entities, reference_search_dir, f'references_for_core_entities_{today}.json')
        
        structured_references = {}
        for entity_type in ['AOP', 'KE', 'KER']:
            structured_references[entity_type] = get_structured_references(references_for_core_entities, entity_type)
        write_dict_to_json(structured_references, reference_search_dir, f'parsed_references_{today}.json')
    else:
        import json
        with open(parsed_refs_path, 'r') as f:
            structured_references = json.load(f)
    
    return structured_references

def _validate_search_results(matched_content, expected_results, search_terms):
    """
    Validate search results against expected results.
    
    Args:
        matched_content: Dict of matched entities and citations
        expected_results: Dict with expected counts and entity IDs
        search_terms: The search terms used (for error reporting)
    """
    # Count actual results
    actual_entity_count = len(matched_content)
    actual_citation_count = sum(len(data['citations']) for data in matched_content.values())
    
    # Organize actual entities by type
    actual_entities = {'aop_ids': [], 'ke_ids': [], 'ker_ids': [], 'event_ids': []}
    for entity_id, data in matched_content.items():
        entity_type = data['entity_type']
        entity_id_int = int(entity_id)
        if entity_type == 'AOP':
            actual_entities['aop_ids'].append(entity_id_int)
        elif entity_type == 'KE':
            actual_entities['event_ids'].append(entity_id_int)
        elif entity_type == 'KER':
            actual_entities['ker_ids'].append(entity_id_int)
    
    # Sort for comparison
    for key in actual_entities:
        actual_entities[key].sort()
    
    # Compare and report
    validation_passed = True
    
    print(f"\n{'='*60}")
    print(f"VALIDATION REPORT: {search_terms}")
    print(f"{'='*60}")
    
    # Check entity count
    if 'entity_count' in expected_results:
        if actual_entity_count == expected_results['entity_count']:
            print(f"✓ Entity count: {actual_entity_count} (matches expected)")
        else:
            print(f"✗ Entity count: {actual_entity_count} (expected {expected_results['entity_count']})")
            validation_passed = False
    
    # Check citation count
    if 'citation_count' in expected_results:
        if actual_citation_count == expected_results['citation_count']:
            print(f"✓ Citation count: {actual_citation_count} (matches expected)")
        else:
            print(f"✗ Citation count: {actual_citation_count} (expected {expected_results['citation_count']})")
            validation_passed = False
    
    # Check specific entity IDs
    if 'entities' in expected_results:
        for entity_type, expected_ids in expected_results['entities'].items():
            actual_ids = actual_entities.get(entity_type, [])
            expected_ids_sorted = sorted(expected_ids)
            
            if actual_ids == expected_ids_sorted:
                print(f"✓ {entity_type}: {actual_ids} (matches expected)")
            else:
                print(f"✗ {entity_type}: {actual_ids} (expected {expected_ids_sorted})")
                missing = set(expected_ids_sorted) - set(actual_ids)
                extra = set(actual_ids) - set(expected_ids_sorted)
                if missing:
                    print(f"  Missing: {sorted(missing)}")
                if extra:
                    print(f"  Extra: {sorted(extra)}")
                validation_passed = False
    
    if validation_passed:
        print(f"\n{'='*60}")
        print(f"✓ ALL VALIDATIONS PASSED")
        print(f"{'='*60}\n")
    else:
        print(f"\n{'='*60}")
        print(f"✗ VALIDATION FAILED")
        print(f"{'='*60}\n")

def search_xml_for_a_specific_reference(today, search_terms, output_file, search_field='all', expected_results=None):
    """
    Search for a specific reference in AOP-Wiki XML using cross-field criteria.
    
    Designed to find a specific publication by combining year, author name, and title terms.
    
    Args:
        today: Date string for output file naming
        search_terms: Dict with search parameters (typically author, title, publication_year)
                     Example: {'author': ['Paula'], 'title': ['Gold nanoparticles'], 'publication_year': ['2015']}
        output_file: Path to write results JSON
        search_field: Which field to search ('all', 'title', 'authors', 'journal', 'year', 'raw')
        expected_results: Optional dict with expected entity_count, citation_count, and entities
                         Example: {'entity_count': 6, 'citation_count': 8, 'entities': {'aop_ids': [23, 25]}}
    
    Returns:
        A dictionary of matching references with associated entity information.
    """
    structured_references = _load_structured_references(today)
    
    # Perform search
    matched_content, term_type_map = _perform_search(structured_references, search_terms, search_field)
    
    # Validate against expected results if provided
    if expected_results:
        _validate_search_results(matched_content, expected_results, search_terms)
    
    # Only export if there are results
    if matched_content:
        # Export results to JSON (convert tuples back to just citations for JSON)
        json_export_data = {}
        for entity_id, data in matched_content.items():
            json_export_data[entity_id] = {
                'entity_type': data['entity_type'],
                'matched_field': data['matched_field'],
                'citations': [c[0] if isinstance(c, tuple) else c for c in data['citations']]
            }
        write_dict_to_json(json_export_data, os.path.dirname(output_file), os.path.basename(output_file))
        
        # Export results to CSV with full parsed structure and term tracking
        csv_output_path = output_file.replace('.json', '.csv')
        export_search_results_to_csv(matched_content, csv_output_path, term_type_map)
        print(f"\n✓ Exported search results to {csv_output_path}")
    else:
        print(f"\n✗ No matching results found - no output files created")
    
    return matched_content

def search_xml_for_multiple_references(today, search_terms_list, output_file):
    """
    Search for multiple sets of search terms and combine results into single output file.
    
    Args:
        today: Date string for output file naming
        search_terms_list: List of dicts with search parameters
        output_file: Path to write combined results
    """
    # Load structured references (collected once and cached)
    structured_references = _load_structured_references(today)
    
    # Perform all searches and combine results
    all_matched_content = {}
    all_term_type_map = {}
    
    for search_params in search_terms_list:
        matched_content, term_type_map = _perform_search(structured_references, search_params['terms'])
        
        # Merge into combined results
        for entity_id, data in matched_content.items():
            if entity_id not in all_matched_content:
                all_matched_content[entity_id] = data
            else:
                # Merge citations from both searches
                all_matched_content[entity_id]['citations'].extend(data['citations'])
        
        all_term_type_map.update(term_type_map)
    
    # Export combined results
    if all_matched_content:
        json_export_data = {}
        for entity_id, data in all_matched_content.items():
            json_export_data[entity_id] = {
                'entity_type': data['entity_type'],
                'matched_field': data['matched_field'],
                'citations': [c[0] if isinstance(c, tuple) else c for c in data['citations']]
            }
        write_dict_to_json(json_export_data, os.path.dirname(output_file), os.path.basename(output_file))
        
        csv_output_path = output_file.replace('.json', '.csv')
        export_search_results_to_csv(all_matched_content, csv_output_path, all_term_type_map)
        print(f"\n✓ Exported combined search results to {csv_output_path}")
    else:
        print(f"\n✗ No matching results found - no output files created")
    
    return all_matched_content