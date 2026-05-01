Compare KE annotations in the shared store against the AOP-Wiki cache and report divergences.

## Usage

Run:
`uv run python scripts/compare_ke_annotations.py`

## Output

Present a summary:
- Total KEs compared
- KEs with divergent content (both files have a value but they differ)
- KEs with new-only fields (populated in annotation but blank in cache)
- Path to the output CSV: outputs/ke_annotation_comparison.csv
