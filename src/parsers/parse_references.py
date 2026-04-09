"""
Parse structured citations from references JSON using BeautifulSoup.

This module handles the extraction and parsing of citation data from HTML-formatted
reference content. It provides functions to:
- Extract individual citations from HTML
- Parse citation details (year, authors, title, journal, DOI, URLs)
- Convert raw references into structured format

For searching citations, see scripts/search_references.py
For exporting search results, see scripts/export_reference_search_results.py
"""

import json
from bs4 import BeautifulSoup
from typing import Dict, List, Tuple


def parse_references_json(json_path: str) -> Dict:
    """Load references JSON file."""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_citations(html_content: str) -> List[str]:
    """Extract individual citations from HTML content.
    
    Searches for citations in:
    - <p> (paragraph) tags
    - <li> (list item) tags
    - Other text elements with citation patterns
    """
    if not html_content:
        return []
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    citations = []
    
    # Extract from <p> tags
    paragraphs = soup.find_all('p')
    for para in paragraphs:
        text = para.get_text(strip=True)
        if text:
            citations.append(text)
    
    # Extract from <li> tags (list items)
    list_items = soup.find_all('li')
    for li in list_items:
        text = li.get_text(strip=True)
        if text and text not in citations:  # Avoid duplicates
            citations.append(text)
    
    return citations


def extract_authors_and_year(citation: str) -> Tuple[str, str]:
    """
    Extract author(s) and year from citation text.
    Handles patterns like "Author, A. (2020)" or "Author A, Author B. 2020."
    """
    import re
    
    # Try to find year in parentheses: (YYYY)
    year_match = re.search(r'\((\d{4})\)', citation)
    if not year_match:
        # Try to find year at end: YYYY.
        year_match = re.search(r'(\d{4})\.?$', citation)
    
    year = year_match.group(1) if year_match else 'N/A'
    
    # Extract first author (everything before first comma or period)
    first_part = citation.split(',')[0].split('.')[0].strip()
    authors = first_part if first_part else 'N/A'
    
    return authors, year


def parse_citation_details(citation: str) -> Dict:
    """
    Parse structured details from a citation.
    Extracts: year, links (DOI, URLs), authors, title, journal, other info.
    
    Handles formats including:
    - OECD (2012), Test No. 229: Fish Short Term Reproduction Assay, OECD Publishing, Paris. DOI: ...
    - Standard author citations: Author, A. (2020). Title. Journal, 1, 1-10.
    
    Args:
        citation: Full citation text
    
    Returns:
        Dict with structured citation components
    """
    import re
    
    result = {
        'raw_citation': citation,
        'year': 'N/A',
        'authors': [],
        'title': '',
        'journal': '',
        'links': {
            'doi': None,
            'urls': []
        },
        'other_info': ''
    }
    
    # Track what we've extracted to remove from remaining text
    extracted_parts = []
    
    # Extract year
    year_match = re.search(r'\((\d{4})\)', citation)
    if not year_match:
        year_match = re.search(r'(?:^|\s)(\d{4})(?:[a-z])?(?:\s|\.)', citation)
    if year_match:
        result['year'] = year_match.group(1)
        extracted_parts.append(year_match.group(0))
    
    # Extract DOI
    doi_match = re.search(r'(?:doi:?\s*)?(?:https?://doi\.org/)?(?:DOI:?\s*)?([0-9.]+/[^\s\)]+)', citation, re.IGNORECASE)
    if doi_match:
        result['links']['doi'] = doi_match.group(1)
        extracted_parts.append(doi_match.group(0))
    
    # Extract all URLs
    url_pattern = r'https?://[^\s\)>\]<"]+'
    urls = re.findall(url_pattern, citation)
    if urls:
        result['links']['urls'] = list(set(urls))  # Remove duplicates
        for url in urls:
            extracted_parts.append(url)
    
    # SPECIAL HANDLING for OECD format
    # Patterns: 
    # - OECD (YYYY), Test No. XXX: [Title], OECD Publishing, [Location]. DOI: ...
    # - 1. OECD. YYYY. Test No. XXX: [Title], [Location]: OECD Publishing
    oecd_match = re.search(r'\bOECD\b', citation)
    if oecd_match:
        # Check if this looks like an OECD citation (has OECD and Test No.)
        test_no_match = re.search(r'Test No\.\s*\d+', citation, re.IGNORECASE)
        if test_no_match:
            # This is an OECD format citation
            result['authors'] = ['OECD']
            extracted_parts.append('OECD')
            
            # Extract title from "Test No. XXX: Title" format
            title_match = re.search(r'Test No\.\s*\d+:\s*([^,]+)', citation, re.IGNORECASE)
            if title_match:
                result['title'] = title_match.group(1).strip()
                extracted_parts.append(title_match.group(0))
            
            # Extract publisher/journal info
            pub_match = re.search(r'OECD Publishing', citation)
            if pub_match:
                result['journal'] = 'OECD Publishing'
                extracted_parts.append('OECD Publishing')
    else:
        # Standard author extraction for non-OECD citations
        # Look for pattern: "Author1, A. and Author2, B."
        author_pattern = r'^([^(]*?)(?=\s*[\(\[]?(?:\d{4}|In|in|Journal|journal|Test))'
        author_section_match = re.match(author_pattern, citation)
        if author_section_match:
            author_section = author_section_match.group(1)
            # Split by common separators
            author_parts = re.split(r'(?:\sand\s|&|,)', author_section)
            for part in author_parts:
                part = part.strip()
                if part and len(part) > 2 and not any(skip in part for skip in ['available', 'Retrieved']):
                    result['authors'].append(part)
                    extracted_parts.append(part)
            result['authors'] = result['authors'][:10]  # Limit to 10
        
        # Extract title (in quotes or between specific markers)
        quote_match = re.search(r'["\']([^"\']{10,})["\']', citation)
        if quote_match:
            result['title'] = quote_match.group(1)
            extracted_parts.append(quote_match.group(0))
        else:
            # Try to find sentence-like patterns between author and journal
            title_pattern = r'(?:^[^.]*?\.?\s+)?([A-Z][^.]{10,}?)(?:\s+(?:Journal|in|In|Environ|Toxicol|Rev|Sci|Nature|Science))'
            title_match = re.search(title_pattern, citation)
            if title_match:
                result['title'] = title_match.group(1).strip('.,')
                extracted_parts.append(title_match.group(1))
        
        # Extract journal (improved patterns)
        journal_patterns = [
            r'(?:(?:Journal|journal|Journal of|journal of)\s+([A-Za-z\s&]+?))\s*(?:\.|,)',
            r'(?:in\s+)([A-Z][a-z\s&]+?)(?:\s+(?:\d{4}|Vol\.|volume|no\.|pp\.))',
            r'([A-Z][a-z\s]+(?:Journal|Review|Proceedings|Letters|Science|Nature|Toxicology|Environmental)[\w\s&]*?)\s*[.,:\s]',
        ]
        for pattern in journal_patterns:
            journal_match = re.search(pattern, citation)
            if journal_match:
                result['journal'] = journal_match.group(1).strip()
                extracted_parts.append(journal_match.group(1))
                break
    
    # Build remaining text by removing all extracted parts
    remaining = citation
    for part in extracted_parts:
        # Remove the part, handling case-insensitive matches
        remaining = re.sub(re.escape(part), '', remaining, flags=re.IGNORECASE)
    
    # Clean up remaining text (remove extra whitespace, punctuation)
    remaining = re.sub(r'\s+', ' ', remaining).strip()
    remaining = remaining.strip('.,;: ')
    result['other_info'] = remaining[:150] if remaining else ''
    
    return result


def process_all_references(data: Dict, entity_type: str = 'AOP') -> List[Dict]:
    """
    Process all references for a given entity type.
    
    Args:
        data: Dict of entity references (either full nested dict or entity-specific dict)
        entity_type: 'AOP', 'KE', or 'KER'
    
    Returns:
        List of dicts with: entity_id, citation_count, citations (list)
    """
    # If data has entity_type as a key, extract that; otherwise use data directly
    if entity_type in data:
        entity_data = data[entity_type]
    else:
        entity_data = data
    
    results = []
    
    for entity_id, html_content in sorted(entity_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        citations = extract_citations(html_content)
        
        result = {
            'entity_type': entity_type,
            'entity_id': entity_id,
            'citation_count': len(citations),
            'citations': citations
        }
        results.append(result)
    
    return results


def get_structured_references(raw_references: Dict, entity_type: str = 'AOP') -> Dict[str, Dict]:
    """
    Unified entry point: Convert raw references into fully parsed, structured format.
    
    Takes references from collect_references_from_aops_kers_and_events() and returns
    a structured dictionary ready for searching and exporting.
    
    Args:
        raw_references: Dict from collect_references_from_aops_kers_and_events() with format:
                       {entity_type: {entity_id: html_content}}
        entity_type: 'AOP', 'KE', or 'KER'
    
    Returns:
        Dict structure:
        {
            entity_id: {
                'citation_count': int,
                'citations': [
                    {
                        'raw_citation': str,
                        'year': str,
                        'authors': [str],
                        'title': str,
                        'journal': str,
                        'links': {'doi': str, 'urls': [str]},
                        'other_info': str
                    },
                    ...
                ]
            },
            ...
        }
    """
    # Extract the entity-specific data
    if entity_type in raw_references:
        entity_data = raw_references[entity_type]
    else:
        entity_data = raw_references
    
    structured = {}
    
    for entity_id, html_content in sorted(entity_data.items(), 
                                         key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        # Extract raw citations from HTML
        citations = extract_citations(html_content)
        
        # Parse each citation into structured format
        parsed_citations = []
        for citation in citations:
            parsed = parse_citation_details(citation)
            parsed_citations.append(parsed)
        
        structured[entity_id] = {
            'citation_count': len(parsed_citations),
            'citations': parsed_citations
        }
    
    return structured


if __name__ == '__main__':
    # Example usage:
    # python scripts/parse_references.py
    
    # Load the references JSON
    refs = parse_references_json("outputs/search_results/references_2024-01-15.json")
    
    # Extract structured references
    structured = get_structured_references(refs, entity_type='KER')
    
    print(f"Processed {len(structured)} KERs")
    for entity_id, data in list(structured.items())[:3]:
        print(f"\nKER {entity_id}: {data['citation_count']} citations")
        for citation in data['citations'][:2]:
            print(f"  - {citation['year']} | {citation['authors'][:2]} | {citation['title'][:50]}...")
