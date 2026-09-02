# KER Analysis Functions

## `harmonize_ker_evidence` — Data Flow

The `harmonize_ker_evidence` CLI command orchestrates a 4-step pipeline that transforms
raw AOP-Wiki XML into structured Excel workbooks with harmonized evidence tables.

---

### Step 1 — Parse XML → All KERs

**Function:** `collect_entity_with_cache('kers', collect_kers_from_xml, ...)`

Checks `outputs/cache/{date}/all_kers_{date}.json` for a cached result. On a cache miss,
loads the AOP-Wiki XML from `<data-dir>/xml_inputs/`, parses every `<key-event-relationship>` element,
and builds a dict keyed by KER ID.

Each KER entry contains:

- `upstream_ke` / `downstream_ke`: ID and title of the bounding Key Events
- `aop_ids`: list of AOPs that include this KER
- `has_any_tables`: boolean flag (used for filtering in Step 2)
- Four evidence fields, each with `free_text`, `tables` (raw row data), and `headers`:
  - `weight_of_evidence`
  - `empirical_support`
  - `biological_plausibility`
  - `quantitative_understanding`
- Taxonomy/DOA fields: `sex_terms`, `life_stage_terms`, `taxonomy_terms`
- Narrative fields: `description`, `modulating_factors`, `uncertainties`, `response_relationship`, etc.
- `completion_score`: computed float added after collection

**Output:** Dict of ~1000+ KERs, cached to `all_kers_{date}.json`.

---

### Step 2 — Filter → KERs with Evidence Tables

**Function:** `filter_kers_by_tables(all_kers, has_tables=True)`

A simple dict comprehension on the `has_any_tables` boolean flag set during XML parsing.
Reduces the full set to only KERs that have at least one tabulated evidence entry (~100–200 KERs typically).

**Output:** Reduced KER dict, no caching.

---

### Step 3 — Harmonize Headers → Canonical Column Names

**Function:** `harmonize_kers_with_cache(kers_with_tables, ...)`

Checks for `outputs/cache/{date}/kers_with_harmonized_evi_tables_{date}.json`. On a miss,
applies a 4-step header resolution pipeline to each evidence table's column headers:

1. **Direct mapping** via `COLUMN_HARMONIZER` dict (e.g., `"dose"` → `"Dose"`)
2. **Keyword matching** (e.g., `"upstream"` → `"Upstream Key Event"`)
3. **Semantic variation matching** against known KE label variants
4. **Fuzzy matching** via `difflib` (similarity threshold: 0.7)

A KER is considered **harmonizable** only if its tables resolve to all three required canonical columns:

- `Upstream Key Event`
- `Downstream Key Event`
- `References`

**Output dict structure:**

- `summary` key: counts of harmonizable KERs, all/unmatched/harmonized headers,
  AOPs with tabulated vs. harmonizable evidence
- Per-KER entries: `harmonized_tables`, `header_mapping` (original → canonical),
  `harmonized_headers`, `unmatched_headers`, `harmonized_fields`

**Output:** Cached to `kers_with_harmonized_evi_tables_{date}.json`.

---

### Step 4 — Write Excel Workbooks

**Function:** `initiate_workbook_creation_for_harmonized_kers(...)`

Uses `AOPS_SELECTED_FOR_HARMONIZED_KERS_WORKBOOKS` from `src/aop_wiki_cli/configs/harmonize_ker_evidence.py`
to scope output to 5 specific AOPs:

| AOP ID | Title |
| --- | --- |
| 281 | Acetylcholinesterase Inhibition Leading to Neurodegeneration |
| 237 | Substance interaction with lung resident cell membrane... |
| 3 | Inhibition of the mitochondrial complex I... |
| 307 | Decreased testosterone synthesis... |
| 392 | Decreased fibrinolysis and activated bradykinin system... |

For each selected AOP, writes one Excel workbook to `outputs/ker_evidence/` containing
the harmonized evidence tables for all of that AOP's KERs.

---

### Data Shape Summary

```sh
XML file
  → all_kers dict        (~1000+ KERs, raw headers)         [cached: all_kers_{date}.json]
    → kers_with_tables   (~100–200, has_any_tables=True)    [not cached]
      → harmonized_kers  (canonical headers, harmonizable)  [cached: kers_with_harmonized_evi_tables_{date}.json]
        → Excel workbooks (one per AOP in config)           [outputs/ker_evidence/]
```
