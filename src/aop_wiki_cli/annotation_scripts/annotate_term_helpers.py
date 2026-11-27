"""
Shared helpers for ontology term search, ranking, and selection.

Used by annotate_ke.py and assay_extraction.py.
"""

import sys

import anthropic

from aop_wiki_cli.annotation_scripts import prompts
from aop_wiki_cli.annotation_scripts.llm import call_text, extract_json
from aop_wiki_cli.annotation_scripts.query_bioportal import search_bioportal_with_fallback

ECS_ONTOLOGIES = {
    # PR (Protein Ontology) and HGNC (gene nomenclature) cover molecular-level
    # objects such as receptors, proteins, and genes (e.g. LXR alpha / NR1H3)
    # that CL/UBERON/CHEBI do not.
    "biological_object": "CL,UBERON,CHEBI,PR,HGNC",
    "biological_process": "GO",
    "phenotype": "UPHENO,HP,MP",
}

# KE-level location fields. Subcellular structures / organelles
# (e.g. "Mitochondrial ...") are GO cellular_component terms. BioPortal exposes
# GO as a single ontology spanning process/function/component, so selection is
# steered by the LLM guidance in prompts.COMPONENT_GUIDANCE, which rejects
# non-cellular-component GO terms.
TOP_LEVEL_ONTOLOGIES = {
    "cell_term": "CL",
    "organ_term": "UBERON",
    "cellular_component": "GO",
}

# One field → BioPortal ontology-scope mapping for every curatable field.
FIELD_ONTOLOGIES = {**ECS_ONTOLOGIES, **TOP_LEVEL_ONTOLOGIES}

# Branch restrictions applied at search time via BioPortal's subtree_root_id.
# Only valid for fields whose scope is a single ontology (the API requires the
# singular `ontology` parameter with a subtree search). cellular_component is
# restricted to the GO cellular_component branch so BP/MF terms never reach
# the candidate list; biological_process is left unrestricted for now because
# GO-wide search has worked for it and a branch restriction would change
# long-standing behavior — add "biological_process": GO_0008150 here to
# restrict it the same way.
FIELD_SUBTREE_ROOTS = {
    "cellular_component": "http://purl.obolibrary.org/obo/GO_0005575",
}


def field_subtree_root(field: str, ontologies: str) -> str | None:
    """The subtree root to search under for `field`, or None.

    Returns None when the scope names more than one ontology, since
    BioPortal's subtree search accepts exactly one.
    """
    if "," in ontologies:
        return None
    return FIELD_SUBTREE_ROOTS.get(field)


def is_rejection(term) -> bool:
    """Return True if term is a stored LLM rejection record (not a real annotation)."""
    return isinstance(term, dict) and term.get("source") == "llm_rejection"


def llm_rank_term(
    ke_title: str,
    component: str,
    candidates: list,
    client: anthropic.Anthropic,
    context: dict | None = None,
) -> tuple[int | None, str, bool]:
    """
    Ask Claude to pick the best ontology term from a candidate list.

    Returns (0-based index | None, reason, judged). `judged` is False when the
    call or its parsing failed mechanically — no model judgment was obtained,
    so the outcome must not be stored as a rejection.
    """
    prompt = prompts.rank_term(ke_title, component, candidates, context)
    raw = call_text(client, prompt, max_tokens=256)
    if raw is None:
        return None, "LLM call failed", False
    parsed_resp = extract_json(raw)
    if parsed_resp is None:
        return None, f"Could not parse LLM response: {raw!r}", False
    idx_1based = parsed_resp.get("index")
    reason = parsed_resp.get("reason", "")
    if idx_1based is None:
        return None, reason, True
    try:
        idx = int(idx_1based)
    except (TypeError, ValueError):
        return None, f"Invalid index {idx_1based!r} from LLM: {reason}", False
    if not 1 <= idx <= len(candidates):
        return None, f"Out-of-range index {idx} from LLM (expected 1-{len(candidates)}): {reason}", False
    return idx - 1, reason, True


def display_candidates(candidates: list, query_used: str) -> None:
    print(f"  Matched via: {query_used}")
    for i, r in enumerate(candidates, 1):
        syns = ", ".join(r.get("synonyms", [])[:3])
        print(f"    {i}. [{r['ontology']}] {r['label']}")
        print(f"       IRI:      {r['term_id']}")
        if syns:
            print(f"       synonyms: {syns}")
        print()
    print()


def rank_term(
    ke_title: str,
    component: str,
    candidates: list,
    client: anthropic.Anthropic | None,
    context: dict | None = None,
) -> tuple[dict | None, str, str]:
    """
    Select the best candidate term via LLM (if client is available) or manual prompt.
    Returns (selected_result_dict | None, source, reason).
    """
    if client is not None:
        idx, reason, judged = llm_rank_term(ke_title, component, candidates, client, context)
        source = "llm_recommendation" if judged else "llm_error"
    else:
        print(f"  (Anthropic unavailable — manual selection)")
        if not sys.stdin.isatty():
            return None, "manual_selection", "skipped (non-interactive)"
        choice = input(
            f"  Select best {component} term (1-{len(candidates)}, m=enter manually, c=comment, Enter to skip, q=quit): "
        ).strip().lower()
        if choice == "q":
            print("Quitting.")
            raise SystemExit(0)
        if choice == "c":
            comment = input("  Comment: ").strip()
            return None, "manual_comment", comment
        if choice.isdigit():
            idx = int(choice) - 1
            idx = idx if 0 <= idx < len(candidates) else None
            reason = "manual selection" if idx is not None else "skipped"
            source = "manual_selection"
        elif choice == "m":
            term_id = input("  Term IRI: ").strip()
            label = input("  Term label: ").strip()
            ontology = input("  Ontology acronym (e.g. GO, CL, UBERON): ").strip()
            if term_id and label:
                return (
                    {"term_id": term_id, "label": label, "ontology": ontology, "synonyms": []},
                    "manual_entry",
                    "manually entered",
                )
            print("  IRI and label are required — skipping.")
            idx, reason, source = None, "skipped", "manual_selection"
        else:
            idx, reason, source = None, "skipped", "manual_selection"

    if idx is not None:
        return candidates[idx], source, reason
    return None, source, reason


def selection_to_record(result: dict | None, source: str, reason: str) -> dict | None:
    """Translate a rank_term outcome into the stored term record (or None)."""
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
    if source == "manual_comment":
        print(f"  → Comment recorded: {reason!r}")
        return {"comment": reason, "source": source}
    if source == "llm_error":
        # A mechanical failure is not a judgment: leave the field null so the
        # next run retries it, instead of storing a permanent rejection.
        print(f"  → LLM selection failed ({reason}) — field left null for retry")
        return None
    if source == "llm_recommendation":
        print(f"  → LLM rejected all candidates: {reason}")
        return {"rejection_reason": reason, "source": "llm_rejection"}
    print(f"  → No selection made ({reason})")
    return None


def annotate_term(
    phrase: str,
    ontologies: str,
    component: str,
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
    context: dict | None = None,
    result_filter=None,
) -> dict | None:
    """
    Search BioPortal for `phrase` and select one term for `component`.

    The pipeline is: search (with fallback queries) → drop off-target-ontology
    results → optional caller-supplied `result_filter` (list → list, printing
    its own diagnostics) → rank the top 5 → translate the outcome to a record.
    """
    if not ontologies:
        print(f"  No ontologies configured for {component} — skipping.")
        return None
    print(f"  Query phrase: {phrase!r}")
    print(f"  Ontologies:   {ontologies}")
    subtree_root = field_subtree_root(component, ontologies)
    if subtree_root:
        print(f"  Subtree:      {subtree_root}")
    results, query_used = search_bioportal_with_fallback(
        phrase, ontologies, api_key, subtree_root_iri=subtree_root
    )
    if not results:
        print("  No matches found after fallback — manual curation needed.")
        return None
    # Filter to only results from the requested ontologies.
    allowed = {o.strip().upper() for o in ontologies.split(",")}
    filtered = [r for r in results if r.get("ontology", "").upper() in allowed]
    if not filtered:
        print("  All results were from off-target ontologies — manual curation needed.")
        return None
    if len(filtered) < len(results):
        print(f"  Filtered out {len(results) - len(filtered)} off-target ontology result(s).")
    results = filtered
    if result_filter is not None:
        results = result_filter(results)
        if not results:
            print("  No results remain after filtering — manual curation needed.")
            return None
    display_candidates(results[:5], query_used)
    result, source, reason = rank_term(title, component, results[:5], client, context)
    return selection_to_record(result, source, reason)
