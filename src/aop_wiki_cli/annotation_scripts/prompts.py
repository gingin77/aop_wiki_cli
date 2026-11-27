"""All LLM prompt templates used by the KE annotation workflow.

Every prompt sent to the Anthropic API lives here as a small template
function, so wording can be reviewed and tuned in one place without touching
the control flow that calls it.
"""


def normalize_biological_action(direction: str, vocabulary: list[str]) -> str:
    """Map a free-text direction phrase onto the AOP-Wiki controlled vocabulary."""
    vocab_str = ", ".join(f'"{w}"' for w in vocabulary)
    return (
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


def decompose_subject(subject: str) -> str:
    """Split a KE subject phrase into biological_object and biological_process."""
    return (
        f"You are parsing an AOP-Wiki Key Event subject phrase into ECS components.\n"
        f"Subject phrase: {subject!r}\n\n"
        f"Identify:\n"
        f"- biological_object: the cell type, tissue, molecule, or anatomical entity\n"
        f"- biological_process: the activity or process (use the full subject phrase as-is)\n\n"
        f"Reply with ONLY valid JSON: "
        f'{{\"biological_object\": \"<phrase>\", \"biological_process\": \"<phrase>\"}}\n'
        f"Use only words that appear in the subject phrase."
    )


def classify_biological_organization(description: str, levels: list[str]) -> str:
    """Pick the level of biological organization from a KE description excerpt."""
    levels_str = ", ".join(levels)
    return (
        f"You are classifying an AOP-Wiki Key Event by level of biological organization.\n"
        f"KE description (excerpt):\n{(description or '')[:500]!r}\n\n"
        f"Choose the single best level from: {levels_str}\n"
        f'Reply with ONLY valid JSON: {{"level": "<level>", "reason": "<one sentence>"}}'
    )


def review_curator_comments(title: str, comments: list[str]) -> str:
    """Summarize prior curator comments into guidance for re-annotation."""
    comments_block = "\n".join(f"- {c}" for c in comments)
    return (
        f"You are reviewing curator comments on an AOP-Wiki Key Event annotation.\n"
        f"KE title: {title!r}\n\n"
        f"Prior curator comments:\n{comments_block}\n\n"
        f"Summarise in 2-3 sentences what these comments tell you about how the "
        f"annotation should be improved. Focus on actionable guidance for selecting "
        f"better ontology terms."
    )


# Per-component selection rules injected into the term-ranking prompt.
COMPONENT_GUIDANCE = {
    "cell_term": (
        "Cell terms must be actual cell types from the Cell Ontology (CL). "
        "Reject any term that is a biological process, molecular function, or anatomical structure — "
        "even if it appears in the candidate list. If no candidate is a genuine cell type, return null."
    ),
    "organ_term": (
        "Organ terms must be anatomical structures or tissues from UBERON. "
        "Reject any term that is a biological process or molecular function."
    ),
    "cellular_component": (
        "Cellular component terms must be subcellular structures or organelles from the "
        "GO cellular_component branch (e.g. mitochondrion, endoplasmic reticulum, nucleus, "
        "lipid droplet). GO process and molecular-function terms often appear in the "
        "candidate list — reject them. If no candidate is a genuine cellular component, "
        "return null."
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


def rank_term(
    ke_title: str,
    component: str,
    candidates: list,
    context: dict | None = None,
) -> str:
    """Choose the best ontology term for a component from a candidate list."""
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

    guidance = COMPONENT_GUIDANCE.get(component, "")
    guidance_str = f"\nComponent guidance: {guidance}\n" if guidance else ""

    return (
        f"You are annotating an AOP-Wiki Key Event (KE) with ontology terms.\n"
        f"KE title: {ke_title!r}\n"
        f"ECS component to annotate: {component}\n"
        f"{guidance_str}"
        f"{context_str}\n"
        f"Candidate ontology terms (choose the single best match):\n{candidate_block}\n\n"
        f"Reply with ONLY a JSON object: {{\"index\": <1-based integer>, \"reason\": \"<one sentence>\"}}\n"
        f"If none are a good match, use {{\"index\": null, \"reason\": \"...\"}}"
    )


def extract_assays(measurement_text: str) -> str:
    """Extract structured assay objects from a KE "How is it measured" field."""
    return (
        "You are extracting structured assay information from text in an AOP-Wiki Key Event field,"
        '"How is it measured or detected".\n\n'
        f"Text:\n{measurement_text}\n\n"
        "Purpose:\n"
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
