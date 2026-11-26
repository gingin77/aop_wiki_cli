#!/usr/bin/env python3
"""Compare two KE grouping runs produced at different times.

Unlike compare_pass_2_vs_pass_3.py (which compares pass 2 vs pass 3 of a single
run and can match on group_key), group keys are LLM-generated per run and drift
between runs. So this script matches groups across runs by their MEMBER EVENTS
(Jaccard overlap of member IDs), not by key. That makes it usable to see how a
May run and a November run diverged — and to re-key manual curations from one
run to the other.

Each group is classified from run A's perspective as:
  identical  — exact same member set exists in run B
  changed    — best-overlap B group shares >= --min-overlap members (reports
               which members were added/removed and whether the type changed)
  dropped    — no B group shares >= --min-overlap of its members
and B groups that no A group matches are reported as `new`. Groups whose members
spread across several B groups are flagged as splits; several A groups collapsing
onto one B group are flagged as merges.

Runs are given by date (resolved under <groupings-dir>/<date>/) or by explicit
file. The group-shape helpers mirror collect_similar_events.py's output format.

Usage:
    # By date (defaults to the pass 3 snapshot of each run)
    uv run python annotation_scripts/compare_grouping_runs.py \
        --date-a 05-07-2026 --date-b 11-25-2026 \
        --crosswalk-csv outputs/ke_groupings/may_to_nov_crosswalk.csv

    # Explicit files, and a full JSON dump of the comparison
    uv run python annotation_scripts/compare_grouping_runs.py \
        --file-a <...>/ke_similar_events_05-07-2026_pass3.json \
        --file-b <...>/ke_similar_events_11-25-2026_pass3.json \
        --json-out outputs/ke_groupings/may_vs_nov.json
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

DEFAULT_GROUPINGS_DIR = Path("outputs_for_vc/ke_groupings")

# Maps logical type name → top-level JSON key (mirrors collect_similar_events.py).
TYPE_KEYS: dict[str, str] = {
    "merge": "events_to_merge",
    "soda": "soda_events",
    "same_object_different_process": "same_object_different_process_events",
    "similar_event_different_biological_context": "similar_event_different_biological_context_events",
}


# ---------------------------------------------------------------------------
# Run resolution + group extraction (group-shape mirrors collect_similar_events.py)
# ---------------------------------------------------------------------------

def resolve_run_file(date_str: str, pass_num: int, base_dir: Path) -> Path:
    """Resolve <base_dir>/<date_str>/ke_similar_events_<date_str>_pass<pass_num>.json."""
    group_dir = base_dir / date_str
    target = group_dir / f"ke_similar_events_{date_str}_pass{pass_num}.json"
    if target.exists():
        return target
    if not group_dir.is_dir():
        sys.exit(f"Error: no groupings directory for date {date_str!r}: {group_dir}")
    available = sorted(p.name for p in group_dir.glob(f"ke_similar_events_{date_str}_pass*.json"))
    hint = f" Available: {', '.join(available)}" if available else " No pass snapshots found there."
    sys.exit(f"Error: {target.name} not found in {group_dir}.{hint}")


def _member_ids(group_dict: dict, type_key: str) -> set[str]:
    """events_to_merge uses merged_event_titles {id: title}; others use event_ids [id, ...]."""
    if type_key == "events_to_merge":
        return set(group_dict.get("merged_event_titles", {}).keys())
    return {str(i) for i in group_dict.get("event_ids", [])}


def _titles(group_dict: dict, type_key: str) -> dict[str, str]:
    if type_key == "events_to_merge":
        return group_dict.get("merged_event_titles", {})
    return group_dict.get("event_titles", {})


def extract_groups(data: dict) -> dict[str, dict]:
    """Flatten the four type buckets into {group_key: {type, member_ids, titles}}."""
    result: dict[str, dict] = {}
    for gtype, top_key in TYPE_KEYS.items():
        for group_key, group_dict in data.get(top_key, {}).items():
            key = group_key
            n = 2
            while key in result:  # same key reused across buckets — keep both
                key = f"{group_key}_{n}"
                n += 1
            result[key] = {
                "type": gtype,
                "member_ids": _member_ids(group_dict, top_key),
                "titles": _titles(group_dict, top_key),
            }
    return result


def _sort_ids(ids) -> list[str]:
    return sorted(ids, key=lambda x: (0, int(x), "") if str(x).isdigit() else (1, 0, str(x)))


def _all_grouped_ids(groups: dict[str, dict]) -> set[str]:
    out: set[str] = set()
    for g in groups.values():
        out.update(g["member_ids"])
    return out


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def compare_runs(groups_a: dict[str, dict], groups_b: dict[str, dict], min_overlap: float) -> dict:
    """Match A groups to B groups by member overlap and classify each."""
    matches: list[dict] = []
    best_b_for_a: dict[str, str] = {}

    for ka, ga in groups_a.items():
        a_ids = ga["member_ids"]
        best_kb, best_j = None, 0.0
        for kb, gb in groups_b.items():
            j = _jaccard(a_ids, gb["member_ids"])
            if j > best_j:
                best_j, best_kb = j, kb
        # how many B groups share ANY member with this A group (split signal)
        spread = sum(1 for gb in groups_b.values() if a_ids & gb["member_ids"])

        if best_kb is not None and best_j >= min_overlap:
            gb = groups_b[best_kb]
            best_b_for_a[ka] = best_kb
            identical = a_ids == gb["member_ids"]
            matches.append({
                "a_key": ka, "a_type": ga["type"], "a_size": len(a_ids),
                "b_key": best_kb, "b_type": gb["type"], "b_size": len(gb["member_ids"]),
                "overlap": round(best_j, 3),
                "status": "identical" if identical else "changed",
                "type_changed": ga["type"] != gb["type"],
                "added_in_b": _sort_ids(gb["member_ids"] - a_ids),
                "removed_from_a": _sort_ids(a_ids - gb["member_ids"]),
                "is_split": spread > 1 and not identical,
            })
        else:
            matches.append({
                "a_key": ka, "a_type": ga["type"], "a_size": len(a_ids),
                "b_key": None, "b_type": None, "b_size": 0,
                "overlap": round(best_j, 3),
                "status": "dropped",
                "type_changed": False,
                "added_in_b": [], "removed_from_a": _sort_ids(a_ids),
                "is_split": spread > 1,
                "nearest_b_key": best_kb,  # best partial match, for reference
            })

    matched_b = set(best_b_for_a.values())
    new_in_b: list[dict] = []
    for kb, gb in groups_b.items():
        if kb in matched_b:
            continue
        # best A overlap, for reference
        best_ka, best_j = None, 0.0
        for ka, ga in groups_a.items():
            j = _jaccard(gb["member_ids"], ga["member_ids"])
            if j > best_j:
                best_j, best_ka = j, ka
        new_in_b.append({
            "b_key": kb, "b_type": gb["type"], "b_size": len(gb["member_ids"]),
            "member_ids": _sort_ids(gb["member_ids"]),
            "nearest_a_key": best_ka, "nearest_overlap": round(best_j, 3),
        })

    # merges: one B group is the best match for several A groups
    b_hit_count: dict[str, int] = {}
    for kb in best_b_for_a.values():
        b_hit_count[kb] = b_hit_count.get(kb, 0) + 1
    merges = {kb: n for kb, n in b_hit_count.items() if n > 1}

    grouped_a = _all_grouped_ids(groups_a)
    grouped_b = _all_grouped_ids(groups_b)

    summary = {
        "a_total_groups": len(groups_a),
        "b_total_groups": len(groups_b),
        "identical": sum(1 for m in matches if m["status"] == "identical"),
        "changed": sum(1 for m in matches if m["status"] == "changed"),
        "dropped_only_in_a": sum(1 for m in matches if m["status"] == "dropped"),
        "new_only_in_b": len(new_in_b),
        "merges_detected": len(merges),
        "splits_detected": sum(1 for m in matches if m.get("is_split")),
        "a_total_grouped_events": len(grouped_a),
        "b_total_grouped_events": len(grouped_b),
        "events_grouped_in_both": len(grouped_a & grouped_b),
        "events_grouped_only_in_a": len(grouped_a - grouped_b),
        "events_grouped_only_in_b": len(grouped_b - grouped_a),
    }
    return {"summary": summary, "matches": matches, "new_in_b": new_in_b, "merges": merges}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(result: dict, label_a: str, label_b: str, min_overlap: float) -> None:
    s = result["summary"]
    print("=" * 72)
    print(f"Grouping comparison:  A={label_a}   B={label_b}   (min overlap {min_overlap})")
    print("=" * 72)
    print(f"  Groups:  A={s['a_total_groups']}  B={s['b_total_groups']}")
    print(f"  identical           : {s['identical']}")
    print(f"  changed             : {s['changed']}")
    print(f"  dropped (only in A) : {s['dropped_only_in_a']}")
    print(f"  new (only in B)     : {s['new_only_in_b']}")
    print(f"  merges detected     : {s['merges_detected']}   (A groups collapsing onto one B group)")
    print(f"  splits detected     : {s['splits_detected']}   (A group spread across several B groups)")
    print()
    print(f"  Grouped events:  A={s['a_total_grouped_events']}  B={s['b_total_grouped_events']}")
    print(f"    in both run groupings : {s['events_grouped_in_both']}")
    print(f"    grouped only in A     : {s['events_grouped_only_in_a']}")
    print(f"    grouped only in B     : {s['events_grouped_only_in_b']}")
    print("=" * 72)


CROSSWALK_COLUMNS = [
    "status", "a_key", "a_type", "a_size",
    "b_key", "b_type", "b_size", "overlap",
    "type_changed", "is_split", "added_in_b", "removed_from_a",
]


def write_crosswalk_csv(result: dict, out_path: Path) -> None:
    """One row per A group (its best B match or 'dropped'), plus 'new' B groups."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CROSSWALK_COLUMNS)
        writer.writeheader()
        for m in result["matches"]:
            writer.writerow({
                "status": m["status"],
                "a_key": m["a_key"], "a_type": m["a_type"], "a_size": m["a_size"],
                "b_key": m["b_key"] or "", "b_type": m["b_type"] or "", "b_size": m["b_size"],
                "overlap": m["overlap"],
                "type_changed": m["type_changed"], "is_split": m.get("is_split", False),
                "added_in_b": ", ".join(m["added_in_b"]),
                "removed_from_a": ", ".join(m["removed_from_a"]),
            })
        for n in result["new_in_b"]:
            writer.writerow({
                "status": "new", "a_key": "", "a_type": "", "a_size": "",
                "b_key": n["b_key"], "b_type": n["b_type"], "b_size": n["b_size"],
                "overlap": n["nearest_overlap"], "type_changed": "", "is_split": "",
                "added_in_b": ", ".join(n["member_ids"]), "removed_from_a": "",
            })
    print(f"Crosswalk CSV written to: {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_side(side: str, date_str, file_str, pass_num: int, base_dir: Path) -> tuple[Path, str]:
    """Return (path, label) for one run side. label is the date or the file stem."""
    if file_str:
        path = Path(file_str)
        if not path.exists():
            sys.exit(f"Error: --file-{side} not found: {path}")
        m = re.search(r"(\d{2}-\d{2}-\d{4})", path.name)
        return path, (m.group(1) if m else path.stem)
    path = resolve_run_file(date_str, pass_num, base_dir)
    return path, date_str


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two KE grouping runs by member overlap (keys drift between runs).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src_a = parser.add_mutually_exclusive_group(required=True)
    src_a.add_argument("--date-a", metavar="MM-DD-YYYY", help="Run A by date")
    src_a.add_argument("--file-a", metavar="FILE", help="Run A grouping JSON (explicit)")
    src_b = parser.add_mutually_exclusive_group(required=True)
    src_b.add_argument("--date-b", metavar="MM-DD-YYYY", help="Run B by date")
    src_b.add_argument("--file-b", metavar="FILE", help="Run B grouping JSON (explicit)")

    parser.add_argument("--pass", dest="pass_num", type=int, choices=(2, 3), default=3,
                        help="Snapshot to use when resolving by date (default: 3)")
    parser.add_argument("--groupings-dir", metavar="DIR", default=str(DEFAULT_GROUPINGS_DIR),
                        help=f"Base dir holding <date> folders (default: {DEFAULT_GROUPINGS_DIR})")
    parser.add_argument("--min-overlap", type=float, default=0.5,
                        help="Jaccard threshold to count two groups as matched (default: 0.5)")
    parser.add_argument("--crosswalk-csv", metavar="FILE", help="Write the A→B group crosswalk CSV")
    parser.add_argument("--json-out", metavar="FILE", help="Write the full comparison as JSON")
    args = parser.parse_args()

    base_dir = Path(args.groupings_dir)
    path_a, label_a = _resolve_side("a", args.date_a, args.file_a, args.pass_num, base_dir)
    path_b, label_b = _resolve_side("b", args.date_b, args.file_b, args.pass_num, base_dir)
    print(f"Run A: {path_a}")
    print(f"Run B: {path_b}\n")

    with open(path_a) as f:
        data_a = json.load(f)
    with open(path_b) as f:
        data_b = json.load(f)

    result = compare_runs(extract_groups(data_a), extract_groups(data_b), args.min_overlap)
    result["run_a"] = {"label": label_a, "file": str(path_a)}
    result["run_b"] = {"label": label_b, "file": str(path_b)}

    print_report(result, label_a, label_b, args.min_overlap)

    if args.crosswalk_csv:
        write_crosswalk_csv(result, Path(args.crosswalk_csv))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Full comparison JSON written to: {out}")


if __name__ == "__main__":
    main()
