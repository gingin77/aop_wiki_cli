Extract and structure citation references from free-text fields of an AOP-Wiki entity (KE, KER, or AOP).

## Citation schema

Each citation object contains:
- authors: author string as it appears in the text
- year: publication year
- title: full title (null if not in text)
- journal: journal name (null if not in text)
- doi: DOI (null if not in text)
- pmid: PubMed ID (null if not in text)

## Usage

Invoked with an entity type, ID, and source field as $ARGUMENTS (e.g. "ke 122 measurement_method").

## Steps

1. Read the source field from the cache for the specified entity.
2. Strip HTML and extract citation strings from the text.
3. Parse each into a structured citation object.
4. Write citations to the entity's annotation store entry under the appropriate key.

## Notes

- For KE assays, citations are extracted per-assay during annotate-assays — do not duplicate
- The references field on a KE contains full bibliographic records that can enrich author+year citations extracted from other fields
