Identify and resolve KEs flagged with needs_review in the shared store.

## Usage

No arguments required. Reads directly from the shared store.

## Steps

1. Load outputs_for_vc/aop_based_ke_annotations/ke_annotations.json
2. Find all KEs where any field has needs_review: true (typically phenotype terms with GO IDs)
3. For each flagged KE, present:
   - KE ID and title
   - The flagged field and current value
4. Ask the user: "Accept, replace, or set to null?"
5. Apply the user's decision:
   - Replace: `uv run python scripts/annotate_ke.py --ke-id <ke_id> --force-on <field> --date <cache_date>`
   - Add comment: `uv run python scripts/annotate_ke.py --ke-id <ke_id> --add-comment "<comment>"`
   - Set to null: manually edit the shared store JSON and set the field to null, then re-run `--force-on <field>`

## Notes

- Flagged fields are most commonly phenotype terms where a GO term was selected instead of UPHENO/HP/MP
- Use `--force-on phenotype` to re-annotate after clearing the reference value manually
