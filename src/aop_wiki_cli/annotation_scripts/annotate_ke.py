"""
Annotate AOP-Wiki Key Events with bio-ontology terms using BioPortal + Claude.

Workflow (see _build_ke_annotation, which runs one step per line):
  1. review_ref_comments           — summarize prior curator comments into
                                     ranking guidance for every later step
  2. _parse_title                  — split the title into direction + subject
                                     phrases (+ subcellular-location hint)
  3. _annotate_biological_action   — controlled vocab, else LLM normalization
  4. _resolve_biological_organization — stored reference, else LLM/manual
  5. _annotate_location_terms      — cell_term / organ_term /
                                     cellular_component, gated by org level
  6. _annotate_subjects            — per subject phrase: biological_object →
                                     biological_process → phenotype
annotate_ke() wraps that sequence with store handling: load the cache and the
stored reference, honor --force/--force-on, extract assays, carry comments,
record newly annotated fields, stamp the schema version, and save.

This script is designed to make use of LLM annotations that have already been stored
and are under version control in `outputs_for_vc/annotations/`.

Storage model within `outputs_for_vc/annotations/` includees:
  - ke_annotations.json  — one entry per KE (single source of truth)
  - aop_ke_index.json    — AOP index, maps AOP ID → list of KE IDs

KEs already in the shared store are skipped during annotation (use --force to re-annotate).

Usage:
    # Annotate a standalone KE (no AOP required)
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_ke --ke-id 14 --date 04-28-2026

    # Annotate a KE and register it under an AOP
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_ke --aop 173 --ke-id 68 --date 04-28-2026

    # List KEs for an AOP with annotation status
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_ke --aop 173 --date 04-28-2026

    # Re-annotate all fields from scratch
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_ke --ke-id 68 --force --date 04-28-2026

    # Re-annotate only the assays
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_ke --ke-id 68 --force-on assays --date 04-28-2026

"""

import argparse
import copy
import datetime
import json
import os
import re
import sys
import anthropic
import logging
from dotenv import load_dotenv
from datetime import date

from aop_wiki_cli.utilities import set_up_logger, get_dated_cache_dir
from aop_wiki_cli.analysis.collect_event_rankings import collect_and_rank_events


logger = set_up_logger('aop-wiki-annotate', level=logging.INFO)

from aop_wiki_cli.annotation_scripts import prompts
from aop_wiki_cli.annotation_scripts.llm import call_json, call_text, make_client
from aop_wiki_cli.annotation_scripts.store import (
    AOP_KE_INDEX_PATH,
    CACHE_DIR_ROOT,
    KE_ANNOTATIONS_PATH,
    events_cache_file,
    load_ke_annotations,
    save_ke_annotations,
    list_aop_kes,
    register_ke_in_aop,
)
from aop_wiki_cli.annotation_scripts.ke_title_parser import (
    WIKI_ACTION_WORDS,
    extract_biological_object,
    parse_ke_title,
)
from aop_wiki_cli.annotation_scripts.query_bioportal import STOPWORDS
from aop_wiki_cli.annotation_scripts.annotate_term_helpers import (
    ECS_ONTOLOGIES,
    TOP_LEVEL_ONTOLOGIES,
    annotate_term,
    is_rejection,
)
from aop_wiki_cli.annotation_scripts.assay_extraction import annotate_ke_assays


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BIOLOGICAL_ORGANIZATION_LEVELS = [
    "Molecular",
    "Cellular",
    "Tissue",
    "Organ",
    "Individual",
    "Population",
]
_CELL_TERM_LEVELS = {"Molecular", "Cellular"}
_ORGAN_TERM_LEVELS = {"Cellular", "Tissue", "Organ"}
_CELLULAR_COMPONENT_LEVELS = {"Molecular", "Cellular"}

# Completeness marker. A KE finished by annotate_ke() is stamped with this
# version; the batch/single-KE gates skip a KE only when its stored
# schema_version equals this. Bump it whenever the workflow changes in a way
# that should re-process KEs previously marked complete — a bump makes the next
# run re-annotate stale KEs (filling nulls and new fields, honoring existing
# ref values). Entries without the field (annotated before versioning, when
# completeness was proxied by the presence of 'assays') are treated as stale.
# History:
#   2 — versioned completeness; adds cellular_component + subcellular-location
#       extraction (replaces the 'assays'-presence proxy)
ANNOTATION_SCHEMA_VERSION = 2

# GO terms may be valid phenotype terms (e.g. "hypersensitivity" is included in UPHENO),
# but many are biological processes and not appropriate as phenotype annotations.
# Flag for manual review when a GO term is selected as phenotype.
_PHENOTYPE_GO_REVIEW_PREFIXES = {"GO"}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def annotate_ke(
    ke_id: str,
    cache_file: str,
    force: bool = False,
    force_fields: set[str] | None = None,
) -> str:
    """
    Annotate one KE and write it to the shared store.

    Load the KE from the cache, use any stored annotation as the reference
    (masked by --force/--force-on), run the annotation sequence
    (_build_ke_annotation), extract assays, carry comments forward, record
    which fields are newly annotated, stamp the schema version, save, and
    register the KE under its AOPs.

    Returns the shared store path.
    """
    bp_api_key = os.environ.get("BIOPORTAL_API_KEY")
    if not bp_api_key:
        raise EnvironmentError("BIOPORTAL_API_KEY not set — add it to .env")

    with open(cache_file) as f:
        events = json.load(f)

    if ke_id not in events:
        print(f"KE {ke_id} not found in cache — skipping.")
        return ""

    store = load_ke_annotations()
    ref_ke = store.get(ke_id)
    if ref_ke:
        print(f"  (KE {ke_id} found in shared store — using as reference)")

    title = events[ke_id].get("title", "")
    description = events[ke_id].get("description", "")

    if force:
        effective_ref = None
    elif force_fields:
        effective_ref = _mask_ref(ref_ke, force_fields) if ref_ke else None
    else:
        effective_ref = ref_ke

    annotated_ke = _build_ke_annotation(ke_id, title, bp_api_key, description=description, ref_ke=effective_ref)

    ref_has_assays = (ref_ke or {}).get("assays") is not None
    if force or "assays" in (force_fields or set()) or not ref_has_assays:
        annotated_ke["assays"] = annotate_ke_assays(ke_id, events[ke_id])
    else:
        annotated_ke["assays"] = (ref_ke or {}).get("assays")

    ref_comments = _attach_comments(annotated_ke, ref_ke)

    new_fields = _compute_newly_updated_fields(effective_ref, annotated_ke)
    if new_fields:
        annotated_ke["newly_annotated_fields"] = new_fields
    else:
        annotated_ke.pop("newly_annotated_fields", None)

    annotated_ke["schema_version"] = ANNOTATION_SCHEMA_VERSION
    store[ke_id] = annotated_ke
    save_ke_annotations(store)
    for aop in events[ke_id].get("aop_ids", []):
        register_ke_in_aop(str(aop), ke_id)

    _print_ke_summary(ke_id, title, annotated_ke, new_fields, ref_comments)
    return KE_ANNOTATIONS_PATH


def _build_ke_annotation(
    ke_id: str,
    title: str,
    api_key: str,
    description: str = "",
    ref_ke: dict | None = None,
) -> dict:
    """Run the annotation sequence for one KE and return the annotation dict.

    Each line is one workflow step (the module docstring describes them);
    `ref_ke` supplies stored values that every step honors instead of
    re-querying.
    """
    client = make_client()
    print(f"KE {ke_id}: {title}\n")

    guidance = review_ref_comments(ref_ke, client, title)
    parsed = _parse_title(title)
    biological_action = _annotate_biological_action(parsed, client)
    org_level = _resolve_biological_organization(description, ref_ke, client)
    location_terms = _annotate_location_terms(
        parsed, title, api_key, client, ref_ke, org_level, guidance
    )
    ec_annotations = _annotate_subjects(
        parsed["subjects"], title, api_key, client, ref_ke, biological_action, guidance
    )

    return {
        "ke_id": ke_id,
        "title": title,
        "biological_organization": org_level,
        **location_terms,
        "ec_annotations": ec_annotations,
    }


# ---------------------------------------------------------------------------
# Workflow steps, in execution order
# ---------------------------------------------------------------------------

def review_ref_comments(
        ref_ke: dict | None,
        client,
        title: str
    ) -> str | None:
    """Show prior curator comments and return an LLM summary of them.

    The summary is threaded into every term-ranking call for this KE as
    `curator_guidance` context, so prior feedback steers re-annotation.
    """
    ref_comments = _flat_ref_comments((ref_ke or {}).get("comments"))
    if not ref_comments or client is None:
        return None
    print("--- prior comments ---")
    for c in ref_comments:
        print(f"  • {c}")
    print()
    review = call_text(client, prompts.review_curator_comments(title, ref_comments), max_tokens=256)
    if review is not None:
        print(f"  LLM review: {review}\n")
    return review


def _parse_title(title: str) -> dict:
    """Parse the KE title into ECS source phrases and show what was found."""
    parsed = parse_ke_title(title)
    print("Parsed ECS source phrases:")
    for k, v in parsed.items():
        print(f"  {k}: {v!r}")
    print()
    return parsed


def _annotate_biological_action(parsed: dict, client) -> dict:
    """Resolve the direction phrase to a controlled-vocab action term."""
    print("--- biological_action ---")
    if parsed["biological_action"] is not None:
        print(f"  Detected (controlled vocab): {parsed['biological_action']!r}\n")
        return {"term": parsed["biological_action"], "source": "controlled_vocab"}
    llm_action = llm_normalize_biological_action(parsed["raw_direction"], client) if client else None
    if llm_action:
        print(f"  LLM normalized to: {llm_action!r}\n")
        return {"term": llm_action, "source": "llm_normalization"}
    print(f"  No match for {parsed['raw_direction']!r} — biological_action set to null\n")
    return {"term": None, "source": "unmatched"}


def _resolve_biological_organization(
    description: str,
    ref_ke: dict | None,
    client,
) -> str | None:
    """Use the stored organization level, or detect it from the description."""
    print("--- biological_organization ---")
    ref_org = (ref_ke or {}).get("biological_organization")
    if ref_org is not None:
        print(f"  (reference) {ref_org!r} — skipping detection")
        org_level = ref_org
    else:
        org_level = detect_biological_organization(description, client)
    print()
    return org_level


def _annotate_location_terms(
    parsed: dict,
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    ref_ke: dict | None,
    org_level: str | None,
    guidance: str | None,
) -> dict:
    """Annotate the three KE-level location fields, each gated by org level.

    cell_term and organ_term are queried on the full subject phrase.
    cellular_component is queried on the extracted subcellular-location noun
    (e.g. "mitochondrion"), NOT the full subject — the location is an adjective
    embedded in a process phrase, so querying the whole phrase returns the
    process/complex, not the organelle. When no location word is present the
    hint is None and _annotate_location_term skips the query.
    """
    return {
        "cell_term": _annotate_location_term(
            "cell_term", _CELL_TERM_LEVELS,
            parsed["full_subject"], title, api_key, client, ref_ke, org_level, guidance,
        ),
        "organ_term": _annotate_location_term(
            "organ_term", _ORGAN_TERM_LEVELS,
            parsed["full_subject"], title, api_key, client, ref_ke, org_level, guidance,
        ),
        "cellular_component": _annotate_location_term(
            "cellular_component", _CELLULAR_COMPONENT_LEVELS,
            parsed.get("cellular_component"), title, api_key, client, ref_ke, org_level, guidance,
        ),
    }


def _annotate_location_term(
    field: str,
    trigger_levels: set[str],
    query: str,
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    ref_ke: dict | None,
    org_level: str | None,
    guidance: str | None = None,
) -> dict | None:
    """Return a ref value if present, or annotate from BioPortal if org_level matches trigger_levels."""
    ref_val = (ref_ke or {}).get(field)
    if ref_val is not None:
        print(f"--- {field} ---")
        print(f"  (reference) {_ref_term_label(ref_val)!r} — skipping query")
        print()
        return ref_val
    if query and org_level in trigger_levels:
        print(f"--- {field} ---")
        result = annotate_term(query, TOP_LEVEL_ONTOLOGIES[field], field, title, api_key, client,
                               context=_guidance_context(guidance))
        print()
        return result
    return None


def _annotate_subjects(
    subjects: list[str],
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    ref_ke: dict | None,
    biological_action: dict,
    guidance: str | None,
) -> list[dict]:
    """Annotate every subject phrase, attaching the shared biological_action."""
    ref_subjects: dict[str, dict] = {
        s["subject"]: s
        for s in (ref_ke or {}).get("ec_annotations", [])
        if isinstance(s, dict) and "subject" in s
    }
    annotations = []
    for i, subject in enumerate(subjects):
        if len(subjects) > 1:
            print(f"\n[Subject {i + 1}/{len(subjects)}: {subject!r}]")
        subj_annotation = _annotate_subject(
            subject, title, api_key, client,
            ref=ref_subjects.get(subject), guidance=guidance,
        )
        subj_annotation["biological_action"] = biological_action
        annotations.append(subj_annotation)
    return annotations


def _annotate_subject(
    subject: str,
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    ref: dict | None = None,
    guidance: str | None = None,
) -> dict:
    """
    Annotate the three ECS components (biological_object, biological_process, phenotype)
    for one KE subject phrase. When `ref` is supplied, any non-null field is used directly.
    """
    subj_annotation: dict = {
        "subject": subject,
        "biological_object": None,
        "biological_process": None,
        "phenotype": None,
    }

    if client is not None:
        decomposed = llm_decompose_subject(subject, client)
    else:
        decomposed = None

    if decomposed:
        object_phrase, _ = decomposed
        print(f"  (LLM decomposition: object={object_phrase!r}, process={subject!r})")
    else:
        object_phrase = extract_biological_object(subject)

    # --- biological_object ---
    print("--- biological_object ---")
    ref_object = _stored_ref(ref, "biological_object")
    if ref_object is not None:
        subj_annotation["biological_object"] = ref_object
        selected_object_label = ref_object.get("label") if not is_rejection(ref_object) else None
    else:
        term = annotate_term(object_phrase, ECS_ONTOLOGIES["biological_object"], "biological_object", title, api_key, client,
                             context=_guidance_context(guidance))
        subj_annotation["biological_object"] = term
        selected_object_label = term.get("label") if term else None
    print()

    # --- biological_process ---
    print("--- biological_process ---")
    subj_annotation["biological_process"] = _annotate_biological_process(
        subject, title, api_key, client, selected_object_label, ref, guidance
    )
    print()

    # --- phenotype ---
    print("--- phenotype ---")
    ref_phenotype = _stored_ref(ref, "phenotype")
    if ref_phenotype is not None:
        subj_annotation["phenotype"] = ref_phenotype
    else:
        term = annotate_term(subject, ECS_ONTOLOGIES["phenotype"], "phenotype", title, api_key, client,
                             context=_guidance_context(guidance))
        if term and term.get("term_id"):
            needs_review = term.get("ontology", "").upper() in _PHENOTYPE_GO_REVIEW_PREFIXES
            if needs_review:
                print("  ⚠ GO term assigned as phenotype — needs manual review")
                term["needs_review"] = True
        subj_annotation["phenotype"] = term
    print()

    return subj_annotation


def _annotate_biological_process(
    subject: str,
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    selected_object_label: str | None,
    ref: dict | None,
    guidance: str | None = None,
) -> dict | None:
    """Search, filter, and rank a biological_process term for a KE subject phrase."""
    ref_process = _stored_ref(ref, "biological_process")
    if ref_process is not None:
        return ref_process

    result_filter = None
    context = _guidance_context(guidance, selected_object=selected_object_label)
    if selected_object_label:

        def result_filter(results):
            kept, filtered_out = partition_process_results(results, selected_object_label)
            if filtered_out:
                print(
                    f"  Filtered out {len(filtered_out)} off-target result(s)"
                    f" (not '{selected_object_label}'):"
                )
                for r in filtered_out:
                    print(f"    ✗ [{r['ontology']}] {r['label']!r}")
                print()
            return kept

    return annotate_term(
        subject, ECS_ONTOLOGIES["biological_process"], "biological_process",
        title, api_key, client, context=context, result_filter=result_filter,
    )


# ---------------------------------------------------------------------------
# LLM primitives used by the steps
# ---------------------------------------------------------------------------

def llm_normalize_biological_action(direction: str, client: anthropic.Anthropic) -> str | None:
    """Map a direction phrase to the nearest WIKI_ACTION_WORDS term via LLM."""
    prompt = prompts.normalize_biological_action(direction, WIKI_ACTION_WORDS)
    parsed = call_json(client, prompt, max_tokens=64)
    if parsed:
        term = parsed.get("term")
        reason = parsed.get("reason", "")
        if term and term in WIKI_ACTION_WORDS:
            print(f"  (LLM normalized {direction!r} → {term!r}: {reason})")
            return term
    return None


def llm_decompose_subject(subject: str, client: anthropic.Anthropic) -> tuple[str, str] | None:
    """
    Ask Claude to split a KE subject phrase into (biological_object, biological_process).
    Returns (object_phrase, process_phrase) or None.
    """
    parsed = call_json(client, prompts.decompose_subject(subject), max_tokens=128)
    if parsed:
        obj = parsed.get("biological_object", "").strip()
        proc = parsed.get("biological_process", "").strip()
        if obj and proc:
            return obj, proc
    return None


def detect_biological_organization(description: str, client: anthropic.Anthropic | None) -> str | None:
    """
    Determine the level of biological organization for a KE from its description.
    Uses LLM when available; falls back to interactive prompt in tty sessions.
    """
    if client is not None:
        prompt = prompts.classify_biological_organization(description, BIOLOGICAL_ORGANIZATION_LEVELS)
        parsed = call_json(client, prompt, max_tokens=64)
        if parsed:
            level = parsed.get("level", "").strip()
            reason = parsed.get("reason", "")
            if level in BIOLOGICAL_ORGANIZATION_LEVELS:
                print(f"  (LLM: {level!r} — {reason})")
                return level
        print("  (LLM organization detection failed — falling back to manual)")

    if not sys.stdin.isatty():
        print("  (non-interactive mode — skipping manual selection)")
        return None

    print("  Levels of biological organization:")
    for i, level in enumerate(BIOLOGICAL_ORGANIZATION_LEVELS, 1):
        print(f"    {i}. {level}")
    choice = input(
        f"  Select level (1-{len(BIOLOGICAL_ORGANIZATION_LEVELS)}, Enter to skip, q=quit): "
    ).strip().lower()
    if choice == "q":
        print("Quitting.")
        raise SystemExit(0)
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(BIOLOGICAL_ORGANIZATION_LEVELS):
            return BIOLOGICAL_ORGANIZATION_LEVELS[idx]
    return None


# ---------------------------------------------------------------------------
# Shared helpers for the steps
# ---------------------------------------------------------------------------

def _ref_term_label(term: dict) -> str:
    """Return a short display string for a stored reference term or rejection."""
    if is_rejection(term):
        return f"[rejected: {term.get('rejection_reason', '')}]"
    if "comment" in term:
        return f"[comment: {term['comment']}]"
    return term.get("label", str(term))


def _stored_ref(ref: dict | None, field: str):
    """Return the stored reference value for `field`, printing the skip notice.

    Returns None when the reference has no value for the field, meaning the
    caller should compute one.
    """
    val = (ref or {}).get(field)
    if val is not None:
        print(f"  (reference) {_ref_term_label(val)!r} — skipping query")
    return val


def _guidance_context(guidance: str | None, **extra) -> dict | None:
    """Build a rank_term context dict from curator guidance plus extras, or None."""
    context = {k: v for k, v in extra.items() if v}
    if guidance:
        context["curator_guidance"] = guidance
    return context or None


def partition_process_results(results: list, object_label: str) -> tuple[list, list]:
    """
    Split process results into (kept, filtered_out) based on the resolved object label.
    Filters out terms specific to a different variant of the object.
    """
    object_words = [w for w in object_label.lower().split() if w not in STOPWORDS]
    kept, filtered_out = [], []
    for r in results:
        label_lower = r["label"].lower()
        has_any_object_word = any(w in label_lower for w in object_words)
        has_full_object = object_label.lower() in label_lower
        if not has_any_object_word or has_full_object:
            kept.append(r)
        else:
            filtered_out.append(r)
    return kept, filtered_out


# ---------------------------------------------------------------------------
# Store & metadata helpers
# ---------------------------------------------------------------------------

def _flat_ref_comments(raw) -> list[str]:
    """Normalize reference comments to a flat list regardless of storage format."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(c) for c in raw]
    if isinstance(raw, dict):
        items: list[str] = []
        for bucket in ("carried", "new"):
            for c in raw.get(bucket, []):
                if isinstance(c, list):
                    items.extend(str(x) for x in c)
                else:
                    items.append(str(c))
        return items
    return []


def _add_comment(ke_id: str, comment: str) -> None:
    store = load_ke_annotations()
    if ke_id not in store:
        print(f"KE {ke_id} not found in shared store — annotate it first.")
        sys.exit(1)
    store[ke_id].setdefault("comments", {"carried": [], "new": []})
    store[ke_id]["comments"]["new"].append(comment)
    save_ke_annotations(store)
    print(f"Comment added to KE {ke_id}. Saved to {KE_ANNOTATIONS_PATH}")


def _strip_carried_suffix(comment: str) -> str:
    """Remove all trailing '[carried from reference]' suffixes from a comment string."""
    return re.sub(r'(\s*\[carried from reference\])+$', '', comment).strip()


def _mask_ref(ref_ke: dict, force_fields: set[str]) -> dict:
    """
    Return a copy of ref_ke with specified fields set to None.
    For ECS fields (phenotype, biological_process, biological_object, biological_action),
    the field is nulled in every subject within ec_annotations.
    """
    masked = copy.deepcopy(ref_ke)
    top_level_fields = {"biological_organization", "cell_term", "organ_term",
                        "cellular_component", "assays"}
    ecs_fields = {"biological_object", "biological_process", "phenotype", "biological_action"}
    for field in force_fields:
        if field in top_level_fields and field in masked:
            masked[field] = None
        if field in ecs_fields:
            for subj in masked.get("ec_annotations", []):
                if field in subj:
                    subj[field] = None
    return masked


def _attach_comments(annotation: dict, ref_ke: dict | None) -> list[str]:
    """Attach the comments block to the annotation dict. Returns the raw ref comments."""
    ref_comments = _flat_ref_comments((ref_ke or {}).get("comments"))
    clean_comments = [_strip_carried_suffix(c) for c in ref_comments]
    annotation["comments"] = {
        "carried": [f"{c} [carried from reference]" for c in clean_comments],
        "new": [],
    }
    return ref_comments


def _compute_newly_updated_fields(effective_ref: dict | None, final_stored: dict) -> list[str]:
    """
    Return field names newly populated in final_stored relative to effective_ref.
    A field is considered newly updated if it was None/absent in the ref and is now non-None.
    Covers top-level fields, assay entries, and per-subject ec_annotation fields.
    """
    ref = effective_ref or {}
    new_fields: list[str] = []

    # Top-level fields: newly populated if ref was None and stored is now a real annotation
    for key in ("biological_organization", "cell_term", "organ_term", "cellular_component"):
        stored_val = final_stored.get(key)
        if stored_val is not None and not is_rejection(stored_val) and ref.get(key) is None:
            new_fields.append(key)

    # Assays: newly populated if ref had none and stored now has entries
    if final_stored.get("assays") and not ref.get("assays"):
        new_fields.append("assays")

    # Per-subject ECS fields
    for subj in final_stored.get("ec_annotations", []):
        ref_subj = next(
            (s for s in ref.get("ec_annotations", [])
             if s.get("subject") == subj.get("subject")),
            {},
        )
        for field in ("biological_object", "biological_process", "phenotype", "biological_action"):
            stored_val = subj.get(field)
            if stored_val is not None and not is_rejection(stored_val) and ref_subj.get(field) is None:
                label = f"ec_annotations[{subj['subject']!r}].{field}"
                if label not in new_fields:
                    new_fields.append(label)
    return new_fields


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

def _print_ke_summary(
    ke_id: str,
    title: str,
    annotation: dict,
    new_fields: list[str],
    ref_comments: list[str],
) -> None:
    print("\n" + "=" * 60)
    print(f"ANNOTATION SUMMARY — KE {ke_id}: {title}")
    print("=" * 60)
    print(f"  biological_organization: {annotation.get('biological_organization')}")
    cell = annotation.get("cell_term")
    organ = annotation.get("organ_term")
    cellcomp = annotation.get("cellular_component")
    print(f"  cell_term:  {cell.get('label') if cell else None}")
    print(f"  organ_term: {organ.get('label') if organ else None}")
    print(f"  cellular_component: {cellcomp.get('label') if cellcomp else None}")
    for subj in annotation.get("ec_annotations", []):
        action = subj.get("biological_action", {})
        obj = subj.get("biological_object")
        proc = subj.get("biological_process")
        phen = subj.get("phenotype")
        print(f"\n  subject: {subj['subject']!r}")
        print(f"    biological_action:  {action.get('term') if action else None}")
        print(f"    biological_object:  {obj.get('label') if obj else None}")
        print(f"    biological_process: {proc.get('label') if proc else None}")
        if phen:
            review_flag = " ⚠ needs_review" if phen.get("needs_review") else ""
            print(f"    phenotype:          {phen.get('label')}{review_flag}")
        else:
            print(f"    phenotype:          None")
    if new_fields:
        print(f"\n  Newly annotated: {new_fields}")
    if ref_comments:
        print(f"\n  Carried comments: {ref_comments}")
    print(f"\nSaved to {KE_ANNOTATIONS_PATH}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def get_fresh_event_cache(date_str: str | None = None):
    """Collect events for the given date (MM-DD-YYYY), defaulting to today."""
    work_date = (
        datetime.datetime.strptime(date_str, "%m-%d-%Y").date() if date_str else date.today()
    )
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)
    output_dir = 'outputs/event_rankings'
    os.makedirs(output_dir, exist_ok=True)

    # Collect and rank events (handles caching internally)
    collect_and_rank_events(work_date, cache_dir, output_dir, logger, None)


def main():
    parser = argparse.ArgumentParser(description="Annotate AOP-Wiki Key Events with ontology terms")
    parser.add_argument("--aop", default=None, help="AOP ID (e.g. 173); omit to annotate a KE standalone")
    parser.add_argument("--ke-id", default=None, help="Annotate a single KE by ID")
    parser.add_argument("--add-comment", default=None, help="Append a comment to a KE (requires --ke-id)")
    parser.add_argument("--force", action="store_true", help="Re-annotate all fields from scratch")
    parser.add_argument(
        "--force-on",
        metavar="FIELD",
        action="append",
        dest="force_fields",
        default=[],
        help=(
            "Re-annotate a specific field while keeping all other reference values. "
            "Can be repeated. Valid fields: biological_organization, cell_term, organ_term, "
            "cellular_component, biological_object, biological_process, phenotype, "
            "biological_action, assays."
        ),
    )
    parser.add_argument(
        "--date",
        default=date.today().strftime("%m-%d-%Y"),
        help="Cache date MM-DD-YYYY (default: today)",
    )
    args = parser.parse_args()

    cache = events_cache_file(args.date)
    if not os.path.exists(cache):
        print(f"Cache file not found: {cache}")
        get_fresh_event_cache(args.date)
        cache = events_cache_file(args.date)
        if not os.path.exists(cache):
            print(f"Unable to generate cache file for {args.date}: {cache}")
            sys.exit(1)

    if args.add_comment:
        if not args.ke_id:
            print("--add-comment requires --ke-id")
            sys.exit(1)
        _add_comment(args.ke_id, args.add_comment)
        return

    force_fields = set(args.force_fields) if args.force_fields else None
    if args.ke_id is None:
        if args.aop is None:
            print("Provide --ke-id to annotate a KE, or --aop to list KEs for an AOP.")
            sys.exit(1)
        kes = list_aop_kes(args.aop, cache)
        if not kes:
            print(f"No KEs found for AOP {args.aop}")
            sys.exit(1)
        store = load_ke_annotations()
        print(f"\nAOP {args.aop} — {len(kes)} KEs")
        print(f"KE annotations: {KE_ANNOTATIONS_PATH}")
        print(f"AOP KE index:   {AOP_KE_INDEX_PATH}")
        print()
        for ke_id, _ in kes:
            ke_entry = store.get(ke_id)
            already_complete = ke_entry and ke_entry.get("schema_version") == ANNOTATION_SCHEMA_VERSION
            if already_complete and not args.force and not force_fields:
                print(f"KE {ke_id} is already fully annotated (schema v{ANNOTATION_SCHEMA_VERSION}).")
                continue
            annotate_ke(ke_id, cache, force=args.force, force_fields=force_fields)
        return

    store = load_ke_annotations()
    # A KE is "complete" when it carries the current ANNOTATION_SCHEMA_VERSION,
    # stamped by annotate_ke() as its final step. A plain run skips complete KEs;
    # --force / --force-on bypass this to re-annotate all or specific fields.
    if (args.ke_id in store and not args.force and not force_fields
            and store[args.ke_id].get("schema_version") == ANNOTATION_SCHEMA_VERSION):
        print(f"KE {args.ke_id} is fully annotated (schema v{ANNOTATION_SCHEMA_VERSION}). "
              f"Use --force to re-annotate or --force-on <field> to re-annotate specific fields.")
        return

    annotate_ke(args.ke_id, cache, force=args.force, force_fields=force_fields)


if __name__ == "__main__":
    load_dotenv()
    main()
