"""
Search functions for finding citations in structured reference data.
Provides flexible search capabilities across different citation fields.
"""

from typing import Dict, List, Tuple


def search_citations_cross_field(structured_refs: Dict[str, Dict], 
                                 search_criteria: Dict[str, List[str]]) -> Dict[str, List[Tuple[Dict, str]]]:
    """
    Search for citations matching criteria across multiple fields.
    
    Finds citations that match ALL specified field criteria (AND operation across fields).
    Used to identify specific publications by combining year + author + title, etc.
    
    Args:
        structured_refs: Dict from get_structured_references() with entity_id as keys
        search_criteria: Dict with field names as keys and term lists as values.
                        Valid fields: 'year', 'author'/'authors', 'title', 'journal'
                        Example: {'year': ['2023'], 'author': ['Paul'], 'title': ['iPSC']}
    
    Returns:
        Dict with structure:
        {
            entity_id: [
                (citation_object, matched_criteria_string),  # e.g., "2023 + Paul + iPSC"
                ...
            ],
            ...
        }
    """
    results = {}
    
    # Normalize field names in search_criteria
    normalized_criteria = {}
    for field_key, terms in search_criteria.items():
        # Map aliases to standard field names
        field_mapping = {
            'publication_year': 'year',
            'year': 'year',
            'authors': 'authors',
            'author': 'authors',
            'title': 'title',
            'journal': 'journal'
        }
        normalized_field = field_mapping.get(field_key, field_key)
        normalized_criteria[normalized_field] = terms
    
    for entity_id, entity_data in structured_refs.items():
        citations = entity_data.get('citations', [])
        matching_citations = []
        
        for citation in citations:
            # Check if citation matches ALL criteria
            matched_parts = []
            matches_all_criteria = True
            
            for field, search_terms in normalized_criteria.items():
                field_matched = False
                matched_term = None
                
                if field == 'year':
                    # Match year field
                    citation_year = citation.get('year', '').lower()
                    for term in search_terms:
                        if term.lower() in citation_year:
                            field_matched = True
                            matched_term = term
                            break
                
                elif field == 'authors':
                    # Match in authors list
                    citation_authors = [a.lower() for a in citation.get('authors', [])]
                    for term in search_terms:
                        term_lower = term.lower()
                        for author in citation_authors:
                            if term_lower in author:
                                field_matched = True
                                matched_term = term
                                break
                        if field_matched:
                            break
                
                elif field == 'title':
                    # Match in title
                    citation_title = citation.get('title', '').lower()
                    for term in search_terms:
                        if term.lower() in citation_title:
                            field_matched = True
                            matched_term = term
                            break
                
                elif field == 'journal':
                    # Match in journal
                    citation_journal = citation.get('journal', '').lower()
                    for term in search_terms:
                        if term.lower() in citation_journal:
                            field_matched = True
                            matched_term = term
                            break
                
                # If this field didn't match, criteria not satisfied
                if not field_matched:
                    matches_all_criteria = False
                    break
                
                if matched_term:
                    matched_parts.append(matched_term)
            
            # If all criteria matched, add to results
            if matches_all_criteria and matched_parts:
                matched_criteria_str = ' + '.join(matched_parts)
                matching_citations.append((citation, matched_criteria_str))
        
        if matching_citations:
            results[entity_id] = matching_citations
    
    return results


def search_citations_by_combination(structured_refs: Dict[str, Dict], 
                                   search_terms: List[str], 
                                   field: str = 'all',
                                   min_matches: int = 2) -> Dict[str, List[Tuple[Dict, str]]]:
    """
    Search for citations containing multiple terms from a list (combination search).
    
    Finds citations that contain at least min_matches number of terms from search_terms.
    
    Args:
        structured_refs: Dict from get_structured_references() with entity_id as keys
        search_terms: List of terms to search for
        field: Which field to search in ('all', 'title', 'authors', 'journal', 'year', 'raw')
        min_matches: Minimum number of terms that must match (default: 2)
    
    Returns:
        Dict with structure:
        {
            entity_id: [
                (citation_object, matched_terms_string),  # e.g., "Parkinson + iPSC"
                ...
            ],
            ...
        }
    """
    results = {}
    
    for entity_id, entity_data in structured_refs.items():
        citations = entity_data.get('citations', [])
        matching_citations = []
        
        for citation in citations:
            # Build search text based on field parameter
            search_texts = []
            
            if field == 'all':
                search_texts = [
                    citation.get('raw_citation', ''),
                    ' '.join(citation.get('authors', [])),
                    citation.get('title', ''),
                    citation.get('journal', ''),
                ]
            elif field == 'title':
                search_texts = [citation.get('title', '')]
            elif field == 'authors':
                search_texts = citation.get('authors', [])
            elif field == 'journal':
                search_texts = [citation.get('journal', '')]
            elif field == 'year':
                search_texts = [citation.get('year', '')]
            elif field == 'raw':
                search_texts = [citation.get('raw_citation', '')]
            
            # Combine all search texts for matching
            combined_text = ' '.join(search_texts).lower()
            
            # Find all matching terms
            matched_terms = []
            for term in search_terms:
                if term.lower() in combined_text:
                    matched_terms.append(term)
            
            # If at least min_matches terms are found, add to results
            if len(matched_terms) >= min_matches:
                matched_term_str = ' + '.join(matched_terms)
                matching_citations.append((citation, matched_term_str))
        
        if matching_citations:
            results[entity_id] = matching_citations
    
    return results


def _match_term_flexible(term: str, search_texts: List[str]) -> bool:
    """
    Match a term against search texts with adaptive word matching.
    
    For single-word terms: exact substring match
    For multi-word phrases: match if 70%+ of words are found in the text
    (e.g., 4 out of 5 words for "Fish Short Term Reproduction Assay")
    
    Handles hyphenated variants: "short-term" matches "short term" and vice versa
    
    Args:
        term: Search term (can be single or multi-word)
        search_texts: List of texts to search in
    
    Returns:
        True if term matches (via exact substring or 70% word match), False otherwise
    """
    combined_text = ' '.join(search_texts).lower()
    term_lower = term.lower()
    
    # Normalize hyphens to spaces for matching (short-term → short term)
    normalized_text = combined_text.replace('-', ' ')
    normalized_term = term_lower.replace('-', ' ')
    
    # Try exact substring match first (on normalized text)
    if normalized_term in normalized_text:
        return True
    
    # For multi-word phrases, require 70% of words (at least 4 out of 5, 3 out of 4, etc.)
    words = normalized_term.split()
    if len(words) > 1:
        # Count how many words from the phrase are in the text
        matched_words = sum(1 for word in words if word in normalized_text)
        # Require 70% match minimum (rounded up)
        min_word_matches = max(2, (len(words) * 7 + 9) // 10)  # 70% rounded up
        if matched_words >= min_word_matches:
            return True
    
    return False


def search_citations_by_field(structured_refs: Dict[str, Dict], 
                              search_terms: List[str], 
                              field: str = 'all') -> Dict[str, List[Tuple[Dict, str]]]:
    """
    Search structured citations by specific field with flexible matching.
    
    Enables precise searching across citation components with flexible word-by-word matching
    for multi-word phrases.
    
    Args:
        structured_refs: Dict from get_structured_references() with entity_id as keys
        search_terms: List of terms to search for
        field: Which field to search in:
               - 'all': Search across raw_citation, authors, title, journal (default)
               - 'title': Search only in title field
               - 'authors': Search only in authors list
               - 'journal': Search only in journal field
               - 'year': Search only in year field
               - 'raw': Search only in raw_citation field
    
    Returns:
        Dict with structure:
        {
            entity_id: [
                (citation_object, matched_term_string),
                ...
            ],
            ...
        }
    """
    results = {}
    
    for entity_id, entity_data in structured_refs.items():
        citations = entity_data.get('citations', [])
        matching_citations = []
        
        for citation in citations:
            # Build search text based on field parameter
            search_texts = []
            
            if field == 'all':
                search_texts = [
                    citation.get('raw_citation', ''),
                    ' '.join(citation.get('authors', [])),
                    citation.get('title', ''),
                    citation.get('journal', ''),
                ]
            elif field == 'title':
                title = citation.get('title', '')
                search_texts = [title]
                # If title is empty or very short (< 5 chars), also search raw citation
                if len(title) < 5:
                    search_texts.append(citation.get('raw_citation', ''))
            elif field == 'authors':
                search_texts = citation.get('authors', [])
            elif field == 'journal':
                search_texts = [citation.get('journal', '')]
            elif field == 'year':
                search_texts = [citation.get('year', '')]
            elif field == 'raw':
                search_texts = [citation.get('raw_citation', '')]
            
            # Search for any term in the selected field(s) using flexible matching
            matched_term = None
            for term in search_terms:
                if _match_term_flexible(term, search_texts):
                    matched_term = term
                    break
            
            if matched_term:
                matching_citations.append((citation, matched_term))
        
        if matching_citations:
            results[entity_id] = matching_citations
    
    return results
