---
name: ke-ontology-annotations
description: 'Extract bio-ontology term annotations (GO, UBERON, CL, ChEBI, NCBI Taxonomy, HPO, UPheno) from AOP-Wiki Key Events parsed from the AOP-Wiki XML. Use when annotating a discrete set of Key Events (KEs) defined by a named config file, producing both a JSON and a long-format CSV annotation output. Trigger phrases: annotate KEs, ontology annotations, KE annotations, GO terms, UBERON terms, bio-ontology mapping, key event ontology.'
argument-hint: 'Config name from configs/ (e.g. lung_and_immune_aops)'
---

# KE Ontology Annotations

## What This Skill Produces

A **JSON file** (one record per KE) and a **long-format CSV file** (one row per KE × ontology term) containing all bio-ontology annotations extractable from the AOP-Wiki XML for a config-filtered set of Key Events.

Supported ontologies extracted directly from the XML:

| Ontology | KE Field | XML Element |
|---|---|---|
| UBERON | `organ_term.source` / `organ_term.term` | `<organ-term>` |
| CL (Cell Ontology) | `cell_term.source` / `cell_term.term` | `<cell-term>` |
| GO (biological process) | `ecs[].biological_process` | `<biological-events>` |
| GO / ChEBI (biological object) | `ecs[].biological_object` | `<biological-events>` |
| AOP-Wiki action terms | `ecs[].biological_action` | `<biological-events>` |
| NCBI Taxonomy | `taxonomy_terms[].source` / `source-id` | `<applicability>` |
| HPO / UPheno | Present only if embedded in XML source fields | any of the above |

> **Coverage note**: `source_id` is not captured for `organ_term` or `cell_term` by the current `collect_events_from_xml` parser. Document this gap in output metadata. HPO and UPheno terms will only appear if they are used as the `source` value in the XML; log a coverage summary at the end.

---

## When to Use

- User asks to annotate Key Events with ontology terms
- User asks to extract GO, UBERON, CL, ChEBI, or taxonomy terms from KEs
- User needs a KE → ontology term mapping table for a topic-specific AOP set
- User references a named config (e.g. `lung_and_immune_aops`, `regulatory_relevance`)

---

## Inputs

| Argument | Description |
|---|---|
| `config` (required) | Module name under `configs/` (e.g. `lung_and_immune_aops`) |
| `--date MM-DD-YYYY` | XML cache date; defaults to today |
| `--force-refresh` | Bypass cache and re-parse the XML |

---

## Procedure

### Step 1 — Understand the target KE set

1. Open `configs/<config_name>.py`.
2. Read `SEARCH_PARAMS` to understand filter terms, entity types, and co-occurrence pairs.
3. Note `OUTPUT_CONFIG["directory"]` — the annotation files will go there.
4. Determine `search_mode`: `"event_to_aop"`, `"entities_and_fields"`, or default (single-entity).

### Step 2 — Implement the annotation extractor

Create `src/analysis/annotate_ke_ontology.py`. The core function signature:

```python
def extract_ke_ontology_annotations(events_dict: dict) -> dict:
    """
    Extract bio-ontology annotations from a parsed events dictionary.

    Args:
        events_dict: Dict keyed by KE ID, as returned by collect_events_from_xml.

    Returns:
        Dict keyed by KE ID, each value is a list of annotation dicts:
        {
            "ontology": str,        # e.g. "GO", "UBERON", "CL", "NCBI Taxonomy"
            "term_type": str,       # "organ", "cell", "biological_process",
                                    #   "biological_object", "biological_action",
                                    #   "taxonomy"
            "source_id": str | None,
            "term_name": str
        }
    """
```

Extraction rules per field:

| KE field | `ontology` value | `term_type` | `source_id` | `term_name` |
|---|---|---|---|---|
| `organ_term` | `ke["organ_term"]["source"]` | `"organ"` | `None` (not in parser) | `ke["organ_term"]["term"]` |
| `cell_term` | `ke["cell_term"]["source"]` | `"cell"` | `None` (not in parser) | `ke["cell_term"]["term"]` |
| `ecs[n].biological_process` | `proc["source"]` | `"biological_process"` | `proc["source_id"]` | `proc["term"]` |
| `ecs[n].biological_object` | `obj["source"]` | `"biological_object"` | `obj["source_id"]` | `obj["term"]` |
| `ecs[n].biological_action` | `"AOP-Wiki"` | `"biological_action"` | `action["source_id"]` | `action["term"]` |
| `taxonomy_terms[n]` | `"NCBI Taxonomy"` | `"taxonomy"` | `tax["source-id"]` | `tax["title"]` |

Additional rules:
- Skip any annotation where `term_name` is `None` or empty.
- Deduplicate within a KE: same `(ontology, source_id, term_name)` tuple → keep one.
- If `source` contains "HPO" or "UPheno" anywhere, emit normally; they surface through the standard logic.

### Step 3 — Implement filtered collection helper

In the same file, add:

```python
def collect_annotated_ke_set(
    config_name: str,
    work_date,
    cache_dir: str,
    force_refresh: bool = False
) -> tuple[dict, dict]:
    """
    Load config, collect events, filter by config criteria, extract annotations.

    Returns:
        (filtered_events_dict, annotations_dict)
    """
```

Logic:
1. `importlib.import_module(f'configs.{config_name}')` → get `SEARCH_PARAMS`.
2. `collect_entity_with_cache('events', collect_events_from_xml, work_date, cache_dir, force_refresh)` → `events` (full events dict, keyed by KE ID).
3. If `search_mode == "event_to_aop"`: also collect AOPs; use `collect_events_from_matched_aops` to get the KE ID set.
4. Otherwise: `_, filtered_results = search_entity_data(events, search_params)`; extract KE IDs with `filtered_ke_ids = set(filtered_results.keys())`.
5. Build `filtered_events_dict = {ke_id: events[ke_id] for ke_id in filtered_ke_ids if ke_id in events}` to preserve full KE fields for annotation.
6. Call `extract_ke_ontology_annotations(filtered_events_dict)`.

### Step 4 — Add field definitions

In `src/data_export/field_definitions.py`, add a `FieldConfigSet` for the long-format CSV:

```python
KE_ONTOLOGY_ANNOTATION_FIELDS = FieldConfigSet(
    name="ke_ontology_annotations",
    fields=[
        FieldConfig('KE ID', 'ke_id'),
        FieldConfig('KE Title', 'title'),
        FieldConfig('Ontology', 'ontology'),
        FieldConfig('Term Type', 'term_type'),
        FieldConfig('Source ID', 'source_id'),
        FieldConfig('Term Name', 'term_name'),
    ]
)
```

Export it from `src/data_export/__init__.py`.

### Step 5 — Add CLI command

In `cli.py`, add:

```python
@app.command()
def annotate_ke_ontology(
    config: str = typer.Argument(
        ...,
        help="Config name from configs/ (e.g. lung_and_immune_aops)"
    ),
    cache_date: Optional[str] = typer.Option(
        None, "--date", "-d",
        help="Date of cached data to use (MM-DD-YYYY). Defaults to today."
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", "-f",
        help="Force fresh data collection, ignoring cached files"
    )
):
    """Annotate a config-defined KE set with bio-ontology terms from the AOP-Wiki XML."""
```

Command body:
1. Parse `work_date` and `work_date_str` (same pattern as `search_with_config`).
2. `cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)`.
3. Load config → `output_dir`.
4. Call `collect_annotated_ke_set(config, work_date, cache_dir, force_refresh)`.
5. Write JSON and CSV (see Step 6).
6. Print coverage report (see Step 7).

### Step 6 — Write outputs

**JSON** — `<output_dir>/<config>_ke_annotations_<date_str>.json`

```json
{
  "metadata": {
    "config": "<config_name>",
    "date": "<date_str>",
    "ke_count": N,
    "source_id_caveat": "organ_term and cell_term source_id not captured by current XML parser"
  },
  "ke_annotations": {
    "KE123": {
      "ke_id": "KE123",
      "title": "...",
      "annotations": [
        {"ontology": "UBERON", "term_type": "organ", "source_id": null, "term_name": "lung"},
        {"ontology": "GO", "term_type": "biological_process", "source_id": "GO:0006954", "term_name": "inflammatory response"}
      ]
    }
  }
}
```

Use `write_dict_to_json` from `src/utilities`.

**CSV** — `<output_dir>/<config>_ke_annotations_<date_str>.csv`

Flatten the annotations into a list of dicts before writing — one dict per annotation, with the KE's `ke_id` and `title` merged in:

```python
rows = [
    {"ke_id": ke_id, "title": events_dict[ke_id]["title"], **ann}
    for ke_id, anns in annotations_dict.items()
    for ann in anns
]
```

Pass this flat list to `write_csv(data=rows, field_config=KE_ONTOLOGY_ANNOTATION_FIELDS, output_path=csv_path)`. Note: `write_csv` accepts both a list and a dict; pass the list directly here.

### Step 7 — Print coverage report

After writing files, print:

```
KE Ontology Annotation Coverage
════════════════════════════════
Total KEs annotated:         N
KEs with UBERON organ term:  N
KEs with CL cell term:       N
KEs with GO process terms:   N
KEs with GO/ChEBI objects:   N
KEs with taxonomy terms:     N
KEs with zero annotations:   N  ← flag for manual curation
HPO/UPheno terms found:      N  (or "None found in XML")
```

---

## Quality Checks

- [ ] All fields with `None` or empty `term_name` are skipped — no empty annotation rows
- [ ] Deduplicate annotations within a KE (same `ontology + source_id + term_name` triple)
- [ ] `source_id` caveat noted in JSON metadata and CLI output for `organ_term` / `cell_term`
- [ ] Output file naming: `<config>_ke_annotations_<date_str>.json/.csv`
- [ ] `src/analysis/__init__.py` updated to export `extract_ke_ontology_annotations` and `collect_annotated_ke_set`
- [ ] `src/data_export/__init__.py` updated to export `KE_ONTOLOGY_ANNOTATION_FIELDS`
- [ ] No HPO/UPheno annotations silently dropped — coverage gap logged even if count is zero

---

## Files to Create / Edit

| Action | File | What to do |
|---|---|---|
| **Create** | `src/analysis/annotate_ke_ontology.py` | Core extractor + collection helper |
| **Edit** | `src/analysis/__init__.py` | Export new functions |
| **Edit** | `src/data_export/field_definitions.py` | Add `KE_ONTOLOGY_ANNOTATION_FIELDS` |
| **Edit** | `src/data_export/__init__.py` | Export new field set |
| **Edit** | `cli.py` | Add `annotate_ke_ontology` command |

---

## Example Invocations

```bash
# Annotate KEs from the lung/immune AOP set
uv run python cli.py annotate-ke-ontology lung_and_immune_aops

# Use a specific XML cache date
uv run python cli.py annotate-ke-ontology lung_and_immune_aops --date 04-21-2026

# Force re-parse the XML
uv run python cli.py annotate-ke-ontology lung_and_immune_aops --force-refresh
```
