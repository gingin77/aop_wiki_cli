"""Extract structured, ontology-annotated assays from the free-text
"How is it measured or detected" field of a Key Event.

Proof of concept: demonstrates how AOP EMOD structures method-of-measurement
properties — each free-text method becomes an Assay record (title,
description, effect specificity, citations) whose measured biological
objects, processes, and taxa are resolved to ontology terms, mirroring the
EMOD Assay/Observation model rather than aiming for production completeness.
"""

import os
import re

import anthropic

from aop_wiki_cli.annotation_scripts import prompts
from aop_wiki_cli.annotation_scripts.llm import call_json, make_client
from aop_wiki_cli.annotation_scripts.annotate_term_helpers import (
    ECS_ONTOLOGIES,
    annotate_term,
)

# Ontology scopes for assay sub-fields that are not ECS components.
ASSAY_TYPE_ONTOLOGIES = "OBI,BAO"
TAXON_ONTOLOGIES = "NCBITAXON"


# ---------------------------------------------------------------------------
# Assay extraction
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r'<[^>]+>', ' ', html)
    for entity, char in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&apos;', "'"), ('&quot;', '"')]:
        text = text.replace(entity, char)
    return re.sub(r'\s+', ' ', text).strip()


def extract_assays_from_text(measurement_text: str, client: anthropic.Anthropic) -> list[dict] | None:
    """
    Extract structured assay objects from a KE measurement_method free-text field.
    Returns a list of assay dicts (IDs assigned sequentially starting at 1), or
    None when the LLM call fails or returns nothing parseable — a failure must
    stay distinguishable from "the text describes no assays".
    """
    parsed = call_json(client, prompts.extract_assays(measurement_text), max_tokens=4096)
    if not parsed:
        return None
    assays = parsed.get("assays") or []
    for i, assay in enumerate(assays, start=1):
        assay["id"] = i
    return assays


def _resolve_label_list(
    items: list | None,
    kind: str,
    ontologies: str,
    component: str,
    assay_title: str,
    api_key: str,
    client: anthropic.Anthropic | None,
) -> list[dict]:
    """Resolve each {"label": ...} entry to an ontology term (keeping the label
    when no term is selected)."""
    resolved = []
    for item in items or []:
        phrase = item.get("label", "")
        if phrase:
            print(f"  [{kind}] Looking up: {phrase!r}")
            term = annotate_term(phrase, ontologies, component, assay_title, api_key, client)
            resolved.append(term if term else {"label": phrase})
        else:
            resolved.append(item)
    return resolved


def annotate_ke_assays(ke_id: str, ke_data: dict) -> list[dict] | None:
    """
    Extract and annotate assays from the measurement_method field for one KE.
    Returns the list of annotated assay dicts ([] when the KE has no
    measurement text), or None when extraction failed — the caller must then
    leave the KE without assays rather than record an empty result.
    """
    client = make_client()
    if client is None:
        raise EnvironmentError("ANTHROPIC_API_KEY not set")

    raw_html = ke_data.get("measurement_method", "")
    if not raw_html:
        print(f"KE {ke_id} has no measurement_method field.")
        return []

    title = ke_data.get("title", "")
    text = _strip_html(raw_html)
    print(f"Extracting assays for KE {ke_id}: {title}")
    print(f"  Text length: {len(text)} chars")

    assays = extract_assays_from_text(text, client)
    if assays is None:
        print("  (assay extraction failed — KE left without assay results)")
        return None
    print(f"  Extracted {len(assays)} assay(s)")

    api_key = os.environ.get("BIOPORTAL_API_KEY")
    for assay in assays:
        assay_title = assay.get("title", "")
        if not api_key:
            assay["assay_type"] = None
            continue

        print(f"\n  [assay_type] Looking up: {assay_title!r}")
        assay["assay_type"] = annotate_term(assay_title, ASSAY_TYPE_ONTOLOGIES, "assay_type", assay_title, api_key, client) if assay_title else None

        assay["objects"] = _resolve_label_list(
            assay.get("objects"), "object", ECS_ONTOLOGIES["biological_object"],
            "biological_object", assay_title, api_key, client,
        )
        assay["processes"] = _resolve_label_list(
            assay.get("processes"), "process", ECS_ONTOLOGIES["biological_process"],
            "biological_process", assay_title, api_key, client,
        )
        assay["taxon_terms"] = _resolve_label_list(
            assay.get("taxon_terms"), "taxon", TAXON_ONTOLOGIES,
            "taxon_term", assay_title, api_key, client,
        )

    _print_assay_summary(ke_id, title, assays)
    return assays


def _term_suffix(term: dict) -> str:
    """' (ONTO:LOCALID)' when the entry resolved to a term, else ''."""
    tid = term.get("term_id", "").split("/")[-1]
    onto = term.get("ontology", "")
    return f" ({onto}:{tid})" if tid else ""


def _print_assay_summary(ke_id: str, title: str, assays: list[dict]) -> None:
    print("\n" + "=" * 60)
    print(f"ASSAY SUMMARY — KE {ke_id}: {title}")
    print("=" * 60)
    for assay in assays:
        print(f"\n  [{assay['id']}] {assay.get('title', '(untitled)')}")
        desc = (assay.get("description") or "")[:120]
        if desc:
            print(f"      description: {desc}")
        assay_type = assay.get("assay_type")
        if assay_type:
            print(f"      assay_type:  {assay_type.get('label')} ({assay_type.get('ontology')}:{assay_type.get('term_id', '').split('/')[-1]})")
        if assay.get("effect_specificity"):
            print(f"      effect_specificity: {assay['effect_specificity']}")
        for label, key in (("object:     ", "objects"),
                           ("process:    ", "processes"),
                           ("taxon:      ", "taxon_terms")):
            for item in assay.get(key) or []:
                print(f"      {label} {item.get('label')}{_term_suffix(item)}")
        citations = assay.get("citations") or []
        if citations:
            cit_strs = [f"{c.get('authors', '')} ({c.get('year', '')})" for c in citations]
            print(f"      citations:   {'; '.join(cit_strs)}")
    print("=" * 60)
