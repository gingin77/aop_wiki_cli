"""
BioPortal ontology search utilities.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

BIOPORTAL_SEARCH_URL = "https://data.bioontology.org/search"
STOPWORDS = {"type", "the", "a", "an", "of", "in", "and", "or", "with", "by"}


# ---------------------------------------------------------------------------
# BioPortal search
# ---------------------------------------------------------------------------

def normalize_phrase(phrase: str) -> str:
    tokens = [t for t in phrase.split() if t.lower() not in STOPWORDS]
    return " ".join(tokens)


def _iri_prefix(iri: str) -> str:
    """
    Extract the ontology prefix from a BioPortal term IRI.

    Handles:
      - OBO PURL, numeric local id:       '.../obo/GO_0042921'            → 'GO'
      - OBO PURL, UniProt-style local id: '.../obo/PR_Q16236'             → 'PR'
        (species-specific Protein Ontology terms use a letter+digits local
        id, which the old digits-only pattern missed and silently dropped)
      - CURIE-tailed IRI (e.g. HGNC):     '.../hgnc_id/HGNC:7782'         → 'HGNC'
    Falls back to empty string when no prefix can be determined.
    """
    # OBO PURL: PREFIX before '_', local id may be digits or alphanumerics.
    m = re.search(r"/([A-Za-z]+)_[A-Za-z0-9]+$", iri)
    if m:
        return m.group(1).upper()
    # CURIE-style tail, e.g. genenames '.../HGNC:7782'.
    m = re.search(r"([A-Za-z]+):[A-Za-z0-9]+$", iri)
    if m:
        return m.group(1).upper()
    return ""


def search_bioportal(phrase: str, ontologies: str, api_key: str) -> list:
    """Search BioPortal for ontology terms matching a phrase."""
    params = urllib.parse.urlencode({
        "q": phrase,
        "ontologies": ontologies,
        "require_exact_match": "false",
        "include": "prefLabel,synonym",
        "pagesize": 10,
        "apikey": api_key,
    })
    req = urllib.request.Request(
        f"{BIOPORTAL_SEARCH_URL}?{params}",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        print(f"  BioPortal search failed for {phrase!r}: {e}")
        return []

    results = []
    for item in data.get("collection", []):
        term_id = item.get("@id", "")
        results.append({
            "ontology": _iri_prefix(term_id),
            "term_id": term_id,
            "label": item.get("prefLabel", ""),
            "synonyms": item.get("synonym", []),
        })
    return results


def search_bioportal_with_fallback(phrase: str, ontologies: str, api_key: str) -> tuple[list, str]:
    """
    Search BioPortal with progressive fallback:
      1. Full phrase
      2. Normalized phrase (stopwords removed)
      3. Noun phrase after 'of'
    Returns (results, query_used).
    """
    results = search_bioportal(phrase, ontologies, api_key)
    if results:
        return results, phrase

    normalized = normalize_phrase(phrase)
    if normalized != phrase:
        results = search_bioportal(normalized, ontologies, api_key)
        if results:
            return results, f"{normalized!r} (stopwords removed)"

    of_match = re.search(r'\bof\s+(.+)$', phrase, re.IGNORECASE)
    if of_match:
        noun_phrase = normalize_phrase(of_match.group(1).strip())
        results = search_bioportal(noun_phrase, ontologies, api_key)
        if results:
            return results, f"{noun_phrase!r} (noun phrase fallback)"

    return [], phrase

