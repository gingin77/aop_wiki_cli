"""
Shared helpers for ontology term search, ranking, and selection.

Used by annotate_ke.py and structure_ke_how_is_it_measured_text.py.
"""

import json
import os
import re
import sys

import anthropic

from query_bioportal import search_bioportal_with_fallback

LLM_MODEL = "claude-sonnet-4-6"

ECS_ONTOLOGIES = {
    # PR (Protein Ontology) and HGNC (gene nomenclature) cover molecular-level
    # objects such as receptors, proteins, and genes (e.g. LXR alpha / NR1H3)
    # that CL/UBERON/CHEBI do not.
    "biological_object": "CL,UBERON,CHEBI,PR,HGNC",
    "biological_process": "GO",
    "phenotype": "UPHENO,HP,MP",
}


def _make_client() -> anthropic.Anthropic | None:
    """Create and return an Anthropic client, or None if the API key is not set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _call_llm_json(client: anthropic.Anthropic, prompt: str, max_tokens: int) -> dict | None:
    """Call the LLM with prompt and parse the first JSON object from the response."""
    try:
        message = client.messages.create(
            model=LLM_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return None
        return json.loads(json_match.group())
    except Exception:
        return None


def llm_rank_term(
    ke_title: str,
    component: str,
    candidates: list,
    client: anthropic.Anthropic,
    context: dict | None = None,
) -> tuple[int | None, str]:
    """
    Ask Claude to pick the best ontology term from a candidate list.
    Returns (0-based index, reason). Returns (None, reason) when no confident match.
    """
    numbered = []
    for i, r in enumerate(candidates, 1):
        syns = ", ".join(r.get("synonyms", [])[:3])
        syn_str = f"  synonyms: {syns}" if syns else ""
        numbered.append(f"{i}. {r['label']} [{r['ontology']}]{chr(10)}{syn_str}".strip())
    candidate_block = "\n".join(numbered)

    context_str = ""
    if context:
        context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
        context_str = f"\nAdditional context:\n{context_str}\n"

    component_guidance = {
        "cell_term": (
            "Cell terms must be actual cell types from the Cell Ontology (CL). "
            "Reject any term that is a biological process, molecular function, or anatomical structure — "
            "even if it appears in the candidate list. If no candidate is a genuine cell type, return null."
        ),
        "organ_term": (
            "Organ terms must be anatomical structures or tissues from UBERON. "
            "Reject any term that is a biological process or molecular function."
        ),
        "biological_process": (
            "Biological process terms should be GO biological process terms describing "
            "the activity or process represented by the KE subject phrase."
        ),
        "biological_object": (
            "Biological object terms represent the cell type, tissue, molecule, or anatomical entity "
            "acted upon. Prefer CL for cell types, UBERON for anatomy, ChEBI for chemicals."
        ),
        "phenotype": (
            "Phenotype terms should come from UPHENO, HP (Human Phenotype Ontology), or MP (Mammalian Phenotype). "
            "GO terms may appear in the candidate list because some are incorporated into UPHENO, but prefer "
            "a dedicated phenotype term when available. If a GO term is the only reasonable match, select it — "
            "it will be flagged for manual review."
        ),
    }
    guidance = component_guidance.get(component, "")
    guidance_str = f"\nComponent guidance: {guidance}\n" if guidance else ""

    prompt = (
        f"You are annotating an AOP-Wiki Key Event (KE) with ontology terms.\n"
        f"KE title: {ke_title!r}\n"
        f"ECS component to annotate: {component}\n"
        f"{guidance_str}"
        f"{context_str}\n"
        f"Candidate ontology terms (choose the single best match):\n{candidate_block}\n\n"
        f"Reply with ONLY a JSON object: {{\"index\": <1-based integer>, \"reason\": \"<one sentence>\"}}\n"
        f"If none are a good match, use {{\"index\": null, \"reason\": \"...\"}}"
    )

    message = client.messages.create(
        model=LLM_MODEL,
        max_tokens=128,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        return None, f"Could not parse LLM response: {raw!r}"
    try:
        parsed_resp = json.loads(json_match.group())
    except json.JSONDecodeError:
        return None, f"Could not parse LLM response: {raw!r}"
    if not isinstance(parsed_resp, dict):
        return None, f"Unexpected LLM response: {raw!r}"
    idx_1based = parsed_resp.get("index")
    reason = parsed_resp.get("reason", "")
    if idx_1based is None:
        return None, reason
    try:
        idx = int(idx_1based)
    except (TypeError, ValueError):
        return None, f"Invalid index {idx_1based!r} from LLM: {reason}"
    if not 1 <= idx <= len(candidates):
        return None, f"Out-of-range index {idx} from LLM (expected 1-{len(candidates)}): {reason}"
    return idx - 1, reason


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
        idx, reason = llm_rank_term(ke_title, component, candidates, client, context)
        source = "llm_recommendation"
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


def _annotate_term(
    phrase: str,
    ontologies: str,
    component: str,
    title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
) -> dict | None:
    """Search BioPortal and select an ontology term for a KE-level component (cell_term, organ_term)."""
    if not ontologies:
        print(f"  No ontologies configured for {component} — skipping.")
        return None
    print(f"  Query phrase: {phrase!r}")
    print(f"  Ontologies:   {ontologies}")
    results, query_used = search_bioportal_with_fallback(phrase, ontologies, api_key)
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
    display_candidates(results[:5], query_used)
    result, source, reason = rank_term(title, component, results[:5], client)
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
