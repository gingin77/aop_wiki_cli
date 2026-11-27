#!/usr/bin/env python3
"""Apply manual KE curations into the shared store BEFORE running annotate_ke.py.

Reads annotation_scripts/manual_curations.yaml and seeds corrected field values
into outputs_for_vc/annotations/ke_annotations.json, marked
`source: manual_curation`. annotate_ke.py then treats these as reference values
and skips re-querying them (its "(reference) ... skipping query" path), so the
corrections survive every future annotation run.

Only fields the annotator reads back from the store are curatable:
  top-level:    biological_organization (level string), cell_term, organ_term,
                cellular_component
  per-subject:  biological_object, biological_process, phenotype
(biological_action is recomputed from the title by annotate_ke.py, so it is not
curatable here.)

Usage:
    uv run python -m aop_wiki_cli.annotation_scripts.apply_manual_curations --dry-run
    uv run python -m aop_wiki_cli.annotation_scripts.apply_manual_curations
    uv run python -m aop_wiki_cli.annotation_scripts.apply_manual_curations \\
        --curations src/aop_wiki_cli/annotation_scripts/manual_curations.yaml --date 11-25-2026
"""

import argparse
import json
import os
import sys
from datetime import date

import yaml
from dotenv import load_dotenv

from aop_wiki_cli.annotation_scripts.annotate_term_helpers import (
    FIELD_ONTOLOGIES,
    field_subtree_root,
)
from aop_wiki_cli.annotation_scripts.store import (
    KE_ANNOTATIONS_PATH,
    find_cache_file,
    load_ke_annotations,
    save_ke_annotations,
)
from aop_wiki_cli.annotation_scripts.ke_title_parser import parse_ke_title
from aop_wiki_cli.annotation_scripts.query_bioportal import search_bioportal_with_fallback

DEFAULT_CURATIONS = os.path.join(os.path.dirname(__file__), "manual_curations.yaml")

# Fields the annotator honors from the store (see module docstring).
TOP_LEVEL_TERM_FIELDS = {"cell_term", "organ_term", "cellular_component"}
EC_TERM_FIELDS = {"biological_object", "biological_process", "phenotype"}
STRING_TOP_FIELDS = {"biological_organization"}
CURATABLE_FIELDS = TOP_LEVEL_TERM_FIELDS | EC_TERM_FIELDS | STRING_TOP_FIELDS

# Prefixes that resolve to an OBO PURL IRI; anything else keeps its CURIE as id.
OBO_PREFIXES = {
    "PR", "GO", "CL", "UBERON", "CHEBI", "HP", "MP", "UPHENO",
    "PATO", "SO", "OBA", "NCBITAXON", "NCIT", "OBI",
}


def _curie_to_iri(curie: str) -> tuple[str, str]:
    """Return (term_id, ontology) for a CURIE. OBO prefixes become PURLs."""
    prefix, sep, local = curie.partition(":")
    if not sep:
        raise ValueError(f"{curie!r} is not a CURIE (expected PREFIX:LOCAL)")
    upper = prefix.upper()
    if upper in OBO_PREFIXES:
        return f"http://purl.obolibrary.org/obo/{upper}_{local}", upper
    return curie, prefix  # non-OBO: keep CURIE as the id


def _resolve_term(field: str, spec: dict, bioportal_key: str | None) -> dict:
    """Turn one field spec into a stored value (term dict or rejection record)."""
    if not isinstance(spec, dict):
        raise ValueError(f"{field}: expected a mapping, got {type(spec).__name__}")

    if spec.get("no_term"):
        return {
            "term_id": None, "label": None, "ontology": None,
            "source": "manual_rejection",
            "rejection_reason": spec.get("reason", "manually asserted: no valid term"),
        }

    if "curie" in spec:
        term_id, ontology = _curie_to_iri(str(spec["curie"]))
        return {
            "term_id": term_id,
            "label": spec.get("label") or str(spec["curie"]),
            "ontology": ontology,
            "source": "manual_curation",
            "curie": str(spec["curie"]),
        }

    if "query" in spec:
        if not bioportal_key:
            raise ValueError(f"{field}: query resolution needs BIOPORTAL_API_KEY (not set)")
        phrase = str(spec["query"])
        ontologies = spec.get("ontologies") or FIELD_ONTOLOGIES.get(field, "")
        results, used = search_bioportal_with_fallback(
            phrase, ontologies, bioportal_key,
            subtree_root_iri=field_subtree_root(field, ontologies),
        )
        if not results:
            raise ValueError(f"{field}: no BioPortal results for query {phrase!r} in [{ontologies}]")
        exact = next((r for r in results if (r.get("label") or "").lower() == phrase.lower()), None)
        chosen = exact or results[0]
        note = f"exact match" if exact else f"top of {len(results)} results"
        print(f"    query {phrase!r} ({used}) -> [{chosen.get('ontology') or '?'}] "
              f"{chosen.get('label')!r} ({note})")
        return {
            "term_id": chosen.get("term_id"),
            "label": chosen.get("label"),
            "ontology": chosen.get("ontology"),
            "source": "manual_curation",
            "query_used": phrase,
        }

    raise ValueError(f"{field}: spec must have one of curie / query / no_term (or value)")


def _resolve_string(field: str, spec) -> str:
    """Resolve a plain-string field (biological_organization)."""
    value = spec.get("value") if isinstance(spec, dict) else spec
    if not value:
        raise ValueError(f"{field}: expected a 'value' string")
    return str(value)


def _title_for(ke_id: str, store: dict, cache_file: str | None) -> str | None:
    if ke_id in store and store[ke_id].get("title"):
        return store[ke_id]["title"]
    if cache_file:
        with open(cache_file) as f:
            events = json.load(f)
        rec = events.get(ke_id)
        if rec:
            return rec.get("title")
    return None


def _blank_entry(ke_id: str, title: str | None) -> dict:
    return {
        "ke_id": ke_id,
        "title": title or "",
        "biological_organization": None,
        "cell_term": None,
        "organ_term": None,
        "cellular_component": None,
        "ec_annotations": [],
        "comments": {"carried": [], "new": []},
    }


def _event_component_for_phrase(entry: dict, subject: str) -> dict:
    for s in entry["ec_annotations"]:
        if isinstance(s, dict) and s.get("subject") == subject:
            return s
    s = {"subject": subject, "biological_object": None,
         "biological_process": None, "phenotype": None, "biological_action": None}
    entry["ec_annotations"].append(s)
    return s


def _add_comment(entry: dict, text: str) -> None:
    comments = entry.setdefault("comments", {"carried": [], "new": []})
    existing = set(comments.get("carried", [])) | set(comments.get("new", []))
    if text not in existing:
        comments.setdefault("new", []).append(text)


def _pick_subject_phrase(field: str, spec: dict, subjects: list[str], ke_id: str) -> str:
    requested = spec.get("subject") if isinstance(spec, dict) else None
    if requested:
        if subjects and requested not in subjects:
            print(f"  ! KE {ke_id} {field}: subject {requested!r} is not a parsed "
                  f"subject {subjects}; applying anyway.")
        return requested
    if len(subjects) == 1:
        return subjects[0]
    raise ValueError(
        f"KE {ke_id} {field}: KE has multiple subjects {subjects}; add `subject:` to the spec."
    )


def apply_curations(curations: dict, store: dict, cache_file: str | None,
                    bioportal_key: str | None) -> tuple[int, int]:
    """Apply all curations into `store` (mutated). Returns (ke_count, field_count)."""
    stamp = date.today().strftime("%Y-%m-%d")
    ke_count = field_count = 0

    for ke_id, cur in curations.items():
        ke_id = str(ke_id)
        fields = (cur or {}).get("fields", {}) or {}
        rationale = (cur or {}).get("rationale", "")
        title = _title_for(ke_id, store, cache_file)
        subjects = parse_ke_title(title)["subjects"] if title else []

        entry = store.setdefault(ke_id, _blank_entry(ke_id, title))
        if title and not entry.get("title"):
            entry["title"] = title

        applied_here = 0
        for field, spec in fields.items():
            if field not in CURATABLE_FIELDS:
                print(f"  ! KE {ke_id}: field {field!r} is not curatable — skipping. "
                      f"Allowed: {sorted(CURATABLE_FIELDS)}")
                continue
            try:
                if field in STRING_TOP_FIELDS:
                    value = _resolve_string(field, spec)
                    old = entry.get(field)
                    entry[field] = value
                    summary = value
                elif field in TOP_LEVEL_TERM_FIELDS:
                    value = _resolve_term(field, spec, bioportal_key)
                    old = entry.get(field)
                    entry[field] = value
                    summary = value.get("label") or value.get("rejection_reason")
                else:  # EC term field
                    value = _resolve_term(field, spec, bioportal_key)
                    subject = _pick_subject_phrase(field, spec, subjects, ke_id)
                    subj_entry = _event_component_for_phrase(entry, subject)
                    old = subj_entry.get(field)
                    subj_entry[field] = value
                    summary = value.get("label") or value.get("rejection_reason")
            except ValueError as e:
                print(f"  ✗ {e}")
                continue

            overwrote = old is not None
            mark = "overwrote" if overwrote else "set"
            print(f"  ✓ KE {ke_id}: {mark} {field} = {summary!r}")
            _add_comment(entry, f"[manual curation {stamp}] {field} ← {summary}. {rationale}".strip())
            applied_here += 1
            field_count += 1

        if applied_here:
            ke_count += 1

    return ke_count, field_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--curations", default=DEFAULT_CURATIONS,
                        help=f"Curation YAML (default: {DEFAULT_CURATIONS})")
    parser.add_argument("--date", default=None,
                        help="Event cache date MM-DD-YYYY for titles (default: latest cache)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve and report changes without writing the store")
    args = parser.parse_args()

    load_dotenv()
    bioportal_key = os.environ.get("BIOPORTAL_API_KEY")

    if not os.path.exists(args.curations):
        print(f"Curations file not found: {args.curations}", file=sys.stderr)
        sys.exit(1)
    with open(args.curations) as f:
        doc = yaml.safe_load(f) or {}
    curations = doc.get("curations", {}) or {}
    if not curations:
        print("No curations defined. Nothing to do.")
        return

    cache_file = find_cache_file(args.date)
    store = load_ke_annotations()

    print(f"Applying {len(curations)} KE curation(s)"
          f"{' [DRY RUN]' if args.dry_run else ''} — titles from "
          f"{cache_file or '(store only)'}\n")
    ke_count, field_count = apply_curations(curations, store, cache_file, bioportal_key)

    print(f"\n{field_count} field(s) curated across {ke_count} KE(s).")
    if args.dry_run:
        print("Dry run — store not written.")
    else:
        save_ke_annotations(store)
        print(f"Saved to {KE_ANNOTATIONS_PATH}")
    print("\nNext: run annotate_ke.py — curated fields show as "
          "'(reference) ... skipping query' and are preserved.")


if __name__ == "__main__":
    main()
