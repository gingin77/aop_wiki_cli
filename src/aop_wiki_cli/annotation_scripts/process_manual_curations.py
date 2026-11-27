#!/usr/bin/env python3
"""Parse and merge the LLM groupings output with the manually curated review CSV.

A review CSV is tied to the grouping run it was curated against — group keys
are LLM-generated per run and drift between runs, so ratings keyed to one
run's groups do not match another's. The committed
ke_groupings_manual_review_05-07-2026_ALL_GROUPS.csv was curated against the
05-07-2026 run; to apply its ratings to a newer run, re-key them first via
compare_grouping_runs.py's member-overlap crosswalk.

Pass a grouping run by date (resolved under outputs_for_vc/ke_groupings/<date>/),
or point at an LLM file explicitly:

Usage:
    # By date — resolves ke_similar_events_<date>_pass3.json in the groupings dir
    uv run python -m aop_wiki_cli.annotation_scripts.process_manual_curations \
        --date 11-25-2026 \
        --mc-file "inputs/manual_curations/ke_groupings_manual_review_05-07-2026_ALL_GROUPS.csv"

    # Choose the pass 2 snapshot instead
    uv run python -m aop_wiki_cli.annotation_scripts.process_manual_curations \
        --date 11-25-2026 --pass 2 --mc-file "inputs/manual_curations/....csv"

    # Explicit LLM file (overrides --date resolution)
    uv run python -m aop_wiki_cli.annotation_scripts.process_manual_curations \
        --llm-file outputs_for_vc/ke_groupings/05-07-2026_.../ke_similar_events_05-07-2026_pass2.json \
        --mc-file "inputs/manual_curations/....csv"
"""

import argparse
import copy
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

from aop_wiki_cli.utilities.helpers import insert_after


TYPE_TO_BUCKET: dict[str, str] = {
    "merge": "events_to_merge",
    "soda": "soda_events",
    "same_object_different_process": "same_object_different_process_events",
    "similar_event_different_biological_context": "similar_event_different_biological_context_events",
}

DEFAULT_GROUPINGS_DIR = Path("outputs_for_vc/ke_groupings")
MANUAL_REVIEW_OUTPUT_DIR = Path("outputs/ke_groupings/manual_review_outputs")
_LLM_NAME_RE = re.compile(r"ke_similar_events_(\d{2}-\d{2}-\d{4})_pass\d+\.json$")


def resolve_llm_file(date_str: str, pass_num: int, base_dir: Path) -> Path:
    """Resolve the grouping snapshot for <date_str> under base_dir/<date_str>/.

    Returns the path to ke_similar_events_<date_str>_pass<pass_num>.json. Raises
    SystemExit with a helpful message if the directory or that snapshot is
    missing, listing the snapshots that are present.
    """
    group_dir = base_dir / date_str
    target = group_dir / f"ke_similar_events_{date_str}_pass{pass_num}.json"
    if target.exists():
        return target
    if not group_dir.is_dir():
        sys.exit(f"Error: no groupings directory for date {date_str!r}: {group_dir}")
    available = sorted(p.name for p in group_dir.glob(f"ke_similar_events_{date_str}_pass*.json"))
    hint = f" Available: {', '.join(available)}" if available else " No pass snapshots found there."
    sys.exit(f"Error: {target.name} not found in {group_dir}.{hint}")


def _run_date_for(args, llm_path: Path) -> str:
    """Date used to stamp output filenames: --date, else parsed from the LLM
    filename, else today."""
    if args.date:
        return args.date
    m = _LLM_NAME_RE.search(llm_path.name)
    return m.group(1) if m else date.today().strftime("%m-%d-%Y")


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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--date",
        metavar="MM-DD-YYYY",
        help="Grouping run date; resolves the LLM file under "
             "<groupings-dir>/<date>/ke_similar_events_<date>_pass<N>.json",
    )
    source.add_argument(
        "--llm-file",
        metavar="FILE",
        help="Explicit path to an LLM grouping JSON (overrides --date resolution)",
    )
    parser.add_argument(
        "--pass",
        dest="pass_num",
        type=int,
        choices=(2, 3),
        default=3,
        help="Which grouping snapshot to use with --date (default: 3)",
    )
    parser.add_argument(
        "--groupings-dir",
        metavar="DIR",
        default=str(DEFAULT_GROUPINGS_DIR),
        help=f"Base directory holding <date> grouping folders (default: {DEFAULT_GROUPINGS_DIR})",
    )
    parser.add_argument(
        "--mc-file",
        required=True,
        metavar="FILE",
        help="Path to the manual review CSV (e.g. 'inputs/manual_curations/ke_groupings_manual_review_05-07-2026_ALL_GROUPS.csv')",
    )
    parser.add_argument(
        "--json-out",
        metavar="FILE",
        help="Write parsed records to this JSON file",
    )
    args = parser.parse_args()

    if args.llm_file:
        llm_path = Path(args.llm_file)
    else:
        llm_path = resolve_llm_file(args.date, args.pass_num, Path(args.groupings_dir))
    print(f"LLM grouping file: {llm_path}")

    mc_path = Path(args.mc_file)
    for label, path in (("llm_file", llm_path), ("mc_file", mc_path)):
        if not path.exists():
            print(f"Error: file not found ({label}): {path}", file=sys.stderr)
            sys.exit(1)

    run_date = _run_date_for(args, llm_path)

    manual_curations = parse_manual_curations(mc_path)
    print(f"Parsed {len(manual_curations)} group manual_curations.")

    if args.json_out:
        tmp_out_path = Path(args.json_out)
    else:
        tmp_out_path = MANUAL_REVIEW_OUTPUT_DIR / f"{run_date}_manual_curations.json"

    export_manual_curations_to_json(manual_curations, tmp_out_path)

    # Integrate manual curations with LLM curations for upload.
    with open(llm_path) as f:
        llm_data = json.load(f)

    integrated = integrate_mcs_with_llm_annotations(manual_curations, llm_data)
    integrated.setdefault("metadata", {})
    integrated["metadata"] = insert_after(
        integrated["metadata"],
        "source_cache",
        "llm_annotation_file", str(llm_path)
    )

    integrated["metadata"] = insert_after(
        integrated["metadata"],
        "llm_annotation_file",
        "manual_annotation_file", str(mc_path)
    )

    integrated_annotations_output_path = (
        MANUAL_REVIEW_OUTPUT_DIR / f"{run_date}_integrated_llm_and_manual_annotations.json"
    )
    integrated_annotations_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(integrated_annotations_output_path, "w") as f:
        json.dump(integrated, f, indent=2)
    print(f"Integrated annotations written to: {integrated_annotations_output_path}")

if __name__ == "__main__":
    main()
