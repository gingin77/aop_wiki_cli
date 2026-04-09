# Caching Functions

## Purpose

This note summarizes existing caching utilities in the codebase.

---

## Existing Caching Utilities

### 1) `generic_cache_wrapper`

- Location: `src/utilities/helpers.py`
- Signature:
  - `generic_cache_wrapper(cache_key, cache_dir, data_collector, force_refresh=False, logger=None)`
- Current behavior:
  - Cache filename: `f"{cache_key}.json"`
  - If cache exists and `force_refresh=False`, load and return cached JSON
  - Else run `data_collector()`, write JSON, return data
- Strengths:
  - Reusable for any JSON-serializable payload
  - Already supports `force_refresh`
  - Centralized logging behavior

### 2) `collect_entity_with_cache`

- Location: `src/parsers/parse_aop_wiki_xml_data.py`
- Purpose:
  - Specialized wrapper for XML entity collection (`events`, `kers`, `aops`)
  - Delegates to `generic_cache_wrapper`
- Cache key pattern:
  - `all_{entity_type}_{MM-DD-YYYY}`

### 3) `harmonize_kers_with_cache`

- Location: `src/harmonization/helpers_for_ker_evidence_harmonization.py`
- Purpose:
  - Caches harmonized KER evidence output
  - Delegates to `generic_cache_wrapper`
- Cache key pattern:
  - `kers_with_harmonized_evi_tables_{MM-DD-YYYY}`

---

## Quick Reference Paths

- `src/utilities/helpers.py` (`generic_cache_wrapper`)
- `src/parsers/parse_aop_wiki_xml_data.py` (`collect_entity_with_cache`)
- `src/harmonization/helpers_for_ker_evidence_harmonization.py` (`harmonize_kers_with_cache`)
