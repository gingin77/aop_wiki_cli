#!/usr/bin/env python3
"""Report ontology-term coverage in outputs_for_vc/annotations/ke_annotations.json.

Quantifies, per ECS field, how many (KE, subject) slots are:
  resolved  -> a term dict carrying a non-null term_id
  rejected  -> source llm_rejection / manual_rejection (term_id null, has reason)
  null      -> None / missing
Resolved slots are also broken down by `source` (llm_recommendation,
manual_curation, manual_entry, ...). This is read-only: it never writes the
store. It complements summarize_annotations.py (assay coverage) and
compare_ke_annotations.py (annotations vs AOP-Wiki cache).

biological_action is reported separately as a direction-word distribution
(increased / decreased / ...), since it is a normalized direction, not an
ontology term.

Scope (default: every KE in the file):
  --diff        only KEs whose content differs from the committed (HEAD) version
  --aop N       only KEs listed under AOP N in aop_ke_index.json
  --worklist F  additionally list every KE/subject where field F is null or
                rejected (a review worklist); F is an ECS field name or "all"

Usage:
    uv run python -m aop_wiki_cli.annotation_scripts.report_annotation_coverage
    uv run python -m aop_wiki_cli.annotation_scripts.report_annotation_coverage --diff
    uv run python -m aop_wiki_cli.annotation_scripts.report_annotation_coverage --aop 61
    uv run python -m aop_wiki_cli.annotation_scripts.report_annotation_coverage --diff --worklist biological_process
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ANNOTATIONS_FILE = "outputs_for_vc/annotations/ke_annotations.json"
AOP_INDEX_FILE = "outputs_for_vc/annotations/aop_ke_index.json"

# Ontology-term fields, classified resolved/rejected/null.
EC_TERM_FIELDS = ["biological_object", "biological_process", "phenotype"]
TOP_TERM_FIELDS = ["cell_term", "organ_term", "cellular_component"]
TERM_FIELDS = EC_TERM_FIELDS + TOP_TERM_FIELDS


def _ke_sort_key(ke_id: str):
    return (0, int(ke_id)) if ke_id.isdigit() else (1, 0)


def classify(value) -> tuple[str, str | None]:
    """Return (state, source) for a term field value.

    state is 'resolved' | 'rejected' | 'null'.
    """
    if not isinstance(value, dict):
        return "null", None
    source = value.get("source")
    if value.get("term_id"):
        return "resolved", source or "unknown"
    if source in ("llm_rejection", "manual_rejection") or value.get("rejection_reason"):
        return "rejected", source or "rejection"
    return "null", source


def _subjects(ke: dict) -> list[dict]:
    return [ec for ec in ke.get("ec_annotations", []) if isinstance(ec, dict)]


def tally(store: dict):
    """Return (field_state, field_source, bio_org, action_dirs)."""
    field_state = {f: Counter() for f in TERM_FIELDS}
    field_source = {f: Counter() for f in TERM_FIELDS}
    bio_org = Counter()
    action_dirs = Counter()
    for ke in store.values():
        bio_org["set" if ke.get("biological_organization") else "null"] += 1
        for f in TOP_TERM_FIELDS:
            state, src = classify(ke.get(f))
            field_state[f][state] += 1
            if state == "resolved":
                field_source[f][src] += 1
        for ec in _subjects(ke):
            for f in EC_TERM_FIELDS:
                state, src = classify(ec.get(f))
                field_state[f][state] += 1
                if state == "resolved":
                    field_source[f][src] += 1
            action = ec.get("biological_action")
            term = action.get("term") if isinstance(action, dict) else None
            action_dirs[term or "(none)"] += 1
    return field_state, field_source, bio_org, action_dirs


def _load_head_store(path: str) -> dict | None:
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:{path}"],
            capture_output=True, text=True, check=True,
        ).stdout
        return json.loads(out)
    except Exception as e:
        print(f"Could not load HEAD version of {path}: {e}", file=sys.stderr)
        return None


def _diff_ke_ids(store: dict, path: str) -> list[str] | None:
    head = _load_head_store(path)
    if head is None:
        return None
    changed = [kid for kid in set(store) | set(head) if store.get(kid) != head.get(kid)]
    return sorted(changed, key=_ke_sort_key)


def _aop_ke_ids(aop: int, store: dict) -> list[str]:
    index = json.loads(Path(AOP_INDEX_FILE).read_text())
    ids = index.get(str(aop)) or index.get(aop) or []
    return sorted((str(k) for k in ids), key=_ke_sort_key)


def print_report(store: dict, scope_label: str) -> None:
    field_state, field_source, bio_org, action_dirs = tally(store)
    print(f"Scope: {scope_label}  ({len(store)} KE(s))\n")

    print("Ontology-term resolution — counts are (KE, subject) slots:")
    print(f"  {'field':<24}{'resolved':>9}{'rejected':>9}{'null':>7}")
    for f in TERM_FIELDS:
        c = field_state[f]
        print(f"  {f:<24}{c['resolved']:>9}{c['rejected']:>9}{c['null']:>7}")
    print(f"\n  biological_organization: set={bio_org['set']}  null={bio_org['null']}")

    dirs = ", ".join(f"{k}={v}" for k, v in action_dirs.most_common())
    print(f"  biological_action (direction word): {dirs}")

    print("\nResolved slots by source:")
    any_src = False
    for f in TERM_FIELDS:
        if field_source[f]:
            any_src = True
            parts = ", ".join(f"{k}={v}" for k, v in field_source[f].most_common())
            print(f"  {f:<24}{parts}")
    if not any_src:
        print("  (none resolved)")


def print_worklist(store: dict, which: str) -> None:
    fields = TERM_FIELDS if which == "all" else [which]
    print(f"\nWorklist — null/rejected slots for: {', '.join(fields)}")
    found = False
    for ke_id in sorted(store, key=_ke_sort_key):
        ke = store[ke_id]
        lines = []
        for f in fields:
            if f in TOP_TERM_FIELDS:
                state, _ = classify(ke.get(f))
                if state != "resolved":
                    lines.append(f"      {f}: {state}")
            else:
                for ec in _subjects(ke):
                    state, _ = classify(ec.get(f))
                    if state != "resolved":
                        reason = ""
                        v = ec.get(f)
                        if isinstance(v, dict) and v.get("rejection_reason"):
                            reason = f" — {v['rejection_reason']}"
                        subj = ec.get("subject", "?")
                        lines.append(f"      [{f}] {subj!r}: {state}{reason}")
        if lines:
            found = True
            print(f"  KE {ke_id}: {ke.get('title', '')!r}")
            print("\n".join(lines))
    if not found:
        print("  (nothing — all requested fields resolved in scope)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotations", default=ANNOTATIONS_FILE,
                        help=f"KE annotations JSON (default: {ANNOTATIONS_FILE})")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--diff", action="store_true",
                       help="only KEs whose content differs from the committed (HEAD) version")
    scope.add_argument("--aop", type=int, metavar="N",
                       help="only KEs listed under AOP N in aop_ke_index.json")
    parser.add_argument("--worklist", metavar="FIELD",
                        help="also list null/rejected slots for FIELD "
                             f"({', '.join(TERM_FIELDS)}, or 'all')")
    args = parser.parse_args()

    if args.worklist and args.worklist != "all" and args.worklist not in TERM_FIELDS:
        parser.error(f"--worklist must be 'all' or one of {TERM_FIELDS}")

    store = json.loads(Path(args.annotations).read_text())

    if args.diff:
        ids = _diff_ke_ids(store, args.annotations)
        if ids is None:
            sys.exit(1)
        scope_label = f"KEs changed vs HEAD: {', '.join(ids) or '(none)'}"
        store = {k: store[k] for k in ids if k in store}
    elif args.aop is not None:
        ids = _aop_ke_ids(args.aop, store)
        present = [k for k in ids if k in store]
        missing = [k for k in ids if k not in store]
        scope_label = f"AOP {args.aop} KEs: {', '.join(ids) or '(none)'}"
        if missing:
            scope_label += f"  [not in store: {', '.join(missing)}]"
        store = {k: store[k] for k in present}
    else:
        scope_label = "all KEs in file"

    print_report(store, scope_label)
    if args.worklist:
        print_worklist(store, args.worklist)


if __name__ == "__main__":
    main()
