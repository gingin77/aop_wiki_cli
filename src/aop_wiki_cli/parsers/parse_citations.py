# Citation parsing and grouping utilities
# Run with: `uv run python -m src.parsers.parse_citations`

import re
from collections import defaultdict


def normalize_citation_string(citation_string):
    """
    Normalize a citation string (strip whitespace).
    
    Treats each citation string as a single unit without splitting.
    """
    if not isinstance(citation_string, str):
        return None
    return citation_string.strip() if citation_string.strip() else None


def extract_citation_base(citation):
    """Extract the base form of a citation (without page numbers, for grouping)."""
    if not isinstance(citation, str):
        return None
    
    # Remove page numbers like "p. 123", "p. 123-4", "p. 123-456"
    base = re.sub(r',?\s*p\.\s*\d+[-–]?\d*', '', citation)
    
    # Normalize whitespace
    base = re.sub(r'\s+', ' ', base).strip()
    
    # Remove trailing punctuation
    base = base.rstrip('.,;')
    
    return base


def extract_url(citation):
    """Extract URL from a citation string."""
    if not isinstance(citation, str):
        return None
    # Match http://, https://, or www. URLs
    match = re.search(r'(https?://[^\s]+|www\.[^\s]+)', citation)
    return match.group(1) if match else None


def extract_year(citation):
    """Extract publication year (4-digit year 19xx or 20xx) from a citation string."""
    if not isinstance(citation, str):
        return None
    # Look for 4-digit years, prefer the last one found (typically publication year)
    years = re.findall(r'\b(19\d{2}|20\d{2})\b', citation)
    return years[-1] if years else None


def extract_authors(citation):
    """
    Extract author names from a citation string.
    
    Handles patterns:
    - "Author et al. YYYY" or "Author et al YYYY"
    - "LastName, F.I., LastName, F.I. (Eds).;" (before semicolon)
    - "LastName, F.I., LastName, F.I.;" (before semicolon)
    
    Note: Agency abbreviations (ATSDR, EPA, etc.) are handled by extract_organization()
    
    Returns:
        str: Extracted author string, or None if not found
    """
    if not isinstance(citation, str):
        return None
    
    citation = citation.strip()
    
    # Pattern 1: Short "Author et al. YYYY" format
    match = re.match(r'^([A-Z][a-z]+\s+et\s+al\.?)\s+\d{4}', citation)
    if match:
        return match.group(1).rstrip('.')
    
    # Skip agency abbreviations - those go in organization field
    if re.match(r'^[A-Z]{2,10}\s*[-–]\s*', citation):
        return None
    
    # Pattern 2: Authors before semicolon (common book format)
    # "LastName, F.I., LastName, F.I. (Eds).;"
    semicolon_pos = citation.find(';')
    if semicolon_pos > 0:
        before_semi = citation[:semicolon_pos].strip()
        # Remove trailing "(Eds)." or "(Ed.)."
        before_semi = re.sub(r'\s*\(Eds?\.?\)\.?\s*$', '', before_semi)
        # If it looks like author names (has commas and initials)
        if re.search(r'[A-Z][a-z]+,\s*[A-Z]\.', before_semi):
            return before_semi
    
    # Pattern 3: Authors before period followed by title-like text
    # "LastName, A.B., LastName, C.D. Title of Book."
    match = re.match(r'^([A-Z][a-z]+(?:,\s*[A-Z]\.?[A-Z]?\.?)?(?:[,;]\s*(?:and\s+)?[A-Z][a-z]+(?:,\s*[A-Z]\.?[A-Z]?\.?)?)*)', citation)
    if match:
        authors = match.group(1).strip()
        # Only return if it's substantial and looks like authors
        if len(authors) > 3 and ',' in authors:
            return authors.rstrip(',;')
    
    return None


def extract_title(citation):
    """
    Extract publication title from a citation string.
    
    Handles patterns:
    - Known source phrases from CITATION_GROUP_PHRASES
    - Journal articles: "Author et al. Title. Journal YYYY;..."
    - Books after semicolon: "Authors (Eds).; Title. Edition..."
    - Agency reports: "Org (YYYY). Title." or "Org. YYYY. Title."
    
    Returns:
        str: Extracted title, or None if not found
    """
    if not isinstance(citation, str):
        return None
    
    # First, check for known source phrases
    matched_phrase = match_known_source_phrase(citation)
    if matched_phrase:
        return matched_phrase
    
    # Pattern 1: Journal article - "Author et al. Title. Journal YYYY;..."
    # e.g., "Das R et al. Worker Illness Related to... California. MMWR 2006;55(17):486-8"
    match = re.match(r'^[A-Z][a-z]+\s+[A-Z]?\s*et\s+al\.?\s+(.+?)\.\s+[A-Z]{2,}', citation)
    if match:
        title = match.group(1).strip()
        if len(title) > 5:
            return title
    
    # Pattern 2: After semicolon, before edition/publisher markers (books)
    # e.g., "Authors (Eds).; Emergency Care For Hazardous Materials Exposure. 3rd revised edition..."
    # Handles: "3rd edition", "3rd revised edition", "2nd ed.", "2nd ed"
    # But skip if after semicolon looks like another author citation (e.g., "Fan et al. 2019")
    semicolon_pos = citation.find(';')
    if semicolon_pos > 0:
        after_semi = citation[semicolon_pos + 1:].strip()
        # Skip if this looks like another author-year citation (not a book title)
        if re.match(r'^[A-Z][a-z]+\s+(et\s+al|[A-Z])', after_semi):
            pass  # Don't extract title from author-style text
        else:
            # Extract title before edition markers (allowing words like "revised" between ordinal and ed/edition)
            match = re.match(r'^([^.]+?)\.(?:\s+\d+(?:st|nd|rd|th)?(?:\s+\w+)*\s*(?:ed\.?|edition)|.*?\d{4})', after_semi, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if len(title) > 5:
                    return title
    
    # Pattern 3: Agency report - "Organization (YYYY). Title."
    # e.g., "ATSDR... (1997). Toxicological profile for chlorpyrifos."
    match = re.search(r'\(\d{4}\)\.\s*([^.]+)', citation)
    if match:
        title = match.group(1).strip()
        if len(title) > 5:
            return title
    
    # Pattern 4: Agency report - "Organization. YYYY. Title."
    # e.g., "U.S. Environmental Protection Agency. 1998. Extremely Hazardous Substances..."
    match = re.search(r'\.\s*\d{4}\.\s*([^.]+)', citation)
    if match:
        title = match.group(1).strip()
        if len(title) > 5:
            return title
    
    return None


def extract_organization(citation):
    """
    Extract organization/agency name from a citation string.
    
    Handles patterns:
    - "Organization Name. YYYY. Title..." → "Organization Name"
    - "ABBREV - Full Organization Name (YYYY)" → "ABBREV - Full Organization Name"
    - "Full Organization Name (ABBREV) OTHER (YYYY)" → "Full Organization Name (ABBREV)"
    
    Returns:
        str: Extracted organization name, or None if not found
    """
    if not isinstance(citation, str):
        return None
    
    citation = citation.strip()
    
    # Pattern 1: "Organization Name. YYYY. Title..."
    # e.g., "U.S. Environmental Protection Agency. 1998. Extremely Hazardous..."
    match = re.match(r'^([A-Z][A-Za-z\.\s]+(?:Agency|Administration|Institute|Organization|Commission|Department|Service|Programme))\.\s*\d{4}\.', citation)
    if match:
        return match.group(1).strip()
    
    # Pattern 2: "ABBREV - Full Organization Name (YYYY)"
    # e.g., "ATSDR - Agency for Toxic Substances and Disease Registry (1997)"
    match = re.match(r'^([A-Z]{2,10}\s*[-–]\s*[^(]+?)\s*\(\d{4}\)', citation)
    if match:
        return match.group(1).strip()
    
    # Pattern 3: "Full Organization Name (ABBREV) SOMETHING (YYYY)"
    # e.g., "International Programme on Chemical Safety (IPCS) INCHEM (1992)"
    # But stop before any year pattern to avoid grabbing title text
    match = re.match(r'^([A-Z][A-Za-z\s]+\([A-Z]{2,10}\))(?:\s+[A-Z]|\s*$)', citation)
    if match:
        return match.group(1).strip()
    
    # Pattern 4: "Organization Name (YYYY)." without abbreviation
    # e.g., "U.S. Environmental Protection Agency (2005)."
    match = re.match(r'^([A-Z][A-Za-z\.\s]+(?:Agency|Administration|Institute|Organization|Commission|Department|Service))\s*\(\d{4}\)', citation)
    if match:
        return match.group(1).strip()
    
    return None


def classify_citation_type(citation):
    """
    Classify citation into types.
    
    Returns one of:
        - 'journal_pmid': Contains PMID reference
        - 'journal_article': Journal-style citation (Author et al, journal name, volume/pages)
        - 'author_year_short': Short "Author et al. YYYY" format
        - 'book': Contains publisher/edition keywords
        - 'agency_report': Government agency reports (ATSDR, EPA)
        - 'database': Primary database reference (e.g., "Database Name; URL")
        - 'other': Unclassified
    """
    if not isinstance(citation, str):
        return 'other'
    
    citation_lower = citation.lower()
    
    # Check for PMID (journal articles)
    if 'pmid' in citation_lower:
        return 'journal_pmid'
    
    # Check for short author-year format: "Author et al. YYYY" or "Author et al YYYY"
    if re.match(r'^[A-Z][a-z]+\s+et\s+al\.?\s+\d{4}$', citation.strip()):
        return 'author_year_short'
    
    # Check for agency reports (before books, as some may have edition-like text)
    if any(kw in citation_lower for kw in ['atsdr', 'toxicological profile', 'u.s. public health service']):
        return 'agency_report'
    
    # Check for books (publishers, editions)
    if any(kw in citation_lower for kw in ['edition', 'ed.', 'publisher', 'mosby', 'mcgraw', 'elsevier']):
        return 'book'
    
    # Check for journal articles (Author et al followed by content, or journal-style formatting)
    if re.match(r'^[A-Z][a-z]+\s+[A-Z]?\s*et\s+al', citation):
        return 'journal_article'
    
    # Check for database references (database name followed by URL, no author-style start)
    if ('http' in citation_lower or 'www.' in citation_lower):
        # Only classify as database if it starts with a database-like name, not author names
        if re.match(r'^[A-Z][a-z]+\s+(and\s+)?[A-Z][a-z]+\s+Database', citation):
            return 'database'
        if 'database' in citation_lower or 'haz-map' in citation_lower:
            return 'database'
    
    return 'other'


def normalize_author_year_citation(citation):
    """Normalize short author-year citations like 'Zhai et al 2022' -> 'Zhai et al. 2022'."""
    # Add period after "et al" if missing
    normalized = re.sub(r'et\s+al\s+(\d{4})', r'et al. \1', citation)
    return normalized.strip()


# Known book/source titles to group by (case-insensitive matching)
# Use "and" form - ampersands will be normalized before matching
CITATION_GROUP_PHRASES = [
    "Emergency Care for Hazardous Materials Exposure",
    "Poisoning and Drug Overdose",
    "Drug Information for the Health Care Professional",
    "Drug Information",
    "Toxicological profile",
    "Documentation of the TLVs and BEIs",
    "Hazardous Substances Data Bank",
    "Haz-Map",
    "Drugs and Lactation Database",
]

# Predefined citation data for known books
EMERGENCY_CARE_BOOK = {
    '2nd': {
        'title': 'Emergency Care for Hazardous Materials Exposure',
        'authors': 'Bronstein, A.C., Currance, P.L.',
        'publisher': 'Mosby Lifeline',
        'citation_type': 'book',
    },
    '3rd': {
        'title': 'Emergency Care for Hazardous Materials Exposure',
        'authors': 'Currance, P.L., Clements, B., Bronstein, A.C.',
        'publisher': 'Elsevier Mosby',
        'citation_type': 'book',
    },
}


def match_emergency_care_book(citation):
    """
    Check if citation is for Emergency Care book and return predefined data.
    
    Returns dict with predefined values if matched, otherwise None.
    """
    if not isinstance(citation, str):
        return None
    
    citation_lower = citation.lower()
    if 'emergency care for hazardous materials exposure' not in citation_lower:
        return None
    
    if '2nd' in citation_lower:
        return EMERGENCY_CARE_BOOK['2nd'].copy()
    if '3rd' in citation_lower:
        return EMERGENCY_CARE_BOOK['3rd'].copy()
    
    return None


def match_known_source_phrase(citation):
    """
    Match citation against known book/source titles.
    
    Returns the matching phrase if found, otherwise None.
    """
    if not isinstance(citation, str):
        return None
    
    # Normalize ampersands to "and" for consistent matching
    citation_normalized = citation.replace('&', 'and')
    citation_lower = citation_normalized.lower()
    
    for phrase in CITATION_GROUP_PHRASES:
        if phrase.lower() in citation_lower:
            return phrase
    
    return None


def parse_citation_string(citation_string):
    """
    Parse a single citation string into a structured dict.
    
    Flow:
    1. Basic cleanup (strip whitespace)
    2. Check for known books with predefined data
    3. Extract discrete components (year, authors, title, organization)
    4. Classify type (book, author_year_short, database_url, etc.)
    
    Args:
        citation_string: Raw citation string from the data
    
    Returns:
        dict with keys: raw, year, url, authors, title, organization, citation_type
        Returns None if citation_string is invalid.
    """
    # 1. Basic cleanup
    normalized = normalize_citation_string(citation_string)
    if not normalized:
        return None
    
    # 2. Check for known books with predefined data
    known_book = match_emergency_care_book(normalized)
    if known_book:
        # Use predefined values, but still extract year from this specific citation
        year = extract_year(normalized)
        return {
            'raw': normalized,
            'year': year,
            'url': None,
            'authors': known_book['authors'],
            'title': known_book['title'],
            'organization': None,
            'citation_type': known_book['citation_type'],
        }
    
    # 3. Extract discrete components
    year = extract_year(normalized)
    url = extract_url(normalized)
    authors = extract_authors(normalized)
    title = extract_title(normalized)
    organization = extract_organization(normalized)
    
    # 4. Classify type
    citation_type = classify_citation_type(normalized)
    
    return {
        'raw': normalized,
        'year': year,
        'url': url,
        'authors': authors,
        'title': title,
        'organization': organization,
        'citation_type': citation_type,
    }


def is_multi_author_citation(citation_string):
    """
    Check if citation string contains multiple semicolon-separated author citations.
    
    Looks for pattern: "Author et al YYYY; Author et al YYYY" or similar.
    Does NOT match book citations (which have semicolons but different structure).
    """
    if not isinstance(citation_string, str):
        return False
    
    # Must have semicolon
    if ';' not in citation_string:
        return False
    
    # Skip book-style citations (semicolon after "(Eds)." or similar)
    if re.search(r'\(Eds?\)\.?\s*;', citation_string):
        return False
    
    # Check if multiple parts look like author-year citations
    parts = [p.strip() for p in citation_string.split(';')]
    author_year_count = 0
    for part in parts:
        # Match "Author et al YYYY" or "Author et al. YYYY" or short name entries
        if re.match(r'^[A-Z][a-z]+\s+(et\s+al\.?\s+\d{4}|[A-Z])', part):
            author_year_count += 1
        # Also match "Name List" style entries like "Neurocrine List"
        elif re.match(r'^[A-Z][a-z]+\s+[A-Z][a-z]+', part):
            author_year_count += 1
    
    return author_year_count >= 2


def parse_citations(citation_string):
    """
    Parse a citation string, handling multi-citation strings.
    
    If the string contains multiple semicolon-separated author citations,
    splits and parses each one individually.
    
    Args:
        citation_string: Raw citation string (may contain multiple citations)
    
    Returns:
        list: Array of parsed citation dicts. Always returns a list.
               Returns empty list if input is invalid.
    """
    if not isinstance(citation_string, str) or not citation_string.strip():
        return []
    
    # Check if this is a multi-citation string
    if is_multi_author_citation(citation_string):
        parts = [p.strip() for p in citation_string.split(';')]
        results = []
        for part in parts:
            if part:
                parsed = parse_citation_string(part)
                if parsed:
                    results.append(parsed)
        return results
    
    # Single citation
    parsed = parse_citation_string(citation_string)
    return [parsed] if parsed else []


def group_citations_by_source(citations_list):
    """
    Group citations by their source (book title, author, etc.).
    
    Uses title or author-based grouping to aggregate variations of the same source.
    
    Args:
        citations_list: List of citation strings
    
    Returns:
        dict: {group_key: [list of full citations]}
    """
    grouped = defaultdict(list)
    
    for citation in citations_list:
        parsed = parse_citation_string(citation)
        if parsed:
            # Use title if available, otherwise use authors, otherwise use raw
            group_key = parsed['title'] or parsed['authors'] or parsed['raw']
            grouped[group_key].append(parsed['raw'])
    
    return dict(grouped)


def group_citations_by_type(citations_list):
    """
    Group citations by their classified type.
    
    Args:
        citations_list: List of citation strings
    
    Returns:
        dict: {type: [list of citations]}
    """
    by_type = defaultdict(list)
    
    for citation in citations_list:
        normalized = normalize_citation_string(citation)
        if normalized:
            ctype = classify_citation_type(normalized)
            by_type[ctype].append(normalized)
    
    return dict(by_type)


def build_citation_summary(citations_list):
    """
    Build a structured summary of all citations.
    
    Args:
        citations_list: List of raw citation strings from the source data
    
    Returns:
        dict: {
            'by_type': {type: [citations]},
            'by_source': {source_key: [all citation variants]},
            'sources_with_variants': {source: [citations]} for sources with >1 citation,
            'unique_sources': int,
            'total_citations': int,
            'total_raw': int
        }
    """
    all_normalized = []
    for citation in citations_list:
        normalized = normalize_citation_string(citation)
        if normalized:
            all_normalized.append(normalized)
    
    # Group by type
    by_type = group_citations_by_type(citations_list)
    
    # Group by source (using phrase matching)
    by_source = group_citations_by_source(citations_list)
    
    # Find sources with multiple citation variants
    sources_with_variants = {
        source: cites for source, cites in by_source.items() 
        if len(cites) > 1
    }
    
    return {
        'by_type': by_type,
        'by_source': by_source,
        'sources_with_variants': sources_with_variants,
        'unique_sources': len(by_source),
        'total_citations': len(all_normalized),
        'total_raw': len(citations_list)
    }


def process_literature_citations(literature_cited_set):
    """
    Process and structure the literature citations for summary analysis.
    
    This provides an overview of citation patterns across all chemicals.
    For per-chemical citation parsing, use parse_citation_string() instead.
    
    Args:
        literature_cited_set: Set or list of citation strings
    
    Returns:
        dict: Full citation summary with groupings and statistics
    """
    summary = build_citation_summary(list(literature_cited_set))
    
    print(f"\n📚 Citation Summary:")
    print(f"  Total unique citations: {len(literature_cited_set)}")
    print(f"  Unique sources: {summary['unique_sources']}")
    
    print(f"\n📖 Citations by type:")
    for ctype, cites in summary['by_type'].items():
        print(f"  {ctype}: {len(cites)}")
    
    if summary['sources_with_variants']:
        print(f"\n📄 Sources cited multiple times ({len(summary['sources_with_variants'])}):")
        for source, variants in sorted(summary['sources_with_variants'].items(), key=lambda x: -len(x[1])):
            print(f"  '{source}': {len(variants)} citations")
    
    return summary


# ============================================================================
# Demo/Testing
# ============================================================================

if __name__ == '__main__':
    # Test with sample citations including multiple editions of same source
    sample_citations = [
        "Currance, P.L. Clements, B., Bronstein, A.C. (Eds).; Emergency Care For Hazardous Materials Exposure. 3Rd edition, Elsevier Mosby, St. Louis, MO 2005, p. 364-5",
        "Currance, P.L. Clements, B., Bronstein, A.C. (Eds).; Emergency Care For Hazardous Materials Exposure. 3rd revised edition, Elsevier Mosby, St. Louis, MO 2007, p. 241-2",
        "Bronstein, A.C., P.L. Currance; Emergency Care for Hazardous Materials Exposure. 2nd ed. St. Louis, MO. Mosby Lifeline. 1994., p. 200-01",
        "Zhai et al 2022",
        "Zhai et al 2023",
        "Bradley et al. 2018; Ishibashi et al. 2021; Matsuda et al. 2022",
        "ATSDR - Agency for Toxic Substances and Disease Registry (2002). Toxicological profile for methoxychlor.",
        "Drugs and Lactation Database (LactMed); https://www.ncbi.nlm.nih.gov/books/n/lactmed/LM367/",
        "Olson, K.R. (Ed.); Poisoning & Drug Overdose. 5th ed. Lange Medical Books/McGraw-Hill. New York, N.Y. 2007., p. 187",
        "Olson, K.R. (ed.) Poisoning & Drug Overdose. 3rd edition. Lange Medical Books/McGraw-Hill, New York, NY. 1999., p. 75",
    ]
    
    summary = process_literature_citations(sample_citations)
