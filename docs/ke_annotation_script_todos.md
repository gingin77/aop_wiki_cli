# KE Annotation Script — Cleanup TODOs

Scripts covered:
- `scripts/test_bioportal_based_ke_title_annotation.py` (core annotation logic)
- `scripts/annotate_aop_ke_ontology.py` (CLI entry point and storage)
- `.claude/commands/annotate-aop-ke-ontology.md` (slash command)

---

## Should the two scripts be merged?

**Recommendation: yes, merge into one script.**

`test_bioportal_based_ke_title_annotation.py` was originally an exploratory/prototyping script and retains that character. `annotate_aop_ke_ontology.py` was built on top of it and is the real entry point. The split creates unnecessary indirection — the CLI script imports core logic from a file named `test_*`, which is confusing, and there is no reason to keep them separate now that the workflow is stable.

Proposed merged name: `scripts/annotate_ke_ontology.py`

---

## `test_bioportal_based_ke_title_annotation.py`

### Remove dead code and stale config

- [ ] **Remove top-level script constants** that were only used by the original `main()` and are no longer relevant when the file is imported as a module:
  - `KE_IDS`, `CACHE_FILE`, `OUTPUT_DIR`, `REFERENCE_FILE`, `BIOPORTAL_URL`
- [ ] **Remove `write_results()`** — writes a dated JSON file to `outputs/ke_ontology_suggestions/`; no longer called anywhere (storage is now handled by `annotate_aop_ke_ontology.py`).
- [ ] **Remove `main()`** — the old interactive loop over `KE_IDS`. No longer the entry point; replaced by `annotate_aop_ke_ontology.py`.
- [ ] **Update the module docstring** — still describes the original exploratory script and references `test_bioportal_ke1499.py`.

### Fix inconsistent model usage

- [ ] **Standardise on one Claude model.** Three different model strings are currently used across LLM calls:
  - `claude-sonnet-4-5` — used in `llm_rank_term`, `llm_decompose_subject`, `detect_biological_organization`, `annotate_ke` (comment review)
  - `claude-sonnet-4-6` — used in `llm_normalize_biological_action`
  Define a single `LLM_MODEL` constant at the top and reference it everywhere.

### Reduce repeated client instantiation

- [ ] **Create one `anthropic.Anthropic` client per annotation run** instead of calling `anthropic.Anthropic(api_key=...)` inside each LLM function (`llm_rank_term`, `llm_normalize_biological_action`, `llm_decompose_subject`, `detect_biological_organization`, `annotate_ke`). Pass the client as a parameter, or create it once in `annotate_ke()` and thread it through.

### Minor code quality

- [ ] **`check_anthropic_available()`** makes a live network probe on every LLM function call. Cache the result for the duration of a single `annotate_ke()` run.
- [ ] **`_extract_biological_process()`** just returns its input unchanged — consider inlining or removing.
- [ ] **`ECS_ONTOLOGIES` dict** is defined but `biological_process` key is the only one used directly; `biological_object` ontologies are hard-coded separately. Either use the dict consistently or remove it.
- [ ] **`sys` import is missing** — `sys.stdin.isatty()` is called in `detect_biological_organization` but `sys` is not imported at the top of the file (currently works because the caller imports it).

### Annotation logic

- [ ] **`_CELL_TERM_LEVELS`** includes `"Molecular"` — consider whether molecular-level KEs should routinely get a cell_term annotation, since many (e.g. receptor activation) have no meaningful cell type.
- [ ] **Phenotype guidance missing from `llm_rank_term`** — `component_guidance` has entries for `cell_term`, `organ_term`, `biological_process`, `biological_object` but not `phenotype`. Add guidance clarifying that phenotype terms should come from UPHENO, HP, or MP and that GO terms need manual review.

---

## `annotate_aop_ke_ontology.py`

### Remove stale references

- [ ] **`_migrate_per_aop_files()`** was a one-time migration from the old per-AOP file format. Now that migration is complete, this function can be removed along with its call in `main()`.
- [ ] **`--reference` flag** is mentioned in the slash command but does not exist in the current `argparse` definition — either add it or remove the mention.

### Storage / newly_annotated_fields

- [ ] **`newly_annotated_fields` is lost on `--force` re-annotation** because the existing store entry becomes the reference, so no fields appear "new." On `--force`, either preserve the original field from the reference or recompute against an empty reference so all annotated fields are recorded.

### If merging into one script

- [ ] Move the storage functions (`_load_shared_store`, `_save_shared_store`, `_load_aop_store`, `_save_aop_store`, `_register_ke_in_aop`), `list_aop_kes`, `annotate_single_ke`, `add_comment`, and `main()` into the merged script.
- [ ] The import line `from test_bioportal_based_ke_title_annotation import annotate_ke, _flat_ref_comments` goes away.

---

## `.claude/commands/annotate-aop-ke-ontology.md`

- [ ] **Remove `--reference` flag** from the per-KE run command on line 16 — this flag does not exist in the current script.
- [ ] **Update the setup step** — step 2 checks for a reference file at `outputs/ke_ontology_suggestions/ke_suggestions_<date>.json`, which is the old format. The current workflow uses the shared store at `outputs_for_vc/annotations/ke_annotations.json`; no separate reference file needs to be located.
- [ ] **Add `needs_review` flag handling** — after presenting the annotation summary, note any phenotype terms flagged `needs_review: true` so the user knows to inspect them.
- [ ] If the scripts are merged, update the command invocations to point to the new script name.
