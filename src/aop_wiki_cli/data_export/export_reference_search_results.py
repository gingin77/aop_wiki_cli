"""
Export functions for reference search results.
Handles JSON and CSV export formats with structured citation data.
"""

import json
import csv
from typing import Dict, List


def export_structured_json(results: List[Dict], output_path: str, parse_citation_details):
    """
    Export parsed citations as structured JSON.
    
    Args:
        results: List of results with entity_type, entity_id, and citations
        output_path: Path to write JSON file
        parse_citation_details: Function to parse citation details (from parse_references module)
    """
    structured = {}
    
    for result in results:
        entity_type = result['entity_type']
        entity_id = result['entity_id']
        
        if entity_type not in structured:
            structured[entity_type] = {}
        
        citations_parsed = []
        for citation in result['citations']:
            parsed = parse_citation_details(citation)
            citations_parsed.append(parsed)
        
        structured[entity_type][entity_id] = {
            'citation_count': len(citations_parsed),
            'citations': citations_parsed
        }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(structured, f, indent=2, ensure_ascii=False)


def export_summary(results: List[Dict], output_path: str):
    """
    Export summary of citation counts per entity.
    
    Args:
        results: List of results with entity_type, entity_id, and citation_count
        output_path: Path to write CSV file
    """
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Entity_Type', 'Entity_ID', 'Citation_Count'])
        
        for result in results:
            writer.writerow([
                result['entity_type'],
                result['entity_id'],
                result['citation_count']
            ])


def export_search_results_to_csv(search_results: Dict[str, Dict], output_path: str, term_type_map: Dict[str, str] = None):
    """
    Export search results with full parsed citation structure to CSV.
    Only creates the CSV file if there are results to export.
    
    Args:
        search_results: Dict from search_xml_for_references() with structure:
                       {entity_id: {entity_type, matched_field, citations: [...]}}
        output_path: Path to write CSV file
        term_type_map: Optional dict mapping search terms to their types (year/author/phrase)
    """
    if term_type_map is None:
        term_type_map = {}
    
    # Skip if no results to export
    if not search_results:
        return
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        
        # Header row with new format
        writer.writerow([
            'Matched_Term', 'Term_Type', 'Entity', 'Year', 'Authors', 'Title', 'Journal', 'DOI',
            'URLs', 'Other_Info', 'Citation_Index', 'Raw_Citation', 
        ])
        
        # Data rows
        for entity_id in sorted(search_results.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            entity_data = search_results[entity_id]
            entity_type = entity_data.get('entity_type', 'N/A')
            matched_field = entity_data.get('matched_field', 'all')
            citations = entity_data.get('citations', [])
            
            for idx, citation_info in enumerate(citations, 1):
                # Handle both old format (just citation) and new format (citation, matched_term)
                if isinstance(citation_info, tuple):
                    citation, matched_term = citation_info
                else:
                    citation = citation_info
                    matched_term = 'N/A'
                
                # Determine term type from map or matched_field
                term_type = term_type_map.get(matched_term, matched_field if matched_field != 'all' else 'phrase')
                
                # Combine Entity_Type and Entity_ID into single column
                entity_combined = f"{entity_type} {entity_id}"
                
                author_str = '; '.join(citation.get('authors', [])) if citation.get('authors') else ''
                url_str = '; '.join(citation.get('links', {}).get('urls', [])) if citation.get('links', {}).get('urls') else ''
                
                writer.writerow([
                    matched_term,
                    term_type,
                    entity_combined,
                    citation.get('year', ''),
                    author_str,
                    citation.get('title', ''),
                    citation.get('journal', ''),
                    citation.get('links', {}).get('doi', ''),
                    url_str,
                    citation.get('other_info', ''),
                    idx,
                    citation.get('raw_citation', ''),
                ])
