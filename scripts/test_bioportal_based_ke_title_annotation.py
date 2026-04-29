"""
Exploratory script: suggest ECS (biological action, process, object) ontology terms
for a KE title using the BioPortal Annotator API.

Approach:
  - KE titles follow the pattern: "<Direction>, <process or object phrase>"
  - Parse out the direction/action token and the subject phrase from the title
  - Query BioPortal separately for each ECS component against the relevant ontologies:
      biological_action  → GO (MF/BP verbs), small curated action list
      biological_process → GO biological process
      biological_object  → CL (cell types), UBERON (anatomy), ChEBI (chemicals), GO MF

Usage:
    uv run python scripts/test_bioportal_ke1499.py
    (requires BIOPORTAL_API_KEY in .env or environment)
"""

import json
import os
import re
import urllib.parse
import urllib.request

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

# KE IDs to annotate in this session.
KE_IDS = ["1499", "1498", "1500"]
# KE_IDS = ["1498"]
CACHE_FILE = "outputs/cache/04-28-2026/all_events_04-28-2026.json"
OUTPUT_DIR = "outputs/ke_ontology_suggestions"
# Pre-curated annotations used as a reference; any non-null property here
# is used directly and skips BioPortal / Anthropic queries.
REFERENCE_FILE = "outputs_for_vc/ke_suggestions_04-28-2026.json"
BIOPORTAL_URL = "https://data.bioontology.org/annotator"

# AOP-Wiki controlled vocabulary for the direction/change prefix in KE titles.
# biological_action is detected directly from the title — no BioPortal lookup needed.
WIKI_ACTION_WORDS = [
    "increased",
    "decreased",
    "functional change",
    "abnormal",
    "pathological",
    "occurrence",
    "disrupted",
    "morphological change",
    "arrested",
    "delayed",
    "premature"
]

ALTERATIVE_ACTION_WORDS = {
    "loss": "decreased",
    "gain": "increased",
    "impairment": "abnormal",
    "impaired": "abnormal",
    "inhibition": "decreased",
    "activation": "increased",
    "accumulation": "increased",
    "reduction": "decreased",
    "suppression": "decreased",
    "overactivation": "increased",
    "downregulation": "decreased",
    "upregulation": "increased",
    "formation": "occurrence",
    "hyperplasia": "increased",
    "changes": "functional change"
}

# Ontologies queried via BioPortal, per ECS component.
# biological_action is resolved locally from WIKI_ACTION_WORDS, not via BioPortal.
ECS_ONTOLOGIES = {
    "biological_object": "CL,UBERON,CHEBI",
    "biological_process": "GO",
}

# AOP-Wiki controlled vocabulary for level of biological organization.
BIOLOGICAL_ORGANIZATION_LEVELS = [
    "Molecular",
    "Cellular",
    "Tissue",
    "Organ",
    "Individual",
    "Population",
]

# Levels that trigger a cell term annotation.
_CELL_TERM_LEVELS = {"Molecular", "Cellular"}
# Levels that trigger an organ term annotation.
_ORGAN_TERM_LEVELS = {"Cellular", "Tissue", "Organ"}

# Ontologies for cell and organ term annotations — to be set once confirmed.
CELL_TERM_ONTOLOGIES = "CL"
ORGAN_TERM_ONTOLOGIES = "UBERON"
PHENOTYPE_ONTOLOGIES = "UPHENO"


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


def _detect_biological_action(direction: str) -> str | None:
    """
    Match the direction prefix of a KE title against the AOP-Wiki controlled
    vocabulary (WIKI_ACTION_WORDS).  If no controlled-vocab term matches,
    checks ALTERATIVE_ACTION_WORDS and returns the mapped canonical term.
    Returns None if nothing matches — only WIKI_ACTION_WORDS terms are eligible.
    """
    for word in sorted(WIKI_ACTION_WORDS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(word)}\b', direction, re.IGNORECASE):
            return word
    for alt, canonical in sorted(ALTERATIVE_ACTION_WORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf'\b{re.escape(alt)}\b', direction, re.IGNORECASE):
            return canonical
    return None


# Prepositions that link a process verb to its object in KE subject phrases.
# Ordered by expected frequency to short-circuit early.
_OBJECT_PREPOSITIONS = ["of", "in", "by", "on", "to", "from"]

# Suffixes that mark the last word of a compound noun phrase as a nominalized
# process verb — e.g. "fibroblast proliferation" → object="fibroblast".
_PROCESS_NOUN_SUFFIXES = (
    "ation", "tion", "sis", "ment", "ing", "ance", "ence", "al"
)


def _split_subject_on_preposition(subject: str) -> tuple[str, str] | None:
    """
    Split a subject phrase on the first structural preposition.

    Returns (process_phrase, object_phrase), or None when no preposition is
    found (subject is a plain noun phrase with no embedded verb).

    Examples
    --------
    "activation of T helper type 2 cells"  → ("activation", "T helper type 2 cells")
    "thyroid hormone binding to receptor"  → ("thyroid hormone binding", "receptor")
    "Adipose lipolysis"                    → None
    """
    for prep in _OBJECT_PREPOSITIONS:
        pattern = rf'\b{prep}\b\s+'
        match = re.search(pattern, subject, re.IGNORECASE)
        if match:
            process_phrase = subject[:match.start()].strip()
            object_phrase = subject[match.end():].strip()
            # Reject the split if either side is empty
            if process_phrase and object_phrase:
                return process_phrase, object_phrase
    return None


def _split_noun_compound(subject: str) -> str | None:
    """
    For compound noun phrases with no preposition, extract the object by
    stripping a trailing nominalized-process word.

    Returns the object phrase when the last word looks like a process
    nominalization, or None when the last word is a plain noun.

    Examples
    --------
    "fibroblast proliferation"       → "fibroblast"
    "myofibroblast differentiation"  → "myofibroblast"
    "T helper type 2 cells"          → None  (no process suffix)
    """
    words = subject.split()
    if len(words) < 2:
        return None
    last = words[-1].lower()
    if any(last.endswith(suffix) for suffix in _PROCESS_NOUN_SUFFIXES):
        return " ".join(words[:-1])
    return None


def _extract_biological_object(subject: str) -> str:
    """
    Extract the biological object phrase from a KE title subject.

    Strategy (in order):
    1. Split on structural preposition → noun phrase after it
       e.g. "activation of T helper type 2 cells" → "T helper type 2 cells"
    2. Trailing process nominalization → words before it
       e.g. "fibroblast proliferation" → "fibroblast"
    3. Fallback → entire subject
       e.g. "T helper type 2 cells"
    """
    split = _split_subject_on_preposition(subject)
    if split:
        return split[1]
    compound = _split_noun_compound(subject)
    if compound:
        return compound
    return subject


def _extract_biological_process(subject: str) -> str:
    """
    Return the full subject phrase as the biological process search candidate.

    The full subject (e.g. "activation of T helper type 2 cells") gives BioPortal
    the most context for a GO search.  A post-hoc refinement step in main() then
    strips the resolved object label from this phrase before querying, narrowing
    the search to the process verb alone (e.g. "activation").
    """
    return subject


def _split_conjoined_subjects(subject: str) -> list[str]:
    """
    Split a subject phrase on top-level ' and ' conjunctions into independent
    sub-subjects.  Returns a list with the original subject when no conjunction
    is found, or when either side would be a single bare word (a fragment rather
    than a complete noun phrase).

    Examples
    --------
    "fibroblast proliferation and myofibroblast differentiation"
        → ["fibroblast proliferation", "myofibroblast differentiation"]
    "activation of T helper type 2 cells"
        → ["activation of T helper type 2 cells"]
    """
    parts = re.split(r'\s+and\s+', subject, flags=re.IGNORECASE)
    stripped = [p.strip() for p in parts if p.strip()]
    # Only split when every part is a multi-word phrase (not a bare fragment)
    if len(stripped) > 1 and all(len(p.split()) > 1 for p in stripped):
        return stripped
    return [subject]


def parse_ke_title(title: str) -> dict:
    """
    Parse a KE title into candidate ECS component phrases.

    KE titles commonly follow: "<Direction/Change>, <subject phrase>"
    e.g. "Increased, activation of T helper type 2 cells"
         "Decreased, interleukin-4 production"

    Returns dict with keys:
        raw_direction      – text before the first comma
        biological_action  – matched AOP-Wiki controlled-vocab term
        biological_process – full subject phrase (for GO search)
        biological_object  – noun phrase after "of" (for CL/UBERON/ChEBI search)
        full_subject       – full subject phrase (unmodified)
    """
    # Strip short parenthetical expansions like "(T)" or "(h)"
    cleaned = re.sub(r'\s*\([^)]{1,4}\)', '', title).strip()

    parts = cleaned.split(',', 1)
    direction = parts[0].strip()
    subject = parts[1].strip() if len(parts) > 1 else cleaned

    # For titles without a comma the whole string is the subject.
    # Still try to detect an action word from the start of the title so that
    # e.g. "Loss of alveolar capillary membrane integrity" yields action="loss"
    # rather than falling back to the full title string.
    if len(parts) == 1:
        detected = _detect_biological_action(cleaned)
        if detected is not None:
            direction = detected

    subjects = _split_conjoined_subjects(subject)

    return {
        "raw_direction": direction,
        "biological_action": _detect_biological_action(direction),
        "subjects": subjects,
        "full_subject": subject,
    }


BIOPORTAL_SEARCH_URL = "https://data.bioontology.org/search"

# Common words that add noise when querying ontologies
STOPWORDS = {"type", "the", "a", "an", "of", "in", "and", "or", "with", "by"}


def normalize_phrase(phrase: str) -> str:
    """Remove stopwords and normalize whitespace."""
    tokens = [t for t in phrase.split() if t.lower() not in STOPWORDS]
    return " ".join(tokens)


def search_bioportal(phrase: str, ontologies: str, api_key: str) -> list:
    """
    Use BioPortal search API to find ontology terms matching a phrase.
    Searches against labels and synonyms — better than the Annotator for
    ECS component lookup where the phrase may not match a label exactly.

    Returns list of result dicts with keys: ontology, term_id, label, synonyms.
    """
    params = urllib.parse.urlencode({
        "q": phrase,
        "ontologies": ontologies,
        "require_exact_match": "false",
        "include": "prefLabel,synonym",
        "pagesize": 10,
        "apikey": api_key,
    })
    req = urllib.request.Request(
        f"{BIOPORTAL_SEARCH_URL}?{params}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    results = []
    for item in data.get("collection", []):
        onto_url = item.get("links", {}).get("ontology", "")
        results.append({
            "ontology": onto_url.split("/")[-1] if onto_url else "",
            "term_id": item.get("@id", ""),
            "label": item.get("prefLabel", ""),
            "synonyms": item.get("synonym", []),
        })
    return results


def search_with_fallback(phrase: str, ontologies: str, api_key: str) -> tuple[list, str]:
    """
    Search BioPortal with progressive fallback when no results are returned.

    Strategy:
      1. Full phrase
      2. Normalized phrase (stopwords removed)
      3. Noun phrase after 'of' (normalized)

    Returns (results, query_used).
    """
    # 1. Full phrase
    results = search_bioportal(phrase, ontologies, api_key)
    if results:
        return results, phrase

    # 2. Normalized phrase
    normalized = normalize_phrase(phrase)
    if normalized != phrase:
        results = search_bioportal(normalized, ontologies, api_key)
        if results:
            return results, f"{normalized!r} (stopwords removed)"

    # 3. Noun after 'of', normalized
    of_match = re.search(r'\bof\s+(.+)$', phrase, re.IGNORECASE)
    if of_match:
        noun_phrase = normalize_phrase(of_match.group(1).strip())
        results = search_bioportal(noun_phrase, ontologies, api_key)
        if results:
            return results, f"{noun_phrase!r} (noun phrase fallback)"

    return [], phrase


def partition_process_results(
    results: list, object_label: str
) -> tuple[list, list]:
    """
    Split process results into (kept, filtered_out) based on the selected object label.

    Keeps a result if:
      - Its label contains NONE of the object's content words  (pure process term), OR
      - Its label contains the FULL object label               (correct-object-specific term)

    Filters out results whose labels contain some object content words but not the
    full label — these are terms specific to a *different* variant of the object
    (e.g. "T-helper 1 cell activation" when the object is "T-helper 2 cell").
    """
    object_words = [
        w for w in object_label.lower().split() if w not in STOPWORDS
    ]
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


def check_anthropic_available() -> tuple[bool, str]:
    """
    Return (True, "") if Anthropic API key is set and the endpoint is reachable.
    Return (False, reason) otherwise — caller should fall back to manual review.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return False, "ANTHROPIC_API_KEY not set in environment"
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com",
            headers={"x-api-key": api_key},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        # Any network error (including 4xx/5xx) still means the host is reachable;
        # only a full connection failure means no connectivity.
        import socket
        try:
            socket.setdefaulttimeout(5)
            socket.getaddrinfo("api.anthropic.com", 443)
        except OSError:
            return False, "Cannot reach api.anthropic.com (no network?)"
    return True, ""


def display_candidates(candidates: list, component: str, query_used: str) -> None:
    """Print a numbered list of candidate ontology terms in a consistent format."""
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
    context: dict | None = None,
) -> tuple[dict | None, str, str]:
    """
    Select the best candidate term using the LLM if available, otherwise
    prompting the user to choose manually.

    Returns (selected_result_dict | None, source, reason).
    """
    anthropic_ok, anthropic_reason = check_anthropic_available()

    if anthropic_ok:
        idx, reason = llm_rank_term(ke_title, component, candidates, context)
        source = "llm_recommendation"
    else:
        print(f"  (Anthropic unavailable: {anthropic_reason} — manual selection)")
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
            idx = None
            reason = "skipped"
            source = "manual_selection"

    if idx is not None:
        return candidates[idx], source, reason
    return None, source, reason


def _refine_process_phrase(phrase: str, object_label: str) -> str:
    """Strip the resolved object label from a process phrase before querying GO.

    For noun-compound subjects (e.g. "fibroblast proliferation" with object
    "fibroblast"), the object is a prefix of the phrase and the full phrase is
    itself a meaningful GO search term — keep it unchanged.
    For preposition-split subjects (e.g. "activation of T helper type 2 cells"
    with object "T helper type 2 cells"), strip the object to leave the process
    verb alone (e.g. "activation").
    """
    if phrase.lower().startswith(object_label.lower()):
        return phrase
    refined = re.sub(re.escape(object_label), "", phrase, flags=re.IGNORECASE).strip()
    refined = re.sub(r'\s+', ' ', refined).strip(" ,of")
    return refined if refined else phrase


def write_results(all_annotations: dict, output_dir: str) -> str:
    """
    Write all KE annotations to a single dated JSON file.
    Returns the path written.
    """
    import datetime
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.date.today().strftime("%m-%d-%Y")
    filename = f"ke_suggestions_{date_str}.json"
    path = os.path.join(output_dir, filename)
    with open(path, "w") as f:
        json.dump(all_annotations, f, indent=2)
    return path


def llm_rank_term(
    ke_title: str,
    component: str,
    candidates: list,
    context: dict | None = None,
) -> tuple[int | None, str]:
    """
    Ask Claude to pick the best ontology term from a candidate list.

    Parameters
    ----------
    ke_title   : full KE title string
    component  : ECS component name (e.g. 'biological_process')
    candidates : list of result dicts with 'label' and 'synonyms' keys
    context    : optional extra context (e.g. {'selected_object': 'T-helper 2 cell'})

    Returns
    -------
    (0-based index of best candidate, justification string)
    Returns (None, reason) when no confident match can be made.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

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
        model="claude-sonnet-4-5",
        max_tokens=128,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    # Extract JSON even if wrapped in a code fence
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        return None, f"Could not parse LLM response: {raw!r}"
    parsed_resp = json.loads(json_match.group())
    idx_1based = parsed_resp.get("index")
    reason = parsed_resp.get("reason", "")
    if idx_1based is None:
        return None, reason
    return int(idx_1based) - 1, reason  # convert to 0-based


def llm_normalize_biological_action(direction: str) -> str | None:
    """
    Ask Claude to map a direction phrase to the nearest WIKI_ACTION_WORDS term.
    Returns the matched canonical term, or None if no confident match exists.
    """
    anthropic_ok, _ = check_anthropic_available()
    if not anthropic_ok:
        return None
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
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
    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return None
        parsed = json.loads(json_match.group())
        term = parsed.get("term")
        reason = parsed.get("reason", "")
        if term and term in WIKI_ACTION_WORDS:
            print(f"  (LLM normalized {direction!r} → {term!r}: {reason})")
            return term
    except Exception:
        pass
    return None


def llm_decompose_subject(subject: str) -> tuple[str, str] | None:
    """
    Ask Claude to split a KE subject phrase into (biological_object, biological_process).

    Returns (object_phrase, process_phrase) using words from the subject, or None
    when the LLM is unavailable or cannot confidently decompose the phrase.

    Examples
    --------
    "fibroblast proliferation"       → ("fibroblast", "fibroblast proliferation")
    "activation of T-helper 2 cells" → ("T-helper 2 cells", "activation")
    """
    anthropic_ok, _ = check_anthropic_available()
    if not anthropic_ok:
        return None
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
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
    try:
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return None
        parsed = json.loads(json_match.group())
        obj = parsed.get("biological_object", "").strip()
        proc = parsed.get("biological_process", "").strip()
        if obj and proc:
            return obj, proc
    except Exception:
        pass
    return None


def detect_biological_organization(description: str) -> str | None:
    """
    Determine the level of biological organization for a KE from its description.
    Returns one of BIOLOGICAL_ORGANIZATION_LEVELS, or None if undetermined.
    Uses LLM if available; otherwise prompts the user interactively.
    """
    anthropic_ok, _ = check_anthropic_available()
    if anthropic_ok:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        levels_str = ", ".join(BIOLOGICAL_ORGANIZATION_LEVELS)
        prompt = (
            f"You are classifying an AOP-Wiki Key Event by level of biological organization.\n"
            f"KE description (excerpt):\n{description[:500]!r}\n\n"
            f"Choose the single best level from: {levels_str}\n"
            f'Reply with ONLY valid JSON: {{"level": "<level>", "reason": "<one sentence>"}}'
        )
        try:
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=64,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                level = parsed.get("level", "").strip()
                reason = parsed.get("reason", "")
                if level in BIOLOGICAL_ORGANIZATION_LEVELS:
                    print(f"  (LLM: {level!r} — {reason})")
                    return level
        except Exception:
            pass
        print("  (LLM organization detection failed — falling back to manual)")

    # Manual fallback
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


def _annotate_term(
    phrase: str,
    ontologies: str,
    component: str,
    title: str,
    api_key: str,
) -> dict | None:
    """
    Search BioPortal and interactively select an ontology term for a KE-level component.
    Used for cell_term and organ_term annotations.
    Returns an annotation dict, or None if no selection is made.
    """
    if not ontologies:
        print(f"  No ontologies configured for {component} — skipping.")
        return None
    print(f"  Query phrase: {phrase!r}")
    print(f"  Ontologies:   {ontologies}")
    results, query_used = search_with_fallback(phrase, ontologies, api_key)
    if not results:
        print("  No matches found after fallback — manual curation needed.")
        return None
    # Filter to only results from the requested ontologies (BioPortal can return
    # cross-ontology hits, e.g. GO terms when querying CL or UBERON).
    allowed = {o.strip().upper() for o in ontologies.split(",")}
    filtered = [r for r in results if r.get("ontology", "").upper() in allowed]
    if not filtered:
        print(f"  All results were from off-target ontologies — manual curation needed.")
        return None
    if len(filtered) < len(results):
        print(f"  Filtered out {len(results) - len(filtered)} off-target ontology result(s).")
    results = filtered
    display_candidates(results[:5], component, query_used)
    result, source, reason = rank_term(title, component, results[:5])
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
    else:
        print(f"  → No selection made ({reason})")
        return None


def _annotate_subject(subject: str, title: str, api_key: str, ref: dict | None = None) -> dict:
    """
    Run biological_object and biological_process annotation for one subject phrase.
    Returns dict with keys: subject, biological_object, biological_process.
    When `ref` is supplied, any non-null property in it is used directly and the
    corresponding BioPortal / Anthropic query is skipped.
    """
    subj_annotation: dict = {
        "subject": subject,
        "biological_object": None,
        "biological_process": None,
        "phenotype": None,
    }

    # Attempt LLM decomposition first; fall back to heuristics.
    decomposed = llm_decompose_subject(subject)
    if decomposed:
        object_phrase, process_phrase_raw = decomposed
        print(f"  (LLM decomposition: object={object_phrase!r}, process={process_phrase_raw!r})")
    else:
        object_phrase = _extract_biological_object(subject)
        process_phrase_raw = _extract_biological_process(subject)

    # --- biological_object ---
    print("--- biological_object ---")
    ref_object = (ref or {}).get("biological_object")
    if ref_object is not None:
        print(f"  (reference) {ref_object.get('label', ref_object)!r} — skipping query")
        subj_annotation["biological_object"] = ref_object
        selected_object_label = ref_object.get("label")
    else:
        print(f"  Query phrase: {object_phrase!r}")
        print(f"  Ontologies:   {ECS_ONTOLOGIES['biological_object']}")
        object_results, object_used = search_with_fallback(
            object_phrase, ECS_ONTOLOGIES["biological_object"], api_key
        )

        selected_object_label = None
        if object_results:
            display_candidates(object_results[:5], "biological_object", object_used)
            result, source, reason = rank_term(title, "biological_object", object_results[:5])
            if result:
                selected_object_label = result["label"]
                print(f"  → [{result['ontology']}] {result['label']}")
                print(f"     IRI:    {result['term_id']}")
                print(f"     reason: {reason}")
                subj_annotation["biological_object"] = {
                    "term_id": result["term_id"],
                    "label": result["label"],
                    "ontology": result["ontology"],
                    "reason": reason,
                    "source": source,
                }
            elif source == "manual_comment":
                print(f"  → Comment recorded: {reason!r}")
                subj_annotation["biological_object"] = {"comment": reason, "source": source}
            else:
                print(f"  → No selection made ({reason})")
        else:
            print("  No matches found after fallback — manual curation needed.")
    print()

    # --- biological_process ---
    print("--- biological_process ---")
    ref_process = (ref or {}).get("biological_process")
    if ref_process is not None:
        print(f"  (reference) {ref_process.get('label', ref_process)!r} — skipping query")
        subj_annotation["biological_process"] = ref_process
    else:
        process_phrase = process_phrase_raw
        print(f"  Query phrase: {process_phrase!r}")
        print(f"  Ontologies:   {ECS_ONTOLOGIES['biological_process']}")
        process_results, process_used = search_with_fallback(
            process_phrase, ECS_ONTOLOGIES["biological_process"], api_key
        )

        if process_results:
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

            if kept:
                display_candidates(kept[:5], "biological_process", process_used)
                context = {"selected_object": selected_object_label} if selected_object_label else None
                result, source, reason = rank_term(title, "biological_process", kept[:5], context)
                if result:
                    print(f"  → [{result['ontology']}] {result['label']}")
                    print(f"     IRI:    {result['term_id']}")
                    print(f"     reason: {reason}")
                    subj_annotation["biological_process"] = {
                        "term_id": result["term_id"],
                        "label": result["label"],
                        "ontology": result["ontology"],
                        "reason": reason,
                        "source": source,
                    }
                elif source == "manual_comment":
                    print(f"  → Comment recorded: {reason!r}")
                    subj_annotation["biological_process"] = {"comment": reason, "source": source}
                else:
                    print(f"  → No selection made ({reason})")
            else:
                print("  No results remain after filtering — manual curation needed.")
        else:
            print("  No matches found after fallback — manual curation needed.")
    print()

    # --- phenotype ---
    print("--- phenotype ---")
    ref_phenotype = (ref or {}).get("phenotype")
    if ref_phenotype is not None:
        print(f"  (reference) {ref_phenotype.get('label', ref_phenotype)!r} — skipping query")
        subj_annotation["phenotype"] = ref_phenotype
    else:
        print(f"  Query phrase: {subject!r}")
        print(f"  Ontologies:   {PHENOTYPE_ONTOLOGIES}")
        phenotype_results, phenotype_used = search_with_fallback(
            subject, PHENOTYPE_ONTOLOGIES, api_key
        )
        if phenotype_results:
            display_candidates(phenotype_results[:5], "phenotype", phenotype_used)
            result, source, reason = rank_term(title, "phenotype", phenotype_results[:5])
            if result:
                print(f"  → [{result['ontology']}] {result['label']}")
                print(f"     IRI:    {result['term_id']}")
                print(f"     reason: {reason}")
                subj_annotation["phenotype"] = {
                    "term_id": result["term_id"],
                    "label": result["label"],
                    "ontology": result["ontology"],
                    "reason": reason,
                    "source": source,
                }
            elif source == "manual_comment":
                print(f"  → Comment recorded: {reason!r}")
                subj_annotation["phenotype"] = {"comment": reason, "source": source}
            else:
                print(f"  → No selection made ({reason})")
        else:
            print("  No matches found after fallback — manual curation needed.")
    print()

    return subj_annotation


def annotate_ke(ke_id: str, title: str, api_key: str, description: str = "", ref_ke: dict | None = None) -> dict:
    """
    Run the full ECS annotation workflow for a single KE.
    Returns the annotation dict. For KEs with conjoined subjects (e.g.
    "fibroblast proliferation and myofibroblast differentiation"), each
    subject gets its own entry in ecs_annotations.
    """
    print(f"KE {ke_id}: {title}\n")

    # --- review prior comments before annotating ---
    ref_comments = _flat_ref_comments((ref_ke or {}).get("comments"))
    if ref_comments:
        print("--- prior comments ---")
        for c in ref_comments:
            print(f"  • {c}")
        print()
        anthropic_ok, _ = check_anthropic_available()
        if anthropic_ok:
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
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
                    model="claude-sonnet-4-5",
                    max_tokens=256,
                    messages=[{"role": "user", "content": prompt}],
                )
                print(f"  LLM review: {message.content[0].text.strip()}\n")
            except Exception as e:
                print(f"  (LLM comment review failed: {e})\n")

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
        "ecs_annotations": [],
    }

    # --- biological_action: resolved locally, no API call ---
    print("--- biological_action ---")
    if parsed["biological_action"] is not None:
        print(f"  Detected (controlled vocab): {parsed['biological_action']!r}\n")
        biological_action = {
            "term": parsed["biological_action"],
            "source": "controlled_vocab",
        }
    else:
        llm_action = llm_normalize_biological_action(parsed["raw_direction"])
        if llm_action:
            print(f"  LLM normalized to: {llm_action!r}\n")
            biological_action = {
                "term": llm_action,
                "source": "llm_normalization",
            }
        else:
            print(f"  No match for {parsed['raw_direction']!r} — biological_action set to null\n")
            biological_action = {
                "term": None,
                "source": "unmatched",
            }

    # --- biological_organization ---
    print("--- biological_organization ---")
    ref_org = (ref_ke or {}).get("biological_organization")
    if ref_org is not None:
        print(f"  (reference) {ref_org!r} — skipping detection")
        org_level = ref_org
    else:
        org_level = detect_biological_organization(description)
    annotation["biological_organization"] = org_level
    print()

    # --- cell_term (Molecular or Cellular) ---
    ref_cell = (ref_ke or {}).get("cell_term")
    if ref_cell is not None:
        print("--- cell_term ---")
        print(f"  (reference) {ref_cell.get('label', ref_cell)!r} — skipping query")
        annotation["cell_term"] = ref_cell
        print()
    elif org_level in _CELL_TERM_LEVELS:
        print("--- cell_term ---")
        annotation["cell_term"] = _annotate_term(
            parsed["full_subject"], CELL_TERM_ONTOLOGIES, "cell_term", description, api_key
        )
        print()

    # --- organ_term (Cellular, Tissue, or Organ) ---
    ref_organ = (ref_ke or {}).get("organ_term")
    if ref_organ is not None:
        print("--- organ_term ---")
        print(f"  (reference) {ref_organ.get('label', ref_organ)!r} — skipping query")
        annotation["organ_term"] = ref_organ
        print()
    elif org_level in _ORGAN_TERM_LEVELS:
        print("--- organ_term ---")
        annotation["organ_term"] = _annotate_term(
            parsed["full_subject"], ORGAN_TERM_ONTOLOGIES, "organ_term", description, api_key
        )
        print()

    # Build a lookup from subject string → reference subject annotation.
    ref_subjects: dict[str, dict] = {}
    for ref_subj in (ref_ke or {}).get("ecs_annotations", []):
        if isinstance(ref_subj, dict) and "subject" in ref_subj:
            ref_subjects[ref_subj["subject"]] = ref_subj

    # --- per-subject object + process annotation ---
    subjects = parsed["subjects"]
    for i, subject in enumerate(subjects):
        if len(subjects) > 1:
            print(f"\n[Subject {i + 1}/{len(subjects)}: {subject!r}]")
        ref_subj = ref_subjects.get(subject)
        subj_annotation = _annotate_subject(subject, title, api_key, ref=ref_subj)
        subj_annotation["biological_action"] = biological_action
        annotation["ecs_annotations"].append(subj_annotation)

    return annotation


def main():
    api_key = os.environ.get("BIOPORTAL_API_KEY")
    if not api_key:
        raise EnvironmentError("BIOPORTAL_API_KEY not set — add it to .env")

    with open(CACHE_FILE) as f:
        events = json.load(f)

    # Load pre-curated reference annotations (skip queries where already assigned).
    reference: dict = {}
    if os.path.exists(REFERENCE_FILE):
        with open(REFERENCE_FILE) as f:
            reference = json.load(f)
        print(f"Loaded reference from {REFERENCE_FILE} ({len(reference)} KEs)\n")
    else:
        print(f"Reference file not found ({REFERENCE_FILE}) — all properties will be queried.\n")

    all_annotations: dict = {}

    for i, ke_id in enumerate(KE_IDS):
        if ke_id not in events:
            print(f"KE {ke_id} not found in cache — skipping.\n")
            continue

        title = events[ke_id].get("title", "")
        description = events[ke_id].get("description", "")
        ref_ke = reference.get(ke_id)
        annotation = annotate_ke(ke_id, title, api_key, description=description, ref_ke=ref_ke)

        # --- carry over reference comments ---
        ref_comments = _flat_ref_comments((ref_ke or {}).get("comments"))
        carried = [f"{c} [carried from reference]" for c in ref_comments]
        annotation["comments"] = { "carried": carried, "new": [] }  # new session comments appended below

        # --- record which top-level fields are newly annotated this run ---
        ref_top_keys = {k for k, v in (ref_ke or {}).items() if v is not None}
        new_fields: list[str] = []
        for key, val in annotation.items():
            if key in ("ke_id", "title", "comments", "ecs_annotations"):
                continue
            if val is not None and key not in ref_top_keys:
                new_fields.append(key)
        # Check ecs_annotations for newly annotated per-subject fields
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
            print(f"  Newly annotated fields: {new_fields}")

        all_annotations[ke_id] = annotation

        # --- post-KE comment prompt ---
        print("\n--- KE review ---")
        print("  Add comments to this KE annotation? (Enter to skip, or type comment, q=quit)")
        ke_comments: list[str] = []
        while True:
            line = input("  Comment (blank to finish): ").strip()
            if line.lower() == "q":
                print("Quitting.")
                out_path = write_results(all_annotations, OUTPUT_DIR)
                print(f"Results written to {out_path}")
                raise SystemExit(0)
            if not line:
                break
            ke_comments.append(line)
        if ke_comments:
            annotation["comments"]["new"] = ke_comments
            print(f"  {len(ke_comments)} comment(s) recorded.")

        if i < len(KE_IDS) - 1:
            cont = input("\nContinue to next KE? [Y/n]: ").strip().lower()
            if cont == "n":
                print("Stopping.")
                break
            print()

    out_path = write_results(all_annotations, OUTPUT_DIR)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
