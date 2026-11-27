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


def extract_title_concepts(
    title: str,
    vocabulary: list[str],
    known_subjects: list[str] | None = None,
) -> str:
    """Decompose a whole KE title into action, event components, and location.

    One call replaces the separate direction-normalization and per-subject
    decomposition prompts, and additionally proposes a phenotype phrase per
    component and a subcellular location. When `known_subjects` is given (a
    stored annotation exists), the model must reuse those exact subject
    phrases so event-component identity is preserved across re-annotation.
    """
    vocab_str = ", ".join(f'"{w}"' for w in vocabulary)
    known_block = ""
    if known_subjects:
        subjects_str = "\n".join(f"- {s!r}" for s in known_subjects)
        known_block = (
            f"\nThis Key Event was annotated before with these subject phrases. "
            f"Return exactly one event component per phrase, with `subject` copied "
            f"verbatim:\n{subjects_str}\n"
        )
    return (
        f"You are decomposing an AOP-Wiki Key Event title into structured concepts "
        f"for ontology annotation.\n"
        f"KE title: {title!r}\n"
        f"{known_block}\n"
        f"Extract:\n"
        f"- biological_action: the direction or observation the title asserts, as the "
        f"semantically closest term from this controlled vocabulary (or null if none "
        f"fits): {vocab_str}. 'occurrence' covers events observed to happen without a "
        f"directional change (formation of a lesion, presence of an interaction, a "
        f"pathological state).\n"
        f"- event_components: one entry per distinct biological change in the title "
        f"(usually one; more when the title conjoins changes). Each entry has:\n"
        f"  - subject: the title phrase describing the change, without the direction word\n"
        f"  - biological_object: the cell type, tissue, molecule, or anatomical entity "
        f"acted upon\n"
        f"  - biological_process: the activity or process phrase, suited to a GO "
        f"biological_process search\n"
        f"  - phenotype: a phrase suited to a phenotype-ontology search (HP/MP/UPHENO), "
        f"or null when the title describes no phenotype-like concept\n"
        f"- cellular_component: when the title localizes the event subcellularly, the "
        f"organelle NOUN to search with (e.g. 'Mitochondrial fatty acid beta-oxidation' "
        f"→ 'mitochondrion'); null otherwise. Do not treat parts of protein names "
        f"('nuclear receptor', 'membrane receptor') as locations.\n\n"
        f"Prefer words that appear in the title; keep phrases concise.\n"
        f"Reply with ONLY valid JSON:\n"
        f'{{"biological_action": "<term or null>", "cellular_component": "<noun or null>", '
        f'"event_components": [{{"subject": "...", "biological_object": "...", '
        f'"biological_process": "...", "phenotype": "<phrase or null>"}}]}}'
    )


def decompose_subject_phrase(subject: str) -> str:
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
        '- If no citations are mentioned, use an empty list\n'
        '- Keep labels concise and specific\n\n'
        'Each assay object must use "citations" (plural, a list) not "citation".\n'
        'Reply with ONLY valid JSON: {"assays": [<assay objects>]}'
    )


# ---------------------------------------------------------------------------
# KE grouping (collect_similar_events): shared blocks, system prompts,
# and per-pass user-prompt builders
# ---------------------------------------------------------------------------

GROUP_TYPE_DEFINITIONS = """
  "merge"  — events that should be merged because they describe the same biological
             event in the same direction, using different wording, abbreviations, or
             specificity (e.g. "collagen accumulation" and "collagen deposition", or
             "TGF-beta activation" and "TGF-β, Activation").

  "same_object_different_action (soda)" — Same Object, Directionally Opposite: events
             that measure the same biological endpoint but in STRICTLY OPPOSITE
             directions — one increases and the other decreases, or one activates and
             the other inhibits the SAME receptor/protein (e.g. "Increase, Plasma
             vitellogenin" paired with "Reduction, Plasma vitellogenin"; or "Agonism,
             Estrogen receptor" paired with "Antagonism, Estrogen receptor").
             IMPORTANT: "soda" is ONLY for directional opposites of the identical
             endpoint. Do NOT use "soda" for a "binding" event paired with an
             "inhibition" or "activation" event — those belong in
             "same_object_different_process".

  "same_object_different_process" — events that share the same biological target
             or object but involve clearly distinct processes that cannot be assumed
             equivalent without additional context. The most common case is a
             "binding" event paired with an "inhibition", "activation", or
             "degradation" event for the same molecule: binding does not imply a
             functional outcome, so these must NOT be classified as "soda" or "merge".
             Group them here so curators can review whether the functional relationship
             is documented. Example: "Binding of inhibitor, Complex I" and
             "Inhibition, Complex I" share the same object but binding alone does not
             confirm inhibition — use "same_object_different_process", not "soda".
             IMPORTANT: "same object" means the IDENTICAL molecule, receptor, or
             entity — not merely related molecules. An enzyme and its substrate or
             product are DIFFERENT objects (e.g. aromatase ≠ estradiol; AChE ≠
             acetylcholine). Do NOT group events across different biological objects
             even if they are part of the same pathway.

  "similar_event_different_biological_context" — events that describe the same
             process in the same direction, but one specifies a biological context
             (cell type, tissue, organ, compartment) while the other either does not list
             a biological context or the biological context is different. These
             should NOT be merged because the specificity difference is biologically
             meaningful for AOP placement. Group them here for curator review.
             Example: "Inhibition, Aromatase" (general) paired with "reduction in
             ovarian granulosa cells, Aromatase (Cyp19a1)" (cell-specific); or "liver
             fibrosis" paired with "pulmonary fibrosis".
"""

GROUPING_MISTAKES = """
CRITICAL MISTAKES TO AVOID:

1. Do NOT put events with conflicting directions into the same "merge" group.
   Check whether the group members are increases or decreases and only include
   events going the SAME direction. If two events describe the same endpoint in
   opposite directions, they belong in a "soda" group together — not a merge group.
   Two small precise merge groups (one for each direction) is better than one large
   SODA group. Only fall back to a SODA group when no same-direction merge partner
   exists. Do NOT create a SODA group with 4+ members when the existing merge group
   already has 3+ — leave the opposing event ungrouped instead.
   BAD EXAMPLE: Putting "Increase, Fatty acid beta-oxidation" or "Increase, Lipid
   degradation" into a merge group whose other members all describe DECREASED
   fatty acid beta-oxidation.
   BAD EXAMPLE: Putting "Decrease, Triglyceride" into a merge group whose other
   members all describe INCREASED triglyceride formation/accumulation.

2. Do NOT put pathway-adjacent or downstream events into the same "merge" group.
   Merge means synonym-level equivalence only. Events that are upstream causes,
   downstream effects, or co-regulated pathway members of a group's topic are NOT
   synonyms for each other.
   BAD EXAMPLE: Grouping "Activation, SREBF1", "Up Regulation, SCD-1", or
   "Increase, De novo lipogenesis" with "Up Regulation, FAS" (fatty acid synthase)
   — these are different molecules and processes in the same pathway.
   BAD EXAMPLE: Grouping "Activation, TGF-beta pathway" with "Increase, Collagen
   accumulation" — TGF-beta activation is an upstream cause, not a synonym for
   collagen accumulation.

3. If you determine a group or assignment is not biologically justified, OMIT IT
   ENTIRELY. Do not output it with a rationale saying "withdrawing this grouping"
   or "these are different biological events". Simply do not include it.

4. Do NOT combine events that operate at different levels of biological scale or
   specificity using "merge", "soda", or "same_object_different_process".
   A generalized process that can occur across many tissue types is NOT equivalent
   to an organ-specific or tissue-specific form of that process, even if they share
   the same general mechanism.
   In particular, organ-level fibrosis events (liver fibrosis, pulmonary fibrosis,
   cardiac fibrosis, renal fibrosis) must NOT be placed in a "merge" group with each
   other or with cellular/tissue-level events like "Increase, Collagen accumulation"
   — fibrosis at a specific organ is a pathological outcome, while collagen
   accumulation is a cellular/ECM process that may contribute to fibrosis in any
   tissue.
   HOWEVER, multiple organ-specific fibrosis events (e.g. "Increase, Liver fibrosis"
   + "Increase, Pulmonary fibrosis" + "Increase, Cardiac fibrosis") ARE appropriate
   candidates for a "similar_event_different_biological_context" group — they describe
   the same process (fibrosis) in different organ contexts.
   Similarly, "Increase, Liver fibrosis" paired with "Increase, Collagen accumulation"
   may belong in "similar_event_different_biological_context" (organ-level outcome vs.
   cellular process contributing to it), not "merge".
   BAD EXAMPLE: Merging "Increase, Liver fibrosis" with "Increase, Collagen
   accumulation" — liver fibrosis is organ-level pathology; collagen accumulation
   is a cellular process. Use "similar_event_different_biological_context" instead.
   BAD EXAMPLE: Merging "Increase, Liver fibrosis" with "Increase, Pulmonary
   fibrosis" — these are the same process in different organs. Use
   "similar_event_different_biological_context" instead.
"""

GROUPING_RULES = """
Grouping rules:
- Do NOT group events that are merely related (e.g. "inflammation" and
  "macrophage infiltration" should NOT be grouped).
- Each event ID may appear in at most one group.
- Only group or assign an event when the match is clear and biologically
  justified — do not force groupings.
- When in doubt between "merge" and "same_object_different_process", choose
  "same_object_different_process" to flag curator review.
- When one event adds a cell type, tissue, organ, or compartment qualifier that
  the paired event lacks, use "similar_event_different_biological_context" rather
  than "merge".
"""

GROUPING_BATCH_SYSTEM = (
    """You are a biologist reviewing AOP-Wiki Key Event (KE) titles.
Your task: identify groups of events that describe the same underlying biological
object, process, or phenotype and classify each group as one of four types:
"""
    + GROUP_TYPE_DEFINITIONS
    + GROUPING_RULES
    + """
Reply with ONLY a JSON array of group objects. Each object must have:
  "group_key":   a short snake_case identifier for the group
  "type":        "merge", "soda", "same_object_different_process", or "similar_event_different_biological_context"
  "member_ids":  array of string event IDs in this group (minimum 2)
  "rationale":   one sentence explaining why these are grouped

Example:
[
  {
    "group_key": "collagen_accumulation",
    "type": "merge",
    "member_ids": ["ID_A", "ID_B"],
    "rationale": "Both describe increased collagen deposition in tissue."
  },
  {
    "group_key": "vitellogenin_plasma_levels",
    "type": "soda",
    "member_ids": ["ID_C", "ID_D"],
    "rationale": "Both measure plasma vitellogenin but in opposite directions."
  },
  {
    "group_key": "complex_i_binding_vs_inhibition",
    "type": "same_object_different_process",
    "member_ids": ["ID_X", "ID_Y"],
    "rationale": "Both target Complex I but binding does not confirm inhibition without additional context."
  },
  {
    "group_key": "aromatase_inhibition_general_vs_granulosa",
    "type": "similar_event_different_biological_context",
    "member_ids": ["ID_E", "ID_F"],
    "rationale": "Both describe aromatase inhibition but one specifies ovarian granulosa cells while the other is general."
  }
]

If there are no similar pairs in this batch, reply with: []
"""
    + GROUPING_MISTAKES
)

def grouping_batch(batch: list[tuple[str, str]]) -> str:
    lines = "\n".join(f"  ID {ke_id}: {title}" for ke_id, title in batch)
    return f"Review these {len(batch)} AOP-Wiki Key Events and group similar ones:\n\n{lines}"

GROUPING_CONSOLIDATION_SYSTEM = """You are a biologist reviewing groups of AOP-Wiki Key Events
that were identified as similar within separate batches.

Each group has a "type" of "merge", "soda", "same_object_different_process",
or "similar_event_different_biological_context".

Your task: identify groups from different batches that describe the same underlying
biological event and should be merged into one. Only merge groups that share the
same type. For example, a batch-1 group "collagen_accumulation" and a batch-2
group "collagen_deposition" should be merged because they describe the same process.

Rules:
- Only merge groups that clearly refer to the same biological event.
- Do not merge groups that are merely related.
- Do not change the type of any group.
- A group may only appear in one merge instruction.

Reply with ONLY a JSON array of merge instructions. Each instruction identifies
one group to keep and one or more groups to absorb into it:
  {
    "keep":   "<group_key to keep>",
    "absorb": ["<group_key>", ...],
    "rationale": "<one sentence>"
  }

If no cross-batch duplicates exist, reply with: []
Do NOT re-output groups that have no match — only list merges.
""" + GROUPING_MISTAKES

def grouping_consolidation(groups: list[dict]) -> str:
    lines = [f"Review these {len(groups)} groups for cross-batch duplicates to merge:\n"]
    for g in groups:
        lines.append(
            f'  group_key: {g["group_key"]!r}  type: {g.get("type", "merge")!r}\n'
            f'  rationale: {g.get("rationale", "")!r}\n'
        )
    return "\n".join(lines)

GROUPING_PASS3_SYSTEM = (
    """You are a biologist reviewing AOP-Wiki Key Event titles.

You are given:
1. EXISTING GROUPS — groups already identified in earlier processing, each with a
   group_key, type, and the titles of their current members.
2. UNGROUPED EVENTS — events that were not placed in any group during earlier
   processing, each with an ID and title.

Your two tasks:
A. For each ungrouped event, decide if it clearly belongs in one of the existing
   groups. Apply the same type rules:
"""
    + GROUP_TYPE_DEFINITIONS
    + GROUPING_RULES
    + """
B. Among the ungrouped events themselves, identify any NEW groups (pairs or larger
   sets) not captured above. Use the same four types.

Reply with ONLY a JSON object with exactly two keys:

"existing_group_assignments": array of assignment objects:
  {
    "event_id": "<string ID of the ungrouped event>",
    "group_key": "<key of the existing group it belongs in>",
    "rationale": "<one sentence>"
  }

"new_groups": array of new group objects:
  {
    "group_key": "<snake_case identifier>",
    "type": "<merge|soda|same_object_different_process|similar_event_different_biological_context>",
    "member_ids": ["<id>", "<id>", ...],
    "rationale": "<one sentence>"
  }

If there are no assignments or new groups, use empty arrays.
"""
    + GROUPING_MISTAKES
)

def grouping_pass3(
    ungrouped_batch: list[tuple[str, str]],
    existing_groups: list[dict],
    events: dict[str, str],
) -> str:
    lines = ["EXISTING GROUPS:"]
    for g in existing_groups:
        titles = ", ".join(
            f'"{events.get(str(mid), str(mid))}"'
            for mid in g.get("member_ids", [])[:6]  # cap at 6 titles to save tokens
        )
        rationale = g.get("rationale", "")
        lines.append(
            f'  {g["group_key"]} (type={g.get("type","merge")}): {titles}'
        )
        if rationale:
            lines.append(f'    rationale: {rationale}')
    lines.append("")
    lines.append(f"UNGROUPED EVENTS ({len(ungrouped_batch)} total):")
    for ke_id, title in ungrouped_batch:
        lines.append(f"  ID {ke_id}: {title}")
    return "\n".join(lines)
