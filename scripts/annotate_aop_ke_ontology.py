"""
Annotate Key Events for a given AOP using the BioPortal + Claude workflow.

Storage model:
  - ke_annotations.json          — shared store, one entry per KE (single source of truth)
  - ke_annotations_for_aop_N.json — AOP index, just {"ke_ids": [...]}

KEs that already exist in the shared store are skipped during annotation (not duplicated).
Claude Code drives the loop one KE at a time via --ke-id.

Usage:
    # List KEs for an AOP with annotation status
    uv run python scripts/annotate_aop_ke_ontology.py --aop 173 --date 04-28-2026

    # Annotate a single KE and write to shared store
    uv run python scripts/annotate_aop_ke_ontology.py --aop 173 --ke-id 68 --date 04-28-2026

    # Add a comment to a KE in the shared store
    uv run python scripts/annotate_aop_ke_ontology.py --aop 173 --ke-id 68 --add-comment "Needs review"
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
AOP_ANNOTATIONS_DIR = "outputs_for_vc/aop_based_ke_annotations"
SHARED_STORE_PATH = os.path.join(AOP_ANNOTATIONS_DIR, "ke_annotations.json")
AOP_STORE_PATH = os.path.join(AOP_ANNOTATIONS_DIR, "aop_based_ke_store.json")


def _cache_file(date_str: str) -> str:
    return os.path.join(CACHE_DIR_ROOT, date_str, f"all_events_{date_str}.json")



# ---------------------------------------------------------------------------
# Shared store
# ---------------------------------------------------------------------------

def _load_shared_store() -> dict:
    if os.path.exists(SHARED_STORE_PATH):
        with open(SHARED_STORE_PATH) as f:
            return json.load(f)
    return {}


def _save_shared_store(store: dict) -> None:
    os.makedirs(AOP_ANNOTATIONS_DIR, exist_ok=True)
    with open(SHARED_STORE_PATH, "w") as f:
        json.dump(store, f, indent=2)


# ---------------------------------------------------------------------------
# AOP store
# ---------------------------------------------------------------------------

def _load_aop_store() -> dict:
    if os.path.exists(AOP_STORE_PATH):
        with open(AOP_STORE_PATH) as f:
            return json.load(f)
    return {}


def _save_aop_store(aop_store: dict) -> None:
    os.makedirs(AOP_ANNOTATIONS_DIR, exist_ok=True)
    with open(AOP_STORE_PATH, "w") as f:
        json.dump(aop_store, f, indent=2)


def _register_ke_in_aop(aop_id: str, ke_id: str) -> None:
    """Add ke_id to the AOP store under aop_id if not already present."""
    aop_store = _load_aop_store()
    ke_ids = aop_store.setdefault(aop_id, [])
    if ke_id not in ke_ids:
        ke_ids.append(ke_id)
        _save_aop_store(aop_store)


def _migrate_per_aop_files() -> None:
    """
    One-time migration: if per-AOP index files exist with full annotation data,
    extract KEs into the shared store and register them in the AOP store.
    """
    if not os.path.isdir(AOP_ANNOTATIONS_DIR):
        return
    for fname in os.listdir(AOP_ANNOTATIONS_DIR):
        if not (fname.startswith("ke_annotations_for_aop_") and fname.endswith(".json")):
            continue
        aop_id = fname.removeprefix("ke_annotations_for_aop_").removesuffix(".json")
        fpath = os.path.join(AOP_ANNOTATIONS_DIR, fname)
        with open(fpath) as f:
            data = json.load(f)
        # Old full-annotation format: dict of ke_id -> annotation dict
        if data and "ke_ids" not in data and not isinstance(next(iter(data.values())), list):
            print(f"  Migrating {fname}...")
            store = _load_shared_store()
            aop_store = _load_aop_store()
            ke_ids = list(data.keys())
            for ke_id, annotation in data.items():
                if ke_id not in store:
                    store[ke_id] = annotation
            _save_shared_store(store)
            existing = aop_store.setdefault(aop_id, [])
            for ke_id in ke_ids:
                if ke_id not in existing:
                    existing.append(ke_id)
            _save_aop_store(aop_store)
            os.remove(fpath)
            print(f"  Migrated {len(ke_ids)} KEs from {fname} → removed per-AOP file")


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------

def annotate_single_ke(
    aop_id: str,
    ke_id: str,
    cache_file: str,
) -> str:
    """
    Annotate one KE and write to the shared store. Registers the KE in the AOP index.
    If the KE already exists in the shared store, uses it as reference (skips re-annotation
    unless the user explicitly passes --force, handled at the call site).
    Returns the shared store path.
    """
    api_key = os.environ.get("BIOPORTAL_API_KEY")
    if not api_key:
        raise EnvironmentError("BIOPORTAL_API_KEY not set — add it to .env")

    with open(cache_file) as f:
        events = json.load(f)

    if ke_id not in events:
        print(f"KE {ke_id} not found in cache.")
        sys.exit(1)

    store = _load_shared_store()
    ref_ke = store.get(ke_id)
    if ref_ke:
        print(f"  (KE {ke_id} found in shared store — using as reference)")

    title = events[ke_id].get("title", "")
    description = events[ke_id].get("description", "")

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

    store[ke_id] = annotation
    _save_shared_store(store)
    _register_ke_in_aop(aop_id, ke_id)

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
    print(f"\nSaved to {SHARED_STORE_PATH}")
    print("=" * 60)

    return SHARED_STORE_PATH


def add_comment(ke_id: str, comment: str) -> None:
    """Append a comment to a KE in the shared store."""
    store = _load_shared_store()
    if ke_id not in store:
        print(f"KE {ke_id} not found in shared store — annotate it first.")
        sys.exit(1)
    store[ke_id].setdefault("comments", {"carried": [], "new": []})
    store[ke_id]["comments"]["new"].append(comment)
    _save_shared_store(store)
    print(f"Comment added to KE {ke_id}. Saved to {SHARED_STORE_PATH}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Annotate KEs for an AOP (one at a time)")
    parser.add_argument("--aop", required=True, help="AOP ID (e.g. 173)")
    parser.add_argument("--ke-id", default=None, help="Annotate a single KE by ID")
    parser.add_argument("--add-comment", default=None, help="Append a comment to a KE (requires --ke-id)")
    parser.add_argument("--force", action="store_true", help="Re-annotate even if KE exists in shared store")
    parser.add_argument(
        "--date",
        default=datetime.date.today().strftime("%m-%d-%Y"),
        help="Cache date MM-DD-YYYY (default: today)",
    )
    args = parser.parse_args()

    cache = _cache_file(args.date)
    if not os.path.exists(cache):
        print(f"Cache file not found: {cache}")
        sys.exit(1)

    # Add a comment
    if args.add_comment:
        if not args.ke_id:
            print("--add-comment requires --ke-id")
            sys.exit(1)
        add_comment(args.ke_id, args.add_comment)
        return

    # List mode
    if args.ke_id is None:
        _migrate_per_aop_files()
        kes = list_aop_kes(args.aop, cache)
        if not kes:
            print(f"No KEs found for AOP {args.aop}")
            sys.exit(1)
        store = _load_shared_store()
        print(f"\nAOP {args.aop} — {len(kes)} KEs")
        print(f"Shared KE store: {SHARED_STORE_PATH}")
        print(f"AOP store:       {AOP_STORE_PATH}")
        print()
        for ke_id, title in kes:
            status = "✓ done" if ke_id in store else "pending"
            print(f"  [{status}] KE {ke_id}: {title}")
        return

    # Single-KE annotation mode
    store = _load_shared_store()
    if args.ke_id in store and not args.force:
        print(f"KE {args.ke_id} already in shared store. Use --force to re-annotate.")
        _register_ke_in_aop(args.aop, args.ke_id)
        return

    annotate_single_ke(args.aop, args.ke_id, cache)


if __name__ == "__main__":
    main()
