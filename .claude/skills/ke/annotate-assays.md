Extract and annotate assay information from the measurement_method field for a single KE.

## Usage

Invoked with a KE ID as $ARGUMENTS.

Run:
`uv run python scripts/annotate_ke.py --ke-id $ARGUMENTS --annotate-assays --date <cache_date>`

## Output

Present the ASSAY SUMMARY to the user:
- Number of assays extracted
- For each assay: title, assay_type (OBI/BAO term), effect_specificity, objects, processes, taxon_terms, citations

Flag any assays where assay_type fell back to the generic `OBI:assay` term — these may need manual review.

## Dependencies

- The KE must already have ECS annotation in the shared store. Run annotate-structured-ke-fields first if not.
- Requires BIOPORTAL_API_KEY and ANTHROPIC_API_KEY in .env
