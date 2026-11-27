#!/usr/bin/env python3
"""Define the KE groups of one type that are unchanged across replicate grouping runs.

The LLM grouping (collect_similar_events.py) is not deterministic: replicate
runs of the same config reproduce only part of their groups
(docs/ke_grouping_model_comparison.md, "Reproducibility"). This script turns
several replicates into a deterministic, reviewable split for ONE group type
(``--type``, default ``merge``):

  stable_groups     — member sets that appear, with exactly the same members
                      and as this type, in EVERY run. These are the
                      reproducible candidates (for ``merge``: KEs that can be
                      merged).
  unstable_groups   — member sets of this type that appear in SOME runs but
                      not all (the LLM's call on them is not reproducible).
  attention_events  — every KE that is placed in a group of this type in at
                      least one run but is not in a stable group, with what
                      each run did with it. These deserve annotation /
                      curator attention before any merge decision.

Matching is exact member-set equality — no overlap threshold — so the result
depends only on the input files: the same inputs always give the same output,
in the same order. Group keys are not used for matching (they are generated
per run and drift); each set is identified by its sorted member ids.

Usage:
    # merge groups across the three thinking-on replicates (the defaults)
    uv run python -m aop_wiki_cli.annotation_scripts.define_stable_ke_groups

    # another type, explicit runs
    uv run python -m aop_wiki_cli.annotation_scripts.define_stable_ke_groups \\
        --type soda \\
        --files outputs_for_vc/ke_groupings/<run_1>/ke_similar_events_<date>_pass3.json \\
                outputs_for_vc/ke_groupings/<run_2>/ke_similar_events_<date>_pass3.json
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from aop_wiki_cli.annotation_scripts.compare_grouping_runs import (
    TYPE_KEYS,
    _member_ids,
    _sort_ids,
    _titles,
)

DEFAULT_FILES = [
    "outputs_for_vc/ke_groupings/11-25-2026_sonnet_5-5_thinking_on/ke_similar_events_11-25-2026_pass3.json",
    "outputs_for_vc/ke_groupings/11-27-2026_sonnet_5-5_thinking_on_run_a/ke_similar_events_11-27-2026_pass3.json",
    "outputs_for_vc/ke_groupings/11-27-2026_sonnet_5-5_thinking_on_run_b/ke_similar_events_11-27-2026_pass3.json",
]
# Derived, regenerable reports stay out of outputs_for_vc/ (which ships
# downstream verbatim).
DEFAULT_OUTPUT_DIR = Path("outputs/ke_groupings/stable_groups")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def run_label(path: Path) -> str:
    """A run's label: its directory name (e.g. 11-27-2026_..._run_a)."""
    return path.parent.name or path.stem


def load_run(data: dict) -> dict:
    """Normalise one grouping snapshot.

    Returns {"groups": [{key, type, member_ids (frozenset), titles,
    rationale, shared_aop_check}], "ungrouped": set of ids}.
    """
    groups = []
    for gtype, top_key in TYPE_KEYS.items():
        for key, group in data.get(top_key, {}).items():
            groups.append({
                "key": key,
                "type": gtype,
                "member_ids": frozenset(_member_ids(group, top_key)),
                "titles": _titles(group, top_key),
                "rationale": group.get("rationale", ""),
                "shared_aop_check": group.get("shared_aop_check", {}),
            })
    return {
        "groups": groups,
        "ungrouped": set(data.get("ungrouped_processed_events", {})),
    }


def _set_id(member_ids) -> str:
    """Deterministic identifier for a member set: its sorted ids joined by '+'."""
    return "+".join(_sort_ids(member_ids))


def _set_sort_key(member_ids):
    """Order sets by their first member id numerically, then by the full id list."""
    ids = _sort_ids(member_ids)
    first = ids[0] if ids else ""
    return (int(first) if first.isdigit() else float("inf"), ids)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _event_status(run: dict, ke_id: str) -> dict:
    """Describe what one run did with one KE."""
    placed = [g for g in run["groups"] if ke_id in g["member_ids"]]
    if placed:
        return {
            "status": "grouped",
            "groups": [
                {"key": g["key"], "type": g["type"], "member_ids": _sort_ids(g["member_ids"])}
                for g in sorted(placed, key=lambda g: (g["type"], g["key"]))
            ],
        }
    if ke_id in run["ungrouped"]:
        return {"status": "ungrouped", "groups": []}
    # Filtered out (orphan / OFA-only / placeholder title) or never processed.
    return {"status": "not_in_run", "groups": []}


def define_stable_groups(runs: dict[str, dict], group_type: str) -> dict:
    """Split one group type into stable groups, unstable groups and attention events.

    ``runs`` maps a run label to a load_run() result; insertion order is the
    run order reported in the output.
    """
    if group_type not in TYPE_KEYS:
        raise ValueError(f"unknown group type {group_type!r}; expected one of {sorted(TYPE_KEYS)}")
    labels = list(runs)

    # member set -> {run label: group} for groups of the requested type
    seen: dict[frozenset, dict[str, dict]] = {}
    for label, run in runs.items():
        for g in run["groups"]:
            if g["type"] == group_type:
                seen.setdefault(g["member_ids"], {})[label] = g

    stable, unstable = [], []
    for members in sorted(seen, key=_set_sort_key):
        by_run = seen[members]
        last = by_run[labels[-1]] if labels[-1] in by_run else next(iter(by_run.values()))
        record = {
            "set_id": _set_id(members),
            "member_ids": _sort_ids(members),
            "titles": {i: last["titles"].get(i, "") for i in _sort_ids(members)},
            "keys_by_run": {lb: by_run[lb]["key"] for lb in labels if lb in by_run},
        }
        if len(by_run) == len(labels):
            record["rationale_by_run"] = {lb: by_run[lb]["rationale"] for lb in labels}
            record["shared_aop_check"] = last["shared_aop_check"]
            stable.append(record)
        else:
            record["present_in"] = [lb for lb in labels if lb in by_run]
            record["absent_from"] = [lb for lb in labels if lb not in by_run]
            unstable.append(record)

    stable_ids = {i for rec in stable for i in rec["member_ids"]}
    candidate_ids = {i for members in seen for i in members}
    attention = []
    for ke_id in _sort_ids(candidate_ids - stable_ids):
        title = next(
            (g["titles"].get(ke_id) for run in runs.values() for g in run["groups"]
             if ke_id in g["member_ids"] and g["titles"].get(ke_id)),
            "",
        )
        per_run = {lb: _event_status(runs[lb], ke_id) for lb in labels}
        in_type = [lb for lb in labels
                   if any(g["type"] == group_type for g in per_run[lb]["groups"])]
        attention.append({
            "event_id": ke_id,
            "title": title,
            "reason": ("membership_differs" if len(in_type) == len(labels)
                       else "not_in_every_run"),
            "runs_with_type": in_type,
            "by_run": per_run,
        })

    return {
        "group_type": group_type,
        "runs": labels,
        "summary": {
            "runs": len(labels),
            "distinct_sets_seen": len(seen),
            "stable_groups": len(stable),
            "stable_events": len(stable_ids),
            "unstable_groups": len(unstable),
            "attention_events": len(attention),
            "attention_membership_differs": sum(a["reason"] == "membership_differs" for a in attention),
            "attention_not_in_every_run": sum(a["reason"] == "not_in_every_run" for a in attention),
        },
        "stable_groups": stable,
        "unstable_groups": unstable,
        "attention_events": attention,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _run_cell(status: dict) -> str:
    if status["status"] != "grouped":
        return status["status"]
    return "; ".join(f"{g['type']}:{g['key']} [{', '.join(g['member_ids'])}]"
                     for g in status["groups"])


def write_csvs(result: dict, out_dir: Path) -> list[Path]:
    """Write one CSV per section; returns the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    gtype, labels = result["group_type"], result["runs"]
    written = []

    path = out_dir / f"{gtype}_stable_groups.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["set_id", "size", "events", "shared_aop_check"]
                   + [f"key: {lb}" for lb in labels])
        for rec in result["stable_groups"]:
            w.writerow([
                rec["set_id"], len(rec["member_ids"]),
                "\n".join(f"{i}: {t}" for i, t in rec["titles"].items()),
                (rec["shared_aop_check"] or {}).get("statement", ""),
            ] + [rec["keys_by_run"].get(lb, "") for lb in labels])
    written.append(path)

    path = out_dir / f"{gtype}_unstable_groups.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["set_id", "size", "events", "present_in", "absent_from"])
        for rec in result["unstable_groups"]:
            w.writerow([
                rec["set_id"], len(rec["member_ids"]),
                "\n".join(f"{i}: {t}" for i, t in rec["titles"].items()),
                ", ".join(rec["present_in"]), ", ".join(rec["absent_from"]),
            ])
    written.append(path)

    path = out_dir / f"{gtype}_attention_events.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "title", "reason"] + labels)
        for a in result["attention_events"]:
            w.writerow([a["event_id"], a["title"], a["reason"]]
                       + [_run_cell(a["by_run"][lb]) for lb in labels])
    written.append(path)
    return written


def print_report(result: dict) -> None:
    s = result["summary"]
    print("=" * 72)
    print(f"Stable '{result['group_type']}' groups across {s['runs']} runs")
    for lb in result["runs"]:
        print(f"  - {lb}")
    print("=" * 72)
    print(f"  distinct member sets seen : {s['distinct_sets_seen']}")
    print(f"  stable (in every run)     : {s['stable_groups']} groups, {s['stable_events']} events")
    print(f"  unstable (in some runs)   : {s['unstable_groups']} groups")
    print(f"  events needing attention  : {s['attention_events']} "
          f"({s['attention_membership_differs']} membership differs, "
          f"{s['attention_not_in_every_run']} not in every run)")
    print("=" * 72)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Define the KE groups of one type that are unchanged across replicate runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--type", dest="group_type", default="merge", choices=sorted(TYPE_KEYS),
                        help="Group type to evaluate (default: merge)")
    parser.add_argument("--files", nargs="+", metavar="FILE", default=DEFAULT_FILES,
                        help="Grouping snapshots (pass 3 JSON) to compare; "
                             "default: the three sonnet-5-5 thinking-on replicates")
    parser.add_argument("--output-dir", metavar="DIR", default=str(DEFAULT_OUTPUT_DIR),
                        help=f"Where to write the JSON and CSVs (default: {DEFAULT_OUTPUT_DIR})")
    args = parser.parse_args()

    paths = [Path(p) for p in args.files]
    if len(paths) < 2:
        parser.error("--files needs at least two runs")
    resolved = [p.resolve() for p in paths]
    if len(set(resolved)) != len(resolved):
        parser.error("--files lists the same file more than once")
    for p in paths:
        if not p.exists():
            sys.exit(f"Error: file not found: {p}")

    runs: dict[str, dict] = {}
    for p in paths:
        label = run_label(p)
        if label in runs:
            label = str(p)  # two runs in same-named directories: fall back to the path
        with open(p) as f:
            runs[label] = load_run(json.load(f))

    result = define_stable_groups(runs, args.group_type)
    result["files"] = {lb: str(p) for lb, p in zip(runs, paths)}
    print_report(result)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{args.group_type}_stable_groups.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"JSON written to: {json_path}")
    for path in write_csvs(result, out_dir):
        print(f"CSV written to:  {path}")


if __name__ == "__main__":
    main()
