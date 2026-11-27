---
name: annotate-kes
description: Interactively annotate Key Events (KEs) with bio-ontology terms, one KE at a time, collecting the user's feedback after each KE. Use when the user asks to annotate an AOP's Key Events (e.g. "annotate AOP 173") or a set of KEs, or invokes /annotate-kes. Takes an AOP ID as its argument, or a comma-separated list of KE IDs.
---

# Interactive KE annotation

The skill argument is either an AOP ID (call it `<aop_id>` below) or a
comma-separated list of KE IDs. With a KE-ID list, skip the AOP listing in
setup, use `--ke-id <ke_id>` per KE exactly as below (dropping `--aop`), and
treat the given list as the pending set. (Non-interactive cluster runs can use
`--ke-ids <id,id,...>` directly.)

## Setup

1. Find the most recent cache date under outputs/cache/ (list dirs, pick the latest).
2. Run the list command to show which KEs are pending vs. already annotated in the shared store:
   `uv run python -m aop_wiki_cli.annotation_scripts.annotate_ke --aop <aop_id> --date <cache_date>`

## Per-KE loop

For each pending KE (in order):

1. Tell the user which KE you are about to annotate (ID and title).
2. Run (with assay extraction, so each KE finishes fully annotated and stamped;
   assays are off by default otherwise):
   `uv run python -m aop_wiki_cli.annotation_scripts.annotate_ke --aop <aop_id> --ke-id <ke_id> --with-assays --date <cache_date>`
3. Present the ANNOTATION SUMMARY from the output to the user in a readable format.
   If any phenotype is flagged with `⚠ needs_review`, highlight it explicitly.
4. Ask the user: "Any comments or corrections for this KE? (type your comment, or press Enter to continue)"
5. If the user provides a comment, run:
   `uv run python -m aop_wiki_cli.annotation_scripts.annotate_ke --aop <aop_id> --ke-id <ke_id> --add-comment "<comment>"`
   You may add multiple comments — keep asking until the user is done.
6. Ask: "Continue to the next KE?" Before proceeding, wait for confirmation.

## Completion

After all KEs are done (or the user stops early):

1. Report:
   - Total KEs annotated this session
   - Path to the shared store (outputs_for_vc/annotations/ke_annotations.json)
   - Any KEs skipped or still pending

2. Run the comparison script:
   `uv run python -m aop_wiki_cli.annotation_scripts.compare_ke_annotations`
   Present a brief summary of the output: how many KEs have divergent fields vs. new-only fields, and the output CSV path.
