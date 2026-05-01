import os
import re
import json

import anthropic

from annotate_term_helpers import ECS_ONTOLOGIES, LLM_MODEL, _annotate_term, _make_client


# ---------------------------------------------------------------------------
# Assay extraction
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r'<[^>]+>', ' ', html)
    for entity, char in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&apos;', "'"), ('&quot;', '"')]:
        text = text.replace(entity, char)
    return re.sub(r'\s+', ' ', text).strip()


def extract_assays_from_text(measurement_text: str, client: anthropic.Anthropic) -> list[dict]:
    """
    Extract structured assay objects from a KE measurement_method free-text field.
    Returns a list of assay dicts; IDs are assigned sequentially starting at 1.
    """
    prompt = (
        "You are extracting structured assay information from text in an AOP-Wiki Key Event field,"
        '"How is it measured or detected".\n\n'
        f"Text:\n{measurement_text[:3000]}\n\n"
        "Purpose:\n" \
        "Extract assay information with specific focus on the biological elements being measured,"
        "which can be classified as biological objects, processes, and phenotypes."
        "If the assay is specific for a certain effect (ie 'agonist' or 'antagonist') or context, "
        "like the taxonomic domain, sex specificity or age, that should be captured.\n"
        "For each distinct assay or measurement method described, extract:\n"
        '- title: short assay name\n'
        '- description: brief description of what is measured and how\n'
        '- citations: list of citation objects, one per reference, each with title, authors, year, doi, pmid, journal\n'
        '  (null for fields not in the text); empty list if none mentioned\n'
        '- effect_specificity: whether the assay is designed to detect agonist or antagonist interactions —\n'
        '  one of: "agonist", "antagonist" (null if not applicable or not specified)\n'
        '- objects: list of biological entities the assay measures (biomolecules like receptors, cells, molecules, organs etc)\n'
        '  — each as {"label": "<name>"}\n'
        '- processes: list of biological processes captured — each as {"label": "<name>"}\n'
        '- taxon_terms: list of species/organisms used — each as {"label": "<species name>"}\n\n'
        'Rules:\n'
        '- One assay object per distinct method; do not merge unrelated methods\n'
        '- If a table lists multiple assay variants, extract each as a separate assay\n'
        '- Only include citation fields present in the text; use null for missing fields\n'
        '- If no citation is mentioned, set citation to null\n'
        '- Keep labels concise and specific\n\n'
        'Each assay object must use "citations" (plural, a list) not "citation".\n'
        'Reply with ONLY valid JSON: {"assays": [<assay objects>]}'
    )
    try:
        message = client.messages.create(
            model=LLM_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return []
        parsed = json.loads(json_match.group())
        assays = parsed.get("assays", [])
        for i, assay in enumerate(assays, start=1):
            assay["id"] = i
        return assays
    except Exception as e:
        print(f"  (assay extraction failed: {e})")
        return []


def annotate_ke_assays(ke_id: str, ke_data: dict) -> list[dict]:
    """
    Extract and annotate assays from the measurement_method field for one KE.
    Returns the list of annotated assay dicts; the caller is responsible for writing to the store.
    """
    client = _make_client()
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
    print(f"  Extracted {len(assays)} assay(s)")

    api_key = os.environ.get("BIOPORTAL_API_KEY")
    for assay in assays:
        assay_title = assay.get("title", "")
        if not api_key:
            assay["assay_type"] = None
            continue

        print(f"\n  [assay_type] Looking up: {assay_title!r}")
        assay["assay_type"] = _annotate_term(assay_title, "OBI,BAO", "assay_type", assay_title, api_key, client) if assay_title else None

        resolved_objects = []
        for obj in assay.get("objects") or []:
            phrase = obj.get("label", "")
            if phrase:
                print(f"  [object] Looking up: {phrase!r}")
                term = _annotate_term(phrase, ECS_ONTOLOGIES["biological_object"], "biological_object", assay_title, api_key, client)
                resolved_objects.append(term if term else {"label": phrase})
            else:
                resolved_objects.append(obj)
        assay["objects"] = resolved_objects

        resolved_processes = []
        for proc in assay.get("processes") or []:
            phrase = proc.get("label", "")
            if phrase:
                print(f"  [process] Looking up: {phrase!r}")
                term = _annotate_term(phrase, ECS_ONTOLOGIES["biological_process"], "biological_process", assay_title, api_key, client)
                resolved_processes.append(term if term else {"label": phrase})
            else:
                resolved_processes.append(proc)
        assay["processes"] = resolved_processes

        resolved_taxa = []
        for taxon in assay.get("taxon_terms") or []:
            phrase = taxon.get("label", "")
            if phrase:
                print(f"  [taxon] Looking up: {phrase!r}")
                term = _annotate_term(phrase, "NCBITAXON", "taxon_term", assay_title, api_key, client)
                resolved_taxa.append(term if term else {"label": phrase})
            else:
                resolved_taxa.append(taxon)
        assay["taxon_terms"] = resolved_taxa

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
        if assay.get("objects"):
            for o in assay["objects"]:
                tid = o.get("term_id", "").split("/")[-1]
                onto = o.get("ontology", "")
                suffix = f" ({onto}:{tid})" if tid else ""
                print(f"      object:      {o.get('label')}{suffix}")
        if assay.get("processes"):
            for p in assay["processes"]:
                tid = p.get("term_id", "").split("/")[-1]
                onto = p.get("ontology", "")
                suffix = f" ({onto}:{tid})" if tid else ""
                print(f"      process:     {p.get('label')}{suffix}")
        if assay.get("taxon_terms"):
            for t in assay["taxon_terms"]:
                tid = t.get("term_id", "").split("/")[-1]
                onto = t.get("ontology", "")
                suffix = f" ({onto}:{tid})" if tid else ""
                print(f"      taxon:       {t.get('label')}{suffix}")
        citations = assay.get("citations") or []
        if citations:
            cit_strs = [f"{c.get('authors', '')} ({c.get('year', '')})" for c in citations]
            print(f"      citations:   {'; '.join(cit_strs)}")
    print("=" * 60)

    return assays