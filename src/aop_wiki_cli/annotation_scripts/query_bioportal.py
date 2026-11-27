"""
BioPortal ontology search utilities.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

BIOPORTAL_SEARCH_URL = "https://data.bioontology.org/search"
BIOPORTAL_ONTOLOGY_URL = "https://data.bioontology.org/ontologies"
STOPWORDS = {"type", "the", "a", "an", "of", "in", "and", "or", "with", "by"}

# Greek letters in KE titles (e.g. "PPARα", "LXRβ", "TNFα") get zero BioPortal
# hits because ontology labels spell the letter out or fold it into a Latin gene
# suffix. We retry with Latin transliterations. Two forms per letter, tried in
# order: the single Latin letter attached to the stem first (α→"a", so
# "PPARα"→"PPARa", which matches gene symbols like PPARA [HGNC] and the
# receptor's Protein Ontology label), then the spelled-out word (α→"alpha").
# The single-letter form is deliberately first: for receptor names the
# spelled-out, space-separated form ("PPAR alpha") tends to surface the wrong
# paralog (e.g. PPAR-gamma terms), whereas the attached single letter does not.
_GREEK_SINGLE = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "h",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "u", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "w",
}
_GREEK_WORD = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron",
    "π": "pi", "ρ": "rho", "σ": "sigma", "ς": "sigma", "τ": "tau",
    "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
}
# Fold uppercase Greek onto the same transliterations.
_GREEK_SINGLE.update({k.upper(): v for k, v in list(_GREEK_SINGLE.items())})
_GREEK_WORD.update({k.upper(): v for k, v in list(_GREEK_WORD.items())})


def _greek_variants(phrase: str) -> list:
    """Latin transliterations of a phrase containing Greek letters.

    Returns an ordered, de-duplicated list of candidate query strings (never
    including the original), or [] when the phrase has no Greek letters. Order:
    single Latin letter attached (α→"a"), then spelled-out word (α→"alpha").
    """
    if not any(ch in _GREEK_WORD for ch in phrase):
        return []
    single = "".join(_GREEK_SINGLE.get(ch, ch) for ch in phrase)
    word = "".join(_GREEK_WORD.get(ch, ch) for ch in phrase)
    variants = []
    for v in (single, word):
        if v and v != phrase and v not in variants:
            variants.append(v)
    return variants


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


def _search_params(phrase: str, ontologies: str, api_key: str,
                   subtree_root_iri: str | None = None) -> dict:
    """Build the BioPortal search parameters.

    A subtree-restricted search uses BioPortal's `subtree_root_id`, which
    requires the singular `ontology` parameter and exactly one ontology —
    sending `ontologies` alongside it is a 400. Callers only pass
    subtree_root_iri with a single-ontology scope.
    """
    params = {
        "q": phrase,
        "require_exact_match": "false",
        "include": "prefLabel,synonym",
        "pagesize": 10,
        "apikey": api_key,
    }
    if subtree_root_iri:
        params["ontology"] = ontologies
        params["subtree_root_id"] = subtree_root_iri
    else:
        params["ontologies"] = ontologies
    return params


def search_bioportal(phrase: str, ontologies: str, api_key: str,
                     subtree_root_iri: str | None = None) -> list:
    """Search BioPortal for ontology terms matching a phrase, optionally
    restricted to the subtree rooted at `subtree_root_iri`."""
    params = urllib.parse.urlencode(
        _search_params(phrase, ontologies, api_key, subtree_root_iri)
    )
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


def ontology_submission_versions(acronyms, api_key: str) -> dict:
    """Return {ACRONYM: {version, released, submission_id}} from BioPortal's
    latest_submission endpoint, for run provenance. A failed lookup maps the
    acronym to None rather than raising — ontology content drifts between
    runs, so the versions are recorded best-effort."""
    versions: dict = {}
    for acronym in sorted({str(a).strip().upper() for a in acronyms if str(a).strip()}):
        params = urllib.parse.urlencode({"apikey": api_key, "display": "version,released,submissionId"})
        req = urllib.request.Request(
            f"{BIOPORTAL_ONTOLOGY_URL}/{acronym}/latest_submission?{params}",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            versions[acronym] = {
                "version": data.get("version"),
                "released": data.get("released"),
                "submission_id": data.get("submissionId"),
            }
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            print(f"  (submission lookup failed for {acronym}: {e})")
            versions[acronym] = None
    return versions


def search_bioportal_with_fallback(phrase: str, ontologies: str, api_key: str,
                                   subtree_root_iri: str | None = None) -> tuple[list, str]:
    """
    Search BioPortal with progressive fallback:
      1. Full phrase
      2. Greek letters transliterated to Latin (e.g. "PPARα" → "PPARa")
      3. Normalized phrase (stopwords removed)
      4. Noun phrase after 'of'
    Every attempt keeps the same subtree restriction, when one is given.
    Returns (results, query_used).
    """
    results = search_bioportal(phrase, ontologies, api_key, subtree_root_iri)
    if results:
        return results, phrase

    for variant in _greek_variants(phrase):
        results = search_bioportal(variant, ontologies, api_key, subtree_root_iri)
        if results:
            return results, f"{variant!r} (Greek transliterated)"

    normalized = normalize_phrase(phrase)
    if normalized != phrase:
        results = search_bioportal(normalized, ontologies, api_key, subtree_root_iri)
        if results:
            return results, f"{normalized!r} (stopwords removed)"

    of_match = re.search(r'\bof\s+(.+)$', phrase, re.IGNORECASE)
    if of_match:
        noun_phrase = normalize_phrase(of_match.group(1).strip())
        results = search_bioportal(noun_phrase, ontologies, api_key, subtree_root_iri)
        if results:
            return results, f"{noun_phrase!r} (noun phrase fallback)"

    return [], phrase

