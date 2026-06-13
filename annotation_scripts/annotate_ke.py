"""
Annotate AOP-Wiki Key Events with bio-ontology terms using BioPortal + Claude.

This script is designed to make use of LLM annotations that have already been stored
and are under version control in `outputs_for_vc/annotations/`.

Storage model within `outputs_for_vc/annotations/` includees:
  - ke_annotations.json  — one entry per KE (single source of truth)
  - aop_ke_index.json    — AOP index, maps AOP ID → list of KE IDs

KEs already in the shared store are skipped during annotation (use --force to re-annotate).

Usage:
    # Annotate a standalone KE (no AOP required)
    uv run python scripts/annotate_ke.py --ke-id 14 --date 04-28-2026

    # Annotate a KE and register it under an AOP
    uv run python scripts/annotate_ke.py --aop 173 --ke-id 68 --date 04-28-2026

    # List KEs for an AOP with annotation status
    uv run python scripts/annotate_ke.py --aop 173 --date 04-28-2026

    # Re-annotate all fields from scratch
    uv run python scripts/annotate_ke.py --ke-id 68 --force --date 04-28-2026

    # Re-annotate only the assays
    uv run python scripts/annotate_ke.py --ke-id 68 --force-on assays --date 04-28-2026

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

from src.utilities import set_up_logger, get_dated_cache_dir
from src.analysis.collect_event_rankings import collect_and_rank_events


logger = set_up_logger('aop-wiki-annotate', level=logging.INFO)

from collect_aop_kes import (
    AOP_KE_INDEX_PATH,
    KE_ANNOTATIONS_PATH,
    load_ke_annotations,
    save_ke_annotations,
    list_aop_kes,
    register_ke_in_aop,
)
from ke_title_parser import (
    WIKI_ACTION_WORDS,
    extract_biological_object,
    parse_ke_title,
)
from query_bioportal import (
    STOPWORDS,
    search_bioportal_with_fallback,
)
from annotate_term_helpers import (
    ECS_ONTOLOGIES,
    LLM_MODEL,
    _annotate_term,
    _call_llm_json,
    _make_client,
    display_candidates,
    rank_term,
)
from structure_ke_how_is_it_measured_text import annotate_ke_assays



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CELL_TERM_ONTOLOGIES = "CL"
ORGAN_TERM_ONTOLOGIES = "UBERON"

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

# GO terms may be valid phenotype terms (e.g. "hypersensitivity" is included in UPHENO),
# but many are biological processes and not appropriate as phenotype annotations.
# Flag for manual review when a GO term is selected as phenotype.
_PHENOTYPE_GO_REVIEW_PREFIXES = {"GO"}

CACHE_DIR_ROOT = "outputs/cache"


def _is_rejection(term) -> bool:
    """Return True if term is a stored LLM rejection record (not a real annotation)."""
    return isinstance(term, dict) and term.get("source") == "llm_rejection"


def _ref_term_label(term: dict) -> str:
    """Return a short display string for a stored reference term or rejection."""
    if _is_rejection(term):
        return f"[rejected: {term.get('rejection_reason', '')}]"
    if "comment" in term:
        return f"[comment: {term['comment']}]"
    return term.get("label", str(term))

# ---------------------------------------------------------------------------
# KE-specific LLM functions
# ---------------------------------------------------------------------------

def llm_normalize_biological_action(direction: str, client: anthropic.Anthropic) -> str | None:
    """Map a direction phrase to the nearest WIKI_ACTION_WORDS term via LLM."""
    vocab_str = ", ".join(f'"{w}"' for w in WIKI_ACTION_WORDS)
    prompt = (
        f"You are normalizing an AOP-Wiki Key Event direction phrase to a controlled vocabulary term.\n"
        f"Direction phrase: {direction!r}\n\n"
        f"Controlled vocabulary terms: {vocab_str}\n\n"
        f"Background: In AOP-Wiki, action terms describe either the direction of a perturbation "
        f"(e.g. increased, decreased) or an observation of the perturbation itself. "
        f"'occurrence' is a valid action term for events that are observed to happen without "
        f"an explicit directional change — for example, the formation of a lesion, the "
        f"presence of an interaction, or the manifestation of a pathological state.\n\n"
        f"If the phrase is semantically equivalent to one of these terms, return it exactly as written above.\n"
        f'Reply with ONLY valid JSON: {{"term": "<matched term or null>", "reason": "<one sentence>"}}'
    )
    parsed = _call_llm_json(client, prompt, max_tokens=64)
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
    prompt = (
        f"You are parsing an AOP-Wiki Key Event subject phrase into ECS components.\n"
        f"Subject phrase: {subject!r}\n\n"
        f"Identify:\n"
        f"- biological_object: the cell type, tissue, molecule, or anatomical entity\n"
        f"- biological_process: the activity or process (use the full subject phrase as-is)\n\n"
        f"Reply with ONLY valid JSON: "
        f'{{\"biological_object\": \"<phrase>\", \"biological_process\": \"<phrase>\"}}\n'
        f"Use only words that appear in the subject phrase."
    )
    parsed = _call_llm_json(client, prompt, max_tokens=128)
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
        levels_str = ", ".join(BIOLOGICAL_ORGANIZATION_LEVELS)
        prompt = (
            f"You are classifying an AOP-Wiki Key Event by level of biological organization.\n"
            f"KE description (excerpt):\n{(description or '')[:500]!r}\n\n"
            f"Choose the single best level from: {levels_str}\n"
            f'Reply with ONLY valid JSON: {{"level": "<level>", "reason": "<one sentence>"}}'
        )
        parsed = _call_llm_json(client, prompt, max_tokens=64)
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
# Per-component annotation helpers
# ---------------------------------------------------------------------------

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


def _annotate_biological_process(
    subject: str,
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    selected_object_label: str | None,
    ref: dict | None,
) -> dict | None:
    """Search, filter, and rank a biological_process term for a KE subject phrase."""
    ref_process = (ref or {}).get("biological_process")
    if ref_process is not None:
        print(f"  (reference) {_ref_term_label(ref_process)!r} — skipping query")
        return ref_process

    print(f"  Query phrase: {subject!r}")
    print(f"  Ontologies:   {ECS_ONTOLOGIES['biological_process']}")
    process_results, process_used = search_bioportal_with_fallback(
        subject, ECS_ONTOLOGIES["biological_process"], api_key
    )
    if not process_results:
        print("  No matches found after fallback — manual curation needed.")
        return None

    if selected_object_label:
        kept, filtered_out = partition_process_results(process_results, selected_object_label)
        if filtered_out:
            print(
                f"  Filtered out {len(filtered_out)} off-target result(s)"
                f" (not '{selected_object_label}'):"
            )
            for r in filtered_out:
                print(f"    ✗ [{r['ontology']}] {r['label']!r}")
            print()
    else:
        kept = process_results

    if not kept:
        print("  No results remain after filtering — manual curation needed.")
        return None

    display_candidates(kept[:5], process_used)
    context = {"selected_object": selected_object_label} if selected_object_label else None
    result, source, reason = rank_term(title, "biological_process", kept[:5], client, context)
    if result:
        print(f"  → [{result['ontology']}] {result['label']}")
        print(f"     IRI:    {result['term_id']}")
        print(f"     reason: {reason}")
        return {
            "term_id": result["term_id"],
            "label": result["label"],
            "ontology": result["ontology"],
            "reason": reason,
            "source": source,
        }
    elif source == "manual_comment":
        print(f"  → Comment recorded: {reason!r}")
        return {"comment": reason, "source": source}
    elif source == "llm_recommendation":
        print(f"  → LLM rejected all candidates: {reason}")
        return {"rejection_reason": reason, "source": "llm_rejection"}
    else:
        print(f"  → No selection made ({reason})")
        return None


def _annotate_subject(
    subject: str,
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    ref: dict | None = None,
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
    ref_object = (ref or {}).get("biological_object")
    if ref_object is not None:
        print(f"  (reference) {_ref_term_label(ref_object)!r} — skipping query")
        subj_annotation["biological_object"] = ref_object
        selected_object_label = ref_object.get("label") if not _is_rejection(ref_object) else None
    else:
        term = _annotate_term(object_phrase, ECS_ONTOLOGIES["biological_object"], "biological_object", title, api_key, client)
        subj_annotation["biological_object"] = term
        selected_object_label = term.get("label") if term else None
    print()

    # --- biological_process ---
    print("--- biological_process ---")
    subj_annotation["biological_process"] = _annotate_biological_process(
        subject, title, api_key, client, selected_object_label, ref
    )
    print()

    # --- phenotype ---
    print("--- phenotype ---")
    ref_phenotype = (ref or {}).get("phenotype")
    if ref_phenotype is not None:
        print(f"  (reference) {_ref_term_label(ref_phenotype)!r} — skipping query")
        subj_annotation["phenotype"] = ref_phenotype
    else:
        term = _annotate_term(subject, ECS_ONTOLOGIES["phenotype"], "phenotype", title, api_key, client)
        if term and term.get("term_id"):
            needs_review = term.get("ontology", "").upper() in _PHENOTYPE_GO_REVIEW_PREFIXES
            if needs_review:
                print("  ⚠ GO term assigned as phenotype — needs manual review")
                term["needs_review"] = True
        subj_annotation["phenotype"] = term
    print()

    return subj_annotation

def pass_ref_comments_to_llm(
        ref_ke: dict | None, 
        client, 
        title: str
    ) -> None:
    # --- review prior comments ---
    ref_comments = _flat_ref_comments((ref_ke or {}).get("comments"))
    if ref_comments and client is not None:
        print("--- prior comments ---")
        for c in ref_comments:
            print(f"  • {c}")
        print()
        comments_block = "\n".join(f"- {c}" for c in ref_comments)
        prompt = (
            f"You are reviewing curator comments on an AOP-Wiki Key Event annotation.\n"
            f"KE title: {title!r}\n\n"
            f"Prior curator comments:\n{comments_block}\n\n"
            f"Summarise in 2-3 sentences what these comments tell you about how the "
            f"annotation should be improved. Focus on actionable guidance for selecting "
            f"better ontology terms."
        )
        try:
            message = client.messages.create(
                model=LLM_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            print(f"  LLM review: {message.content[0].text.strip()}\n")
        except Exception as e:
            print(f"  (LLM comment review failed: {e})\n")

def _annotate_location_term(
    field: str,
    ontologies: str,
    trigger_levels: set[str],
    query: str,
    context: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    ref_ke: dict | None,
    org_level: str | None,
) -> dict | None:
    """Return a ref value if present, or annotate from BioPortal if org_level matches trigger_levels."""
    ref_val = (ref_ke or {}).get(field)
    if ref_val is not None:
        print(f"--- {field} ---")
        print(f"  (reference) {_ref_term_label(ref_val)!r} — skipping query")
        print()
        return ref_val
    if org_level in trigger_levels:
        print(f"--- {field} ---")
        result = _annotate_term(query, ontologies, field, context, api_key, client)
        print()
        return result
    return None


def _build_ke_annotation(
    ke_id: str,
    title: str,
    api_key: str,
    description: str = "",
    ref_ke: dict | None = None,
) -> dict:
    """Run the full ECS annotation workflow for a single KE. Returns the annotation dict."""
    client = _make_client()

    print(f"KE {ke_id}: {title}\n")

    pass_ref_comments_to_llm(ref_ke, client, title)

    parsed = parse_ke_title(title)
    print("Parsed ECS source phrases:")
    for k, v in parsed.items():
        print(f"  {k}: {v!r}")
    print()

    annotation: dict = {
        "ke_id": ke_id,
        "title": title,
        "biological_organization": None,
        "cell_term": None,
        "organ_term": None,
        "ec_annotations": [],
    }

    # --- biological_action ---
    print("--- biological_action ---")
    if parsed["biological_action"] is not None:
        print(f"  Detected (controlled vocab): {parsed['biological_action']!r}\n")
        biological_action = {"term": parsed["biological_action"], "source": "controlled_vocab"}
    else:
        llm_action = llm_normalize_biological_action(parsed["raw_direction"], client) if client else None
        if llm_action:
            print(f"  LLM normalized to: {llm_action!r}\n")
            biological_action = {"term": llm_action, "source": "llm_normalization"}
        else:
            print(f"  No match for {parsed['raw_direction']!r} — biological_action set to null\n")
            biological_action = {"term": None, "source": "unmatched"}

    # --- biological_organization ---
    print("--- biological_organization ---")
    ref_org = (ref_ke or {}).get("biological_organization")
    if ref_org is not None:
        print(f"  (reference) {ref_org!r} — skipping detection")
        org_level = ref_org
    else:
        org_level = detect_biological_organization(description, client)
    annotation["biological_organization"] = org_level
    print()

    annotation["cell_term"] = _annotate_location_term(
        "cell_term", CELL_TERM_ONTOLOGIES, _CELL_TERM_LEVELS,
        parsed["full_subject"], description, api_key, client, ref_ke, org_level,
    )
    annotation["organ_term"] = _annotate_location_term(
        "organ_term", ORGAN_TERM_ONTOLOGIES, _ORGAN_TERM_LEVELS,
        parsed["full_subject"], description, api_key, client, ref_ke, org_level,
    )

    # --- ECS annotation ---
    ref_subjects: dict[str, dict] = {
        s["subject"]: s
        for s in (ref_ke or {}).get("ec_annotations", [])
        if isinstance(s, dict) and "subject" in s
    }
    for i, subject in enumerate(parsed["subjects"]):
        if len(parsed["subjects"]) > 1:
            print(f"\n[Subject {i + 1}/{len(parsed['subjects'])}: {subject!r}]")
        ref_subj = ref_subjects.get(subject)
        subj_annotation = _annotate_subject(subject, title, api_key, client, ref=ref_subj)
        subj_annotation["biological_action"] = biological_action
        annotation["ec_annotations"].append(subj_annotation)

    return annotation

# ---------------------------------------------------------------------------
# Annotation & Orchestration helpers
# ---------------------------------------------------------------------------
def _get_events_cache_file(date_str: str) -> str:
    return os.path.join(CACHE_DIR_ROOT, date_str, f"all_events_{date_str}.json")


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
    top_level_fields = {"biological_organization", "cell_term", "organ_term", "assays"}
    ecs_fields = {"biological_object", "biological_process", "phenotype", "biological_action"}
    for field in force_fields:
        if field in top_level_fields and field in masked:
            masked[field] = None
        if field in ecs_fields:
            for subj in masked.get("ec_annotations", []):
                if field in subj:
                    subj[field] = None
    return masked


def _build_annotation_metadata(ref_ke: dict | None, annotation: dict) -> tuple[dict, list[str]]:
    """
    Attach comments to the annotation dict.
    Returns (updated annotation, ref_comments).
    """
    ref_comments = _flat_ref_comments((ref_ke or {}).get("comments"))
    clean_comments = [_strip_carried_suffix(c) for c in ref_comments]
    annotation["comments"] = {
        "carried": [f"{c} [carried from reference]" for c in clean_comments],
        "new": [],
    }
    return annotation, ref_comments


def _compute_newly_updated_fields(effective_ref: dict | None, final_stored: dict) -> list[str]:
    """
    Return field names newly populated in final_stored relative to effective_ref.
    A field is considered newly updated if it was None/absent in the ref and is now non-None.
    Covers top-level fields, assay entries, and per-subject ec_annotation fields.
    """
    ref = effective_ref or {}
    new_fields: list[str] = []

    # Top-level fields: newly populated if ref was None and stored is now a real annotation
    for key in ("biological_organization", "cell_term", "organ_term"):
        stored_val = final_stored.get(key)
        if stored_val is not None and not _is_rejection(stored_val) and ref.get(key) is None:
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
            if stored_val is not None and not _is_rejection(stored_val) and ref_subj.get(field) is None:
                label = f"ec_annotations[{subj['subject']!r}].{field}"
                if label not in new_fields:
                    new_fields.append(label)
    return new_fields


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
    print(f"  cell_term:  {cell.get('label') if cell else None}")
    print(f"  organ_term: {organ.get('label') if organ else None}")
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
# Orchestration
# ---------------------------------------------------------------------------

def annotate_ke(
    ke_id: str,
    cache_file: str,
    force: bool = False,
    force_fields: set[str] | None = None,
) -> str:
    """
    Orchestration function to annotate one KE and write it to the shared store.
    AOP associations are read from the cache and recorded in the AOP store automatically.

    force=True re-annotates all fields from scratch.
    force_fields re-annotates only the named fields, keeping all others from the reference.
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

    annotated_ke, ref_comments = _build_annotation_metadata(ref_ke, annotated_ke)

    new_fields = _compute_newly_updated_fields(effective_ref, annotated_ke)
    if new_fields:
        annotated_ke["newly_annotated_fields"] = new_fields
    else:
        annotated_ke.pop("newly_annotated_fields", None)

    store[ke_id] = annotated_ke
    save_ke_annotations(store)
    for aop in events[ke_id].get("aop_ids", []):
        register_ke_in_aop(str(aop), ke_id)

    _print_ke_summary(ke_id, title, annotated_ke, new_fields, ref_comments)
    return KE_ANNOTATIONS_PATH

def get_fresh_event_cache():
    work_date = date.today()
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
            "biological_object, biological_process, phenotype, biological_action, assays."
        ),
    )
    parser.add_argument(
        "--date",
        default=date.today().strftime("%m-%d-%Y"),
        help="Cache date MM-DD-YYYY (default: today)",
    )
    args = parser.parse_args()

    cache = _get_events_cache_file(args.date)
    if not os.path.exists(cache):
        print(f"Cache file not found: {cache}")
        get_fresh_event_cache()
        cache = _get_events_cache_file(args.date)

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
            already_complete = ke_entry and ke_entry.get("assays") is not None
            if already_complete and not args.force and not force_fields:
                print(f"KE {ke_id} is already fully annotated.")
                continue
            annotate_ke(ke_id, cache, force=args.force, force_fields=force_fields)
        return

    store = load_ke_annotations()
    # The check for existing annotation is based on the presence of "assays" as a proxy for a complete annotation.
    # since that's the last step in the workflow, *currently*. This allows --force-on to work on specific fields
    # without being blocked by the presence of other annotated fields.   
    # TODO: When DOA annotation is implemented, this should be updated. 
    if args.ke_id in store and not args.force and not force_fields and store[args.ke_id].get("assays") is not None:
        print(f"KE {args.ke_id} is fully annotated. Use --force to re-annotate or --force-on <field> to re-annotate specific fields.")
        return

    annotate_ke(args.ke_id, cache, force=args.force, force_fields=force_fields)


if __name__ == "__main__":
    load_dotenv()
    main()
