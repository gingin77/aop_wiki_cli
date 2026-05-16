#!/usr/bin/env python3
"""Parse and merge the LLM groupings output with the manually curated review CSV.

Usage:
    uv run python annotation_scripts/process_manual_curations.py \
        --llm-file outputs_for_vc/ke_groupings/05-07-2026_with_updated_prompts_200_NA_50/ke_similar_events_05-07-2026_pass2.json \
        --mc-file "inputs/manual_curations/KE groupings manual review - ALL_GROUPS.csv"
"""

import argparse
import csv
import json
import sys
import copy
from datetime import date
from pathlib import Path

from src.utilities.helpers import insert_after


TYPE_TO_BUCKET: dict[str, str] = {
    "merge": "events_to_merge",
    "soda": "soda_events",
    "same_object_different_process": "same_object_different_process_events",
    "similar_event_different_biological_context": "similar_event_different_biological_context_events",
}


def parse_manual_curations(csv_path: Path) -> list[dict]:
    """Read the review CSV and return one record per group.

    Each record contains:
      group_name            — snake_case group key
      group_type            — merge / soda / same_object_different_process / ...
      rating_pass2          — value from "Rating on Pass 2" column
      comment_pass2         — value from "Comment on Group - Pass 2" column
    """
    records: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            group_name = row.get("group_name", "").strip()
            if not group_name:
                continue  # skip blank rows
            records.append({
                "group_name": group_name,
                "group_type": row.get("group_type", "").strip(),
                "rating_pass2": row.get("Rating on Pass 2", "").strip(),
                "comment_pass2": row.get("Comment on Group - Pass 2", "").strip(),
            })
    return records

def export_manual_curations_to_json(mcs, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(mcs, f, indent=2)
    print(f"Written to: {out_path}")

def integrate_mcs_with_llm_annotations(mcs: list[dict], llm_annotations: dict) -> dict:
    """Merge manual curation ratings/comments into a copy of the LLM annotations dict.

    For each MC record the matching group in the appropriate LLM bucket receives
    two new fields:
      manual_rating  — value from rating_pass2
      eval_comment   — value from comment_pass2

    Groups present in the LLM output but absent from the MCs are left unchanged.
    MC records whose group_name or group_type cannot be matched are skipped with
    a warning.
    """
    result = copy.deepcopy(llm_annotations)

    for mc in mcs:
        group_type = mc.get("group_type", "")
        group_name = mc.get("group_name", "")
        bucket_key = TYPE_TO_BUCKET.get(group_type)

        if bucket_key is None:
            print(f"Warning: unknown group_type {group_type!r} for {group_name!r}, skipping.", file=sys.stderr)
            continue

        bucket = result.get(bucket_key, {})
        if group_name not in bucket:
            # If processing an LLM file from pass 2, with a manual curation file that includes
            # new groups generated during pass 3, these Warning messages can be expected.
            print(f"Warning: group {group_name!r} not found in {bucket_key}, skipping.", file=sys.stderr)
            continue

        bucket[group_name]["manual_rating"] = mc.get("rating_pass2", "")
        bucket[group_name]["eval_comment"] = mc.get("comment_pass2", "")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse and merge the LLM groupings output with the manually curated review CSV."
    )
    parser.add_argument(
        "--llm-file",
        required=True,
        metavar="FILE",
        help="Path to the LLM pass 3 output JSON (e.g. ke_similar_events_*_pass3.json)",
    )
    parser.add_argument(
        "--mc-file",
        required=True,
        metavar="FILE",
        help="Path to the manual review CSV (e.g. 'inputs/manual_curations/KE groupings manual review - ALL_GROUPS.csv')",
    )
    parser.add_argument(
        "--json-out",
        metavar="FILE",
        help="Write parsed records to this JSON file",
    )
    args = parser.parse_args()

    llm_path = Path(args.llm_file)
    mc_path = Path(args.mc_file)
    for label, path in (("llm_file", llm_path), ("mc_file", mc_path)):
        if not path.exists():
            print(f"Error: file not found ({label}): {path}", file=sys.stderr)
            sys.exit(1)

    manual_curations = parse_manual_curations(mc_path)
    print(f"Parsed {len(manual_curations)} group manual_curations.")

    today = date.today().strftime("%m-%d-%Y")
    if args.json_out:
        tmp_out_path = Path(args.json_out)
    else:
        tmp_out_path = Path(f"outputs/ke_groupings/manual_review_outputs/{today}_manual_curations.json")

    export_manual_curations_to_json(manual_curations, tmp_out_path)

    # Integrate manual curations with LLM curations for upload.
    with open(llm_path) as f:
        llm_data = json.load(f)

    integrated = integrate_mcs_with_llm_annotations(manual_curations, llm_data)
    integrated["metadata"] = insert_after(
        integrated["metadata"],
        "source_cache",
        "llm_annotation_file", args.llm_file
    )
    
    integrated["metadata"] = insert_after(
        integrated["metadata"],
        "llm_annotation_file",
        "manual_annotation_file", args.mc_file
    )

    integrated_annotations_output_path = Path(
        f"outputs/ke_groupings/manual_review_outputs/{today}_integrated_llm_and_manual_annotations.json"
    )
    integrated_annotations_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(integrated_annotations_output_path, "w") as f:
        json.dump(integrated, f, indent=2)
    print(f"Integrated annotations written to: {integrated_annotations_output_path}")

if __name__ == "__main__":
    main()
