"""
BioPortal ontology search utilities.
"""

import json
import re
import urllib.parse
import urllib.request
import urllib.error

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
    Extract the true ontology prefix from an OBO IRI.
    e.g. 'http://purl.obolibrary.org/obo/GO_0042921' → 'GO'
    Falls back to empty string for non-OBO IRIs.
    """
    m = re.search(r"/([A-Z]+)_\d+$", iri)
    return m.group(1) if m else ""


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
    except urllib.error.HTTPError as e:
        print(f"  BioPortal HTTP error {e.code}: {e.reason} — returning empty results.")
        return []
    except urllib.error.URLError as e:
        print(f"  BioPortal connection error: {e.reason} — returning empty results.")
        return []
    except TimeoutError:
        print("  BioPortal request timed out — returning empty results.")
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

