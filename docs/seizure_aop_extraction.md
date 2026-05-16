# Seizure AOP Extraction Functions

## `collect_harmonized_seizure_aops` — Data Flow

The `collect_harmonized_seizure_aops` CLI command orchestrates a 9-function pipeline that
transforms a seizure AOP Excel workbook into enriched, harmonized data with two stages of
human-in-the-loop review.

The input seizure AOP Excel workbook is the supplemental data published by Behl, et al (2025) and
the following worksheets were used:

| Worksheet | Mappings extracted |
| --- | --- |
| Suppl2_KEs AOP Harmonization | AOP ID → Key Events (with original title, harmonized KE title, references, target family); produces `harmonization_dict`, `event_mappings_orig_to_harmonized`, `aop_to_harmonized_events_dict` |
| Suppl6_ICE Assays | Assay endpoints (AEID, name, MOA, mechanistic target, species) → target families, KE descriptions, AOP IDs; standalone target family list; produces `aeid_mappings`, `aop_id_mapping`, `ke_description_mapping`, `target_families` |
| Suppl4_Compiled Compounds | Chemicals by CASRN with direction of effect, PubChem evidence flag, and parsed literature citations; produces `chemicals_by_casrn_with_seizure_details` |

The central data structure throughout is `seizure_content`, a nested dict with 5 root
groups: `ready_for_emod`, `mappings_generated`, `to_analyze`, `for_xlsx_export_only`,
and `enriched`. It is populated by `parse_seizure_aop_workbook()` and progressively
enriched by each subsequent step.

Each root group has the same shape:

```python
seizure_content['<group>'] = {
    'data': { ... },          # The actual payload (datasets, mappings, etc.)
    'export_types': [...]     # e.g. ['json', 'xlsx'] — controls what export_seizure_aop_results() writes
}
```

So `seizure_content['ready_for_emod']['data']['harmonized_kes']` is a real access path.
References to `<group>.data` throughout this document refer to this `data` key.

---

### Step 1 — Parse Workbook → `seizure_content`

**Function:** `parse_seizure_aop_workbook(workbook_path)`
**Source:** `src/parsers/parse_behl_seizure_aop_workbook.py`

Reads 3 sheets from `inputs/seizure_aops/behl_seizure_supp_data.xlsx`:
harmonization, assays, and chemicals. Extracts and organizes content into the
`seizure_content` structure.

Initial `seizure_content` root groups populated here:

- `ready_for_emod.data`: Cleaned data ready for downstream use
  - `harmonized_kes`: list of harmonized KE titles from the workbook
  - `biological_target_families`: target families linked to assays
  - `event_mappings_orig_to_harmonized`: mapping from original → harmonized KE
  - `aop_to_harmonized_events_dict`: per-AOP harmonized event lists
  - `assays_by_aeid`, `chemicals_by_casrn_with_seizure_details`
- `mappings_generated.data`: Structures requiring further transformation
  - `ke_description_mappings_from_assays_df`: KE descriptions (needs fuzzy matching)
  - `aop_id_to_assays_and_target_families`, `dict_of_target_family_lists`
- `to_analyze.data`: Raw nested structures for enrichment
  - `harmonization_dict`: AOP-centric event mappings (input to Step 8)
  - `assays`: raw assay list
  - `target_families_to_h_events_and_assays`: TF → events/assays (input to Steps 5–7)
- `for_xlsx_export_only.data`: Validation metadata (merged events, discrepancies)
- `enriched.data`: Empty at this point; populated in Steps 3–8

**Output:** Populated `seizure_content` dict.

---

### Step 2 — Fuzzy Match KE Descriptions → Harmonized KE Titles

**Function:** `map_ke_descriptions_to_harmonized_kes(ke_description_mapping, harmonized_kes_list, threshold=0.6)`
**Source:** `src/analysis/map_ke_descriptions_to_harmonized.py`

The Behl workbook links assays to KE *descriptions* rather than exact KE titles. This step
uses prefix-weighted fuzzy matching to find the best harmonized KE title for each
description (threshold: 0.6).

**Input:** KE descriptions from `mappings_generated`, list of harmonized KE titles from
`ready_for_emod`.\
**Output:** Same mapping structure with added `input_term`, `matched_term`, and
`match_score` fields per entry.

---

### Human Review — Stage 1: KE Description ↔ Harmonized KE

**Function:** `review_matches(enhanced_ke_description_mapping, score_threshold=0.9)`
**Source:** `src/analysis/manual_match_review.py`

Interactive terminal review of matches below the 0.9 confidence threshold.
High-confidence matches (≥ 0.9) are auto-approved.

For each low-confidence match the user is prompted:

```
Review item: "KE description" → "Harmonized KE" (score: X.XX)
[y/n/q]:
  y = accept (human_verified=true)
  n = reject (human_verified=false; optional suggested match)
  q = quit (remaining items marked unreviewed)
```

**Checkpoint:** Results are saved to
`outputs_for_vc/reviewed_ke_description_to_harmonized_ke_mapping.json`.
If this file exists and `--skip-curated` is not set, this stage is skipped on re-runs.

**Output stored in:** `seizure_content['enriched']['data']['ke_description_to_harmonized_ke_mapping']`

---

### Step 3 — Collect AOP-Wiki Data (Cached)

**Function:** `collect_entity_with_cache('aops', ...)` and `collect_entity_with_cache('events', ...)`
**Source:** `src/parsers/parse_aop_wiki_xml_data.py`

Checks `outputs/cache/{date}/all_aops_{date}.json` and
`outputs/cache/{date}/all_events_{date}.json`. On a cache miss, parses the AOP-Wiki XML
export from `xml_inputs/` and saves results to cache.

**Output:** `all_aops` and `all_events` dicts used for Wiki-side enrichment in Steps 5–8.

---

### Step 4 — Fuzzy Match Target Families → Wiki Events

**Function:** `enrich_target_families(target_families_to_h_events_and_assays, all_events)`
**Source:** `src/analysis/map_ke_descriptions_to_harmonized.py`

For each biological target family from the workbook, checks for an existing manual mapping
to harmonized events. If none exists, fuzzy-matches the target family name against Wiki
event titles (threshold: 0.5).

**Output:** Dict with `matched_term`, `match_score`, and `matched_event_id` per target
family, sorted by score descending.

---

### Human Review — Stage 2: Target Family ↔ Wiki Event

**Function:** `review_matches(tfs_to_events, score_threshold=0.9)`
**Source:** `src/analysis/manual_match_review.py`

Same interactive review process as Stage 1, applied to target family → event matches.
After review, the CLI renames fields for clarity:

- `input_term` → `target_family`
- `matched_term` → `event`
- `suggested_match` → `suggested_event`

**Checkpoint:** Results saved to `outputs_for_vc/curated_event-target_family_mappings.json`.
If this file exists and `--skip-curated` is not set, this stage is skipped on re-runs.

**Output stored in:** `seizure_content['enriched']['data']['biological_target_families_enriched']`

---

### Step 5 — Map Assays to Events via Target Families

**Function:** `map_assays_to_events_via_target_families(enriched_target_families_reviewed, target_families_to_h_events_and_assays)`
**Source:** `src/analysis/map_ke_descriptions_to_harmonized.py`

Creates a two-step linking chain: assays → target families → events. For each target
family, builds an event list from three sources (in priority order):

1. `harmonized_workbook`: events pre-mapped in the harmonization sheet
2. `fuzzy_matched`: fuzzy-matched events where `human_verified=true`
3. `manual_suggestion`: user-supplied suggestions (regardless of verification status)

All events linked through a target family inherit all of that family's assays.

**Output:** Dict with:

- `event_to_assays`: maps each event to its assays and originating target families
- `summary`: aggregation statistics

**Stored in:** `seizure_content['enriched']['data']['event_to_assays_via_target_families']`
and `['event_to_assays_summary']`

---

### Step 6 — Organize and Enrich Harmonized Events

**Function:** `organize_and_enrich_harmonized_events(seizure_aop_curations, all_aops, all_events)`
**Source:** `src/analysis/analyze_seizure_aop_content.py`

Two-stage enrichment:

**A) `add_wiki_content()`**
Looks up each Behl event by ID in the Wiki XML, adds `title_from_wiki`, `lobo`, and
`event_match` metadata. Reports any title string differences for QC.

**B) `analyze_harmonized_kes()`**
Pivots structure from AOP-centric `{aop_id: {event_id: ...}}` to harmonization-centric
`{harmonized_ke: {event_id: ...}}`. For each harmonized KE, aggregates:
event IDs, LOBOs, AOP IDs, references, and target families. Separates excluded ("E") and
unassigned ("nan") events.

**Output:** Tuple of:

1. `extraction_summary`: per-AOP counts of matched/unmatched/excluded events
2. `enriched_seizure_aop_events`: data reorganized by harmonized KE
3. `harmonized_summary`: aggregated counts per harmonized KE

**Stored in:** `seizure_content['enriched']['data']['enriched_seizure_aop_events']` and
`['harmonized_summary']`

---

### Step 7 — Export All Results

**Function:** `export_seizure_aop_results(seizure_content, output_dir, work_date_str)`
**Source:** `src/data_export/seizure_aop_export.py`

Iterates over `seizure_content` root groups and writes each dataset based on its declared
`export_types` (`json`, `csv`, `xlsx`). All files written to
`outputs/seizure_aops/{MM-DD-YYYY}/`.

**JSON exports** (one file per dataset):

- `ready_for_emod/`: `biological_target_families`, `harmonized_kes`, `chemicals_by_casrn_with_seizure_details`, etc.
- `enriched/`: `ke_description_to_harmonized_ke_mapping`, `biological_target_families_enriched`,
  `event_to_assays_via_target_families`, `enriched_seizure_aop_events`, `harmonized_summary`

**CSV exports:**

- `harmonization_dict_{date}.csv`
- `assays_{date}.csv`
- `ke_description_mappings_{date}.csv`

**XLSX export:**

- `seizure_aop_events_{date}.xlsx` (multiple named sheets)

---

### Human-in-the-Loop Review Summary

| Stage | Data reviewed | Auto-approve threshold | Checkpoint file |
| --- | --- | --- | --- |
| 1 | KE description ↔ harmonized KE | score ≥ 0.9 | `outputs_for_vc/reviewed_ke_description_to_harmonized_ke_mapping.json` |
| 2 | Target family ↔ Wiki event title | score ≥ 0.9 | `outputs_for_vc/curated_event-target_family_mappings.json` |

If either checkpoint file is present, the corresponding review stage is skipped on re-runs.
Use `--skip-curated` to force interactive review regardless.

---

### Data Shape Summary

```sh
Excel workbook (behl_seizure_supp_data.xlsx)
  → seizure_content dict (5 root groups)                        [Step 1: parse_seizure_aop_workbook]
    → KE description fuzzy matches                             [Step 2: map_ke_descriptions_to_harmonized_kes]
      → Stage 1 human review (KE description ↔ harmonized KE) [HitL Review 1]
    → all_aops, all_events dicts                               [Step 3: collect_entity_with_cache, cached]
    → target family fuzzy matches                              [Step 4: enrich_target_families]
      → Stage 2 human review (target family ↔ event)          [HitL Review 2]
    → event_to_assays mapping                                  [Step 5: map_assays_to_events_via_target_families]
    → enriched_seizure_aop_events + harmonized_summary         [Step 6: organize_and_enrich_harmonized_events]
      → outputs/seizure_aops/{date}/*.json / *.csv / *.xlsx    [Step 7: export_seizure_aop_results]
```
