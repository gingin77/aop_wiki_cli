"""
Annotate Key Events for a given AOP using the BioPortal + Claude workflow.

Designed to be driven interactively by Claude Code one KE at a time:
  - Use --ke-id to annotate a single KE and append to the output file.
  - Omit --ke-id to list all KEs for the AOP without annotating.

Claude Code drives the loop: annotate one KE, show results, collect user
comments via conversation, write comments to the output file, then move on.

Usage:
    # List KEs for an AOP (no annotation)
    uv run python scripts/annotate_aop_ke_ontology.py --aop 173 --date 04-28-2026

    # Annotate a single KE and append to output file
    uv run python scripts/annotate_aop_ke_ontology.py --aop 173 --ke-id 68 --date 04-28-2026

    # Add comments to an already-annotated KE in the output file
    uv run python scripts/annotate_aop_ke_ontology.py --aop 173 --ke-id 68 --add-comment "Needs manual review"
"""

import argparse
import datetime
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(__file__))
from test_bioportal_based_ke_title_annotation import (
    annotate_ke,
    _flat_ref_comments,
)

CACHE_DIR_ROOT = "outputs/cache"
OUTPUT_DIR = "outputs/ke_ontology_suggestions"


def _cache_file(date_str: str) -> str:
    return os.path.join(CACHE_DIR_ROOT, date_str, f"all_events_{date_str}.json")


def _output_path(aop_id: str) -> str:
    return os.path.join(OUTPUT_DIR, f"ke_annotations_for_aop_{aop_id}.json")


def _load_output(aop_id: str) -> dict:
    path = _output_path(aop_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_output(aop_id: str, all_annotations: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = _output_path(aop_id)
    with open(path, "w") as f:
        json.dump(all_annotations, f, indent=2)
    return path


def list_aop_kes(aop_id: str, cache_file: str) -> list[tuple[str, str]]:
    """Return [(ke_id, title), ...] for all KEs in the AOP, sorted by KE ID."""
    with open(cache_file) as f:
        events = json.load(f)
    kes = [
        (k, v.get("title", ""))
        for k, v in events.items()
        if aop_id in [str(x) for x in v.get("aop_ids", [])]
    ]
    return sorted(kes, key=lambda x: int(x[0]))


def annotate_single_ke(
    aop_id: str,
    ke_id: str,
    cache_file: str,
    reference_file: str | None = None,
) -> str:
    """
    Annotate one KE and append/update it in the AOP output file.
    Prints a structured summary at the end for Claude Code to relay to the user.
    Returns the output file path.
    """
    api_key = os.environ.get("BIOPORTAL_API_KEY")
    if not api_key:
        raise EnvironmentError("BIOPORTAL_API_KEY not set — add it to .env")

    with open(cache_file) as f:
        events = json.load(f)

    if ke_id not in events:
        print(f"KE {ke_id} not found in cache.")
        sys.exit(1)

    reference: dict = {}
    if reference_file and os.path.exists(reference_file):
        with open(reference_file) as f:
            reference = json.load(f)

    title = events[ke_id].get("title", "")
    description = events[ke_id].get("description", "")
    ref_ke = reference.get(ke_id)

    annotation = annotate_ke(ke_id, title, api_key, description=description, ref_ke=ref_ke)

    ref_comments = _flat_ref_comments((ref_ke or {}).get("comments"))
    carried = [f"{c} [carried from reference]" for c in ref_comments]
    annotation["comments"] = {"carried": carried, "new": []}

    ref_top_keys = {k for k, v in (ref_ke or {}).items() if v is not None}
    new_fields: list[str] = []
    for key, val in annotation.items():
        if key in ("ke_id", "title", "comments", "ecs_annotations"):
            continue
        if val is not None and key not in ref_top_keys:
            new_fields.append(key)
    for subj in annotation.get("ecs_annotations", []):
        ref_subj = next(
            (s for s in (ref_ke or {}).get("ecs_annotations", [])
             if s.get("subject") == subj.get("subject")),
            {},
        )
        for field in ("biological_object", "biological_process", "phenotype"):
            if subj.get(field) is not None and ref_subj.get(field) is None:
                label = f"ecs_annotations[{subj['subject']!r}].{field}"
                if label not in new_fields:
                    new_fields.append(label)
    if new_fields:
        annotation["newly_annotated_fields"] = new_fields

    all_annotations = _load_output(aop_id)
    all_annotations[ke_id] = annotation
    out_path = _save_output(aop_id, all_annotations)

    # Structured summary for Claude Code to present to the user
    print("\n" + "=" * 60)
    print(f"ANNOTATION SUMMARY — KE {ke_id}: {title}")
    print("=" * 60)
    print(f"  biological_organization: {annotation.get('biological_organization')}")
    cell = annotation.get("cell_term")
    organ = annotation.get("organ_term")
    print(f"  cell_term:  {cell.get('label') if cell else None}")
    print(f"  organ_term: {organ.get('label') if organ else None}")
    for subj in annotation.get("ecs_annotations", []):
        print(f"\n  subject: {subj['subject']!r}")
        action = subj.get("biological_action", {})
        print(f"    biological_action:  {action.get('term') if action else None}")
        obj = subj.get("biological_object")
        proc = subj.get("biological_process")
        phen = subj.get("phenotype")
        print(f"    biological_object:  {obj.get('label') if obj else None}")
        print(f"    biological_process: {proc.get('label') if proc else None}")
        print(f"    phenotype:          {phen.get('label') if phen else None}")
    if new_fields:
        print(f"\n  Newly annotated: {new_fields}")
    if ref_comments:
        print(f"\n  Carried comments: {ref_comments}")
    print(f"\nSaved to {out_path}")
    print("=" * 60)

    return out_path


def add_comment(aop_id: str, ke_id: str, comment: str) -> str:
    """Append a comment to an already-annotated KE in the output file."""
    all_annotations = _load_output(aop_id)
    if ke_id not in all_annotations:
        print(f"KE {ke_id} not found in {_output_path(aop_id)} — annotate it first.")
        sys.exit(1)
    all_annotations[ke_id].setdefault("comments", {"carried": [], "new": []})
    all_annotations[ke_id]["comments"]["new"].append(comment)
    out_path = _save_output(aop_id, all_annotations)
    print(f"Comment added to KE {ke_id}. Saved to {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Annotate KEs for an AOP (one at a time)")
    parser.add_argument("--aop", required=True, help="AOP ID (e.g. 173)")
    parser.add_argument("--ke-id", default=None, help="Annotate a single KE by ID")
    parser.add_argument("--add-comment", default=None, help="Append a comment to a KE (requires --ke-id)")
    parser.add_argument(
        "--date",
        default=datetime.date.today().strftime("%m-%d-%Y"),
        help="Cache date MM-DD-YYYY (default: today)",
    )
    parser.add_argument("--reference", default=None, help="Path to reference JSON file")
    args = parser.parse_args()

    cache = _cache_file(args.date)
    if not os.path.exists(cache):
        print(f"Cache file not found: {cache}")
        sys.exit(1)

    # Add a comment to an existing annotation
    if args.add_comment:
        if not args.ke_id:
            print("--add-comment requires --ke-id")
            sys.exit(1)
        add_comment(args.aop, args.ke_id, args.add_comment)
        return

    # List mode: no --ke-id given
    if args.ke_id is None:
        kes = list_aop_kes(args.aop, cache)
        if not kes:
            print(f"No KEs found for AOP {args.aop}")
            sys.exit(1)
        existing = _load_output(args.aop)
        print(f"\nAOP {args.aop} — {len(kes)} KEs")
        print(f"Output file: {_output_path(args.aop)}")
        print()
        for ke_id, title in kes:
            status = "✓ done" if ke_id in existing else "pending"
            print(f"  [{status}] KE {ke_id}: {title}")
        return

    # Single-KE annotation mode
    ref = args.reference
    if ref is None:
        default_ref = os.path.join(OUTPUT_DIR, f"ke_suggestions_{args.date}.json")
        if os.path.exists(default_ref):
            ref = default_ref

    annotate_single_ke(args.aop, args.ke_id, cache, reference_file=ref)


if __name__ == "__main__":
    main()
