Interactively annotate structured ECS fields for all KEs in AOP $ARGUMENTS one at a time, collecting user feedback after each KE.

## Setup

1. Find the most recent cache date under outputs/cache/ (list dirs, pick the latest).
2. Run the list command to show which KEs are pending vs. already annotated:
   `uv run python scripts/annotate_ke.py --aop $ARGUMENTS --date <cache_date>`

## Per-KE loop

For each pending KE (in order):

1. Tell the user which KE you are about to annotate (ID and title).
2. Run:
   `uv run python scripts/annotate_ke.py --ke-id <ke_id> --date <cache_date>`
3. Present the ANNOTATION SUMMARY to the user in a readable format.
   If any phenotype is flagged with `⚠ needs_review`, highlight it explicitly.
4. Ask: "Any comments or corrections for this KE? (type your comment, or press Enter to continue)"
5. If the user provides a comment, run:
   `uv run python scripts/annotate_ke.py --ke-id <ke_id> --add-comment "<comment>"`
6. Ask: "Continue to the next KE?" and wait for confirmation before proceeding.

## Completion

After all KEs are done (or the user stops early):

1. Report:
   - Total KEs annotated this session
   - Path to the shared store (outputs_for_vc/annotations/ke_annotations.json)
   - Any KEs skipped or still pending

2. Run the comparison script:
   `uv run python scripts/compare_ke_annotations.py`
   Present a brief summary of the output: how many KEs have divergent fields vs. new-only fields, and the output CSV path.
