Interactively annotate all Key Events for AOP $ARGUMENTS one at a time, collecting user feedback after each KE.

## Setup

1. Find the most recent cache date under outputs/cache/ (list dirs, pick the latest).
2. Check for a reference file at outputs/ke_ontology_suggestions/ke_suggestions_<cache_date>.json.
3. Run the list command to show the user which KEs are pending vs. already done:
   `uv run python scripts/annotate_aop_ke_ontology.py --aop $ARGUMENTS --date <cache_date>`

## Per-KE loop

For each pending KE (in order):

1. Tell the user which KE you are about to annotate (ID and title).
2. Run:
   `uv run python scripts/annotate_aop_ke_ontology.py --aop $ARGUMENTS --ke-id <ke_id> --date <cache_date> [--reference <ref_file>]`
3. Present the ANNOTATION SUMMARY from the output to the user in a readable format.
4. Ask the user: "Any comments or corrections for this KE? (type your comment, or press Enter to continue)"
5. If the user provides a comment, run:
   `uv run python scripts/annotate_aop_ke_ontology.py --aop $ARGUMENTS --ke-id <ke_id> --add-comment "<comment>"`
   You may add multiple comments — keep asking until the user is done.
6. Ask: "Continue to the next KE?" Before proceeding, wait for confirmation.

## Completion

After all KEs are done (or the user stops early), report:
- Total KEs annotated this session
- Path to the output file
- Any KEs skipped or still pending
