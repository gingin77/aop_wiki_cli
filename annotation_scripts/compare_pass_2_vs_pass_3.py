#!/usr/bin/env python3
"""Compare pass 2 and pass 3 outputs from collect_similar_events.py.

Usage:
uv run python annotation_scripts/compare_pass_2_vs_pass_3.py \
outputs_for_vc/ke_groupings/05-07-2026_with_updated_prompts_200_NA_50/ke_similar_events_05-07-2026_pass2.json \
outputs_for_vc/ke_groupings/05-07-2026_with_updated_prompts_200_NA_50/ke_similar_events_05-07-2026_pass3.json \
--changes-json outputs_for_vc/ke_groupings/05-07-2026_with_updated_prompts_200_NA_50/changes_pass2_to_pass3.json \
--changes-csv  outputs_for_vc/ke_groupings/05-07-2026_with_updated_prompts_200_NA_50/changes_pass2_to_pass3.csv

    # Optionally write full comparison to JSON:
    uv run python annotation_scripts/compare_pass_2_vs_pass_3.py \\
        ..._pass2.json ..._pass3.json --json-out comparison.json
"""

import argparse
import csv
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maps logical type name → top-level JSON key in the output files
TYPE_KEYS: dict[str, str] = {
    "merge": "events_to_merge",
    "soda": "soda_events",
    "same_object_different_process": "same_object_different_process_events",
    "similar_event_different_biological_context": "similar_event_different_biological_context_events",
}

TYPE_LABELS: dict[str, str] = {
    "merge": "Merge",
    "soda": "SODA",
    "same_object_different_process": "Same-object different process",
    "similar_event_different_biological_context": "Similar event, different context",
}


# ---------------------------------------------------------------------------
# Helpers — normalise the two different group shapes
# ---------------------------------------------------------------------------

def _member_ids(group_dict: dict, type_key: str) -> set[str]:
    """Return the set of member IDs for one group entry.

    events_to_merge uses merged_event_titles: {id: title};
    the other three types use event_ids: [id, ...].
    """
    if type_key == "events_to_merge":
        return set(group_dict.get("merged_event_titles", {}).keys())
    return {str(i) for i in group_dict.get("event_ids", [])}


def _titles(group_dict: dict, type_key: str) -> dict[str, str]:
    if type_key == "events_to_merge":
        return group_dict.get("merged_event_titles", {})
    return group_dict.get("event_titles", {})


def _aop_check_summary(shared_aop_check: dict) -> str:
    """Format shared_aop_check as a compact string for CSV display."""
    if not shared_aop_check:
        return ""
    statement = shared_aop_check.get("statement", "")
    non_ofa = shared_aop_check.get("non_open_for_adoption_aops_holding_grouped_events", [])
    ofa = shared_aop_check.get("open_for_adoption_aops_holding_grouped_events", [])
    parts = [statement] if statement else []
    if non_ofa:
        parts.append("AOPs: " + ", ".join(non_ofa))
    if ofa:
        parts.append("OFA AOPs: " + ", ".join(ofa))
    return "\n".join(parts)


def _aop_count(shared_aop_check: dict) -> str:
    """Return total co-occurring AOP count as a string, or empty string if none."""
    non_ofa = shared_aop_check.get("non_open_for_adoption_aops_holding_grouped_events", [])
    ofa = shared_aop_check.get("open_for_adoption_aops_holding_grouped_events", [])
    total = len(non_ofa) + len(ofa)
    return str(total) if total > 0 else ""


def _aop_ids_str(shared_aop_check: dict) -> str:
    """Return comma-separated AOP IDs (non-OFA first, then OFA), or empty string."""
    non_ofa = shared_aop_check.get("non_open_for_adoption_aops_holding_grouped_events", [])
    ofa = shared_aop_check.get("open_for_adoption_aops_holding_grouped_events", [])
    return ", ".join(list(non_ofa) + list(ofa))


def _extract_all_groups(data: dict) -> dict[str, dict]:
    """Flatten all four type buckets into {group_key: normalised_group}."""
    result: dict[str, dict] = {}
    for gtype, top_key in TYPE_KEYS.items():
        for group_key, group_dict in data.get(top_key, {}).items():
            key = group_key
            if key in result:
                # Same group_key reused in another bucket — possible in older
                # output files whose keys were only deduped within a type.
                # Suffix it so neither group is silently dropped here.
                n = 2
                while f"{group_key}_{n}" in result:
                    n += 1
                key = f"{group_key}_{n}"
            result[key] = {
                "type": gtype,
                "type_key": top_key,
                "member_ids": _member_ids(group_dict, top_key),
                "titles": _titles(group_dict, top_key),
                "rationale": group_dict.get("rationale", ""),
                "shared_aop_check": group_dict.get("shared_aop_check", {}),
            }
    return result


def _all_grouped_ids(groups: dict[str, dict]) -> set[str]:
    ids: set[str] = set()
    for g in groups.values():
        ids.update(g["member_ids"])
    return ids


def _sort_ids(ids: set[str]) -> list[str]:
    # Numeric IDs sort numerically and ahead of any non-numeric IDs. The leading
    # 0/1 flag keeps int and str out of the same comparison (a TypeError in Py3).
    return sorted(ids, key=lambda x: (0, int(x), "") if x.isdigit() else (1, 0, x))


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def compare(pass2: dict, pass3: dict) -> dict:
    groups2 = _extract_all_groups(pass2)
    groups3 = _extract_all_groups(pass3)

    ungrouped2: set[str] = set(pass2.get("ungrouped_processed_events", {}).keys())
    ungrouped3: set[str] = set(pass3.get("ungrouped_processed_events", {}).keys())

    ungrouped2_titles: dict[str, str] = pass2.get("ungrouped_processed_events", {})

    # --- 1. Events newly grouped by pass 3 ---
    # Were in ungrouped_processed_events after pass2, absent after pass3.
    newly_grouped_ids = ungrouped2 - ungrouped3
    newly_grouped: list[dict] = []
    for event_id in _sort_ids(newly_grouped_ids):
        assigned_to = [
            {
                "group_key": gk,
                "type": g["type"],
                "rationale": g["rationale"],
            }
            for gk, g in groups3.items()
            if event_id in g["member_ids"]
        ]
        newly_grouped.append({
            "event_id": event_id,
            "title": ungrouped2_titles.get(event_id, ""),
            "assigned_to": assigned_to,
        })

    # --- 2. Groups expanded in pass 3 ---
    # Same group_key exists in both, but pass3 has more members.
    expanded_groups: list[dict] = []
    for group_key, g3 in groups3.items():
        if group_key not in groups2:
            continue
        g2 = groups2[group_key]
        added = g3["member_ids"] - g2["member_ids"]
        if not added:
            continue
        expanded_groups.append({
            "group_key": group_key,
            "type": g3["type"],
            "pass2_count": len(g2["member_ids"]),
            "pass3_count": len(g3["member_ids"]),
            "added_ids": _sort_ids(added),
            "added_titles": {ke_id: g3["titles"].get(ke_id, "") for ke_id in added},
        })

    # --- 3. Entirely new groups created by pass 3 ---
    # Group keys present in pass3 but absent in pass2.
    keys_in_pass2 = set(groups2.keys())
    new_groups_in_pass3: list[dict] = []
    for group_key, g3 in groups3.items():
        if group_key in keys_in_pass2:
            continue
        new_groups_in_pass3.append({
            "group_key": group_key,
            "type": g3["type"],
            "member_ids": _sort_ids(g3["member_ids"]),
            "titles": g3["titles"],
            "rationale": g3["rationale"],
        })

    # --- 4. Type-level summary ---
    type_summary: list[dict] = []
    for gtype, top_key in TYPE_KEYS.items():
        p2_bucket = pass2.get(top_key, {})
        p3_bucket = pass3.get(top_key, {})
        p2_groups = len(p2_bucket)
        p3_groups = len(p3_bucket)
        p2_events = sum(len(_member_ids(gd, top_key)) for gd in p2_bucket.values())
        p3_events = sum(len(_member_ids(gd, top_key)) for gd in p3_bucket.values())
        type_summary.append({
            "type": gtype,
            "pass2_groups": p2_groups,
            "pass2_events": p2_events,
            "pass3_groups": p3_groups,
            "pass3_events": p3_events,
            "delta_groups": p3_groups - p2_groups,
            "delta_events": p3_events - p2_events,
        })

    grouped2 = _all_grouped_ids(groups2)
    grouped3 = _all_grouped_ids(groups3)

    return {
        "totals": {
            "pass2_total_grouped": len(grouped2),
            "pass3_total_grouped": len(grouped3),
            "pass2_total_ungrouped": len(ungrouped2),
            "pass3_total_ungrouped": len(ungrouped3),
            "events_newly_grouped_by_pass3": len(newly_grouped_ids),
            "groups_expanded_by_pass3": len(expanded_groups),
            "new_groups_created_by_pass3": len(new_groups_in_pass3),
        },
        "type_summary": type_summary,
        "newly_grouped_events": newly_grouped,
        "expanded_groups": expanded_groups,
        "new_groups_in_pass3": new_groups_in_pass3,
    }


# ---------------------------------------------------------------------------
# Simplified changes view (pass 2 → pass 3)
# ---------------------------------------------------------------------------

def _bullet_list(id_title_pairs: list[tuple[str, str]]) -> str:
    """Format a list of (id, title) pairs as newline-separated bullet points."""
    return "\n".join(f"• {ke_id}: {title}" for ke_id, title in id_title_pairs)


def _build_changes_records(
    result: dict,
    groups2: dict[str, dict],
    groups3: dict[str, dict],
) -> list[dict]:
    """Build one record per group for JSON/CSV export.

    Includes every pass 2 group (with any additions from pass 3 in new_events)
    plus groups created entirely by pass 3.

    Each record has:
      group_name              — the group key
      group_type              — merge / soda / same_object_different_process / ...
      pass2_events            — (id, title) pairs present in pass 2
      new_events              — (id, title) pairs added by pass 3 (empty if unchanged)
      pass2_shared_aop_check  — raw shared_aop_check dict from pass 2
      pass3_shared_aop_check  — raw shared_aop_check dict from pass 3
    """
    # Build a fast lookup: group_key → set of added IDs from the expanded_groups list
    expanded_added: dict[str, list[str]] = {
        eg["group_key"]: eg["added_ids"] for eg in result["expanded_groups"]
    }

    unchanged: list[dict] = []
    changed: list[dict] = []

    # All pass 2 groups — sort into unchanged vs expanded
    for gk, g2 in groups2.items():
        pass2_ids = _sort_ids(g2.get("member_ids", set()))
        pass2_titles = g2.get("titles", {})
        pass2_pairs = [(i, pass2_titles.get(i, "")) for i in pass2_ids]

        added_ids = expanded_added.get(gk, [])
        g3 = groups3.get(gk, {})
        g3_titles = g3.get("titles", {})
        added_pairs = [(i, g3_titles.get(i, "")) for i in added_ids]

        rec = {
            "group_name": gk,
            "group_type": g2["type"],
            "pass2_events": pass2_pairs,
            "new_events": added_pairs,
            "pass2_shared_aop_check": g2.get("shared_aop_check", {}),
            "pass3_shared_aop_check": g3.get("shared_aop_check", {}),
        }
        (changed if added_pairs else unchanged).append(rec)

    # Entirely new groups created by pass 3 (no pass 2 counterpart)
    new_in_pass3: list[dict] = []
    for ng in result["new_groups_in_pass3"]:
        gk = ng["group_key"]
        g3 = groups3.get(gk, {})
        all_ids = _sort_ids(g3.get("member_ids", set()))
        all_titles = g3.get("titles", {})
        all_pairs = [(i, all_titles.get(i, "")) for i in all_ids]

        new_in_pass3.append({
            "group_name": gk,
            "group_type": ng["type"],
            "pass2_events": [],
            "new_events": all_pairs,
            "pass2_shared_aop_check": {},
            "pass3_shared_aop_check": g3.get("shared_aop_check", {}),
        })

    # Unchanged pass 2 groups first, then expanded, then brand-new
    return unchanged + changed + new_in_pass3


def _write_changes_json(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"Changes JSON written to: {path}")


def _write_changes_csv(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "group_name", "group_type",
                "pass2_events",
                "Count Co-Occurring AOPs", "AOPs",
                "Rating on Pass 2", "Comment on Group - Pass 2",
                "new_events",
                "Count Co-Occurring AOPs - Pass 3", "AOPs - Pass 3",
                "Rating on Pass 3", "Comment on Group",
            ],
        )
        writer.writeheader()
        for rec in records:
            aop_check2 = rec.get("pass2_shared_aop_check", {})
            aop_check3 = rec.get("pass3_shared_aop_check", {})
            writer.writerow({
                "group_name": rec["group_name"],
                "group_type": rec["group_type"],
                "pass2_events": _bullet_list(rec["pass2_events"]),
                "Count Co-Occurring AOPs": _aop_count(aop_check2),
                "AOPs": _aop_ids_str(aop_check2),
                "Rating on Pass 2": "",
                "Comment on Group - Pass 2": "",
                "new_events": _bullet_list(rec["new_events"]),
                "Count Co-Occurring AOPs - Pass 3": _aop_count(aop_check3),
                "AOPs - Pass 3": _aop_ids_str(aop_check3),
                "Rating on Pass 3": "",
                "Comment on Group": "",
            })
    print(f"Changes CSV written to: {path}")


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

def _print_report(result: dict) -> None:
    totals = result["totals"]

    print("=" * 72)
    print("PASS 2 vs PASS 3 COMPARISON")
    print("=" * 72)

    # --- Type summary table ---
    print("\n--- Groups and events by type ---")
    col = 42
    header = (
        f"{'Type':<{col}} {'P2 grps':>8} {'P2 evts':>8}"
        f" {'P3 grps':>8} {'P3 evts':>8} {'Δ grps':>7} {'Δ evts':>7}"
    )
    print(header)
    print("-" * len(header))

    total_p2g = total_p2e = total_p3g = total_p3e = 0
    for row in result["type_summary"]:
        label = TYPE_LABELS.get(row["type"], row["type"])
        dg = f"{row['delta_groups']:+d}" if row["delta_groups"] != 0 else "—"
        de = f"{row['delta_events']:+d}" if row["delta_events"] != 0 else "—"
        print(
            f"{label:<{col}} {row['pass2_groups']:>8} {row['pass2_events']:>8}"
            f" {row['pass3_groups']:>8} {row['pass3_events']:>8} {dg:>7} {de:>7}"
        )
        total_p2g += row["pass2_groups"]
        total_p2e += row["pass2_events"]
        total_p3g += row["pass3_groups"]
        total_p3e += row["pass3_events"]

    print("-" * len(header))
    total_dg = f"{total_p3g - total_p2g:+d}" if total_p3g != total_p2g else "—"
    total_de = f"{total_p3e - total_p2e:+d}" if total_p3e != total_p2e else "—"
    print(
        f"{'TOTAL':<{col}} {total_p2g:>8} {total_p2e:>8}"
        f" {total_p3g:>8} {total_p3e:>8} {total_dg:>7} {total_de:>7}"
    )

    delta_grouped = totals["pass3_total_grouped"] - totals["pass2_total_grouped"]
    delta_ungrouped = totals["pass3_total_ungrouped"] - totals["pass2_total_ungrouped"]
    print(
        f"\n  All grouped events  — pass2: {totals['pass2_total_grouped']}, "
        f"pass3: {totals['pass3_total_grouped']}  (Δ {delta_grouped:+d})"
    )
    print(
        f"  Ungrouped processed — pass2: {totals['pass2_total_ungrouped']}, "
        f"pass3: {totals['pass3_total_ungrouped']}  (Δ {delta_ungrouped:+d})"
    )

    # --- Newly grouped ---
    n = totals["events_newly_grouped_by_pass3"]
    print(f"\n--- Events newly grouped by pass 3: {n} ---")
    if result["newly_grouped_events"]:
        for ev in result["newly_grouped_events"]:
            print(f"  [{ev['event_id']}] {ev['title']}")
            for a in ev["assigned_to"]:
                print(f"        → {a['group_key']}  (type={a['type']})")
                print(f"          {a['rationale']}")
    else:
        print("  (none)")

    # --- Expanded groups ---
    n = totals["groups_expanded_by_pass3"]
    print(f"\n--- Groups expanded by pass 3: {n} ---")
    if result["expanded_groups"]:
        for eg in result["expanded_groups"]:
            added = eg["pass3_count"] - eg["pass2_count"]
            print(
                f"  {eg['group_key']}  (type={eg['type']})  "
                f"{eg['pass2_count']} → {eg['pass3_count']} members  (+{added})"
            )
            for ke_id in eg["added_ids"]:
                title = eg["added_titles"].get(ke_id, "")
                print(f"        + [{ke_id}] {title}")
    else:
        print("  (none)")

    # --- New groups ---
    n = totals["new_groups_created_by_pass3"]
    print(f"\n--- New groups created by pass 3: {n} ---")
    if result["new_groups_in_pass3"]:
        for ng in result["new_groups_in_pass3"]:
            print(f"  {ng['group_key']}  (type={ng['type']})")
            for ke_id in ng["member_ids"]:
                title = ng["titles"].get(ke_id, "")
                print(f"        [{ke_id}] {title}")
            print(f"        rationale: {ng['rationale']}")
    else:
        print("  (none)")

    print("\n" + "=" * 72)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare pass 2 and pass 3 outputs from collect_similar_events.py."
    )
    parser.add_argument("pass2_file", help="Path to the *_pass2.json output file")
    parser.add_argument("pass3_file", help="Path to the *_pass3.json output file")
    parser.add_argument(
        "--json-out",
        metavar="FILE",
        help="Write the full comparison result to this JSON file",
    )
    parser.add_argument(
        "--changes-json",
        metavar="FILE",
        help="Write the simplified changed-groups list to this JSON file",
    )
    parser.add_argument(
        "--changes-csv",
        metavar="FILE",
        help="Write the simplified changed-groups list to this CSV file",
    )
    args = parser.parse_args()

    for path in (args.pass2_file, args.pass3_file):
        if not Path(path).exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)

    with open(args.pass2_file) as f:
        pass2 = json.load(f)
    with open(args.pass3_file) as f:
        pass3 = json.load(f)

    result = compare(pass2, pass3)
    _print_report(result)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nFull comparison written to: {args.json_out}")

    if args.changes_json or args.changes_csv:
        groups2 = _extract_all_groups(pass2)
        groups3 = _extract_all_groups(pass3)
        records = _build_changes_records(result, groups2, groups3)
        if args.changes_json:
            _write_changes_json(records, Path(args.changes_json))
        if args.changes_csv:
            _write_changes_csv(records, Path(args.changes_csv))


if __name__ == "__main__":
    main()
