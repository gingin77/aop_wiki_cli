"""
Annotate Key Events for a given AOP using BioPortal + Claude.

Storage model:
  - ke_annotations.json       — shared store, one entry per KE (single source of truth)
  - aop_based_ke_store.json   — AOP index, maps AOP ID → list of KE IDs

KEs already in the shared store are skipped during annotation (use --force to re-annotate).

Usage:
    # List KEs for an AOP with annotation status
    uv run python scripts/annotate_ke_ontology.py --aop 173 --date 04-28-2026

    # Annotate a single KE
    uv run python scripts/annotate_ke_ontology.py --aop 173 --ke-id 68 --date 04-28-2026

    # Re-annotate a KE already in the shared store
    uv run python scripts/annotate_ke_ontology.py --aop 173 --ke-id 68 --force --date 04-28-2026

    # Add a comment to a KE
    uv run python scripts/annotate_ke_ontology.py --aop 173 --ke-id 68 --add-comment "Needs review"
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LLM_MODEL = "claude-sonnet-4-6"

BIOPORTAL_SEARCH_URL = "https://data.bioontology.org/search"
STOPWORDS = {"type", "the", "a", "an", "of", "in", "and", "or", "with", "by"}

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
    "premature",
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
    "changes": "functional change",
}

ECS_ONTOLOGIES = {
    "biological_object": "CL,UBERON,CHEBI",
    "biological_process": "GO",
    "phenotype": "UPHENO,HP,MP",
}

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
AOP_ANNOTATIONS_DIR = "outputs_for_vc/aop_based_ke_annotations"
SHARED_STORE_PATH = os.path.join(AOP_ANNOTATIONS_DIR, "ke_annotations.json")
AOP_STORE_PATH = os.path.join(AOP_ANNOTATIONS_DIR, "aop_based_ke_store.json")


# ---------------------------------------------------------------------------
# Helpers exported for use by other scripts
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


# ---------------------------------------------------------------------------
# KE title parsing
# ---------------------------------------------------------------------------

def _detect_biological_action(direction: str) -> str | None:
    for word in sorted(WIKI_ACTION_WORDS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(word)}\b', direction, re.IGNORECASE):
            return word
    for alt, canonical in sorted(ALTERATIVE_ACTION_WORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf'\b{re.escape(alt)}\b', direction, re.IGNORECASE):
            return canonical
    return None


_OBJECT_PREPOSITIONS = ["of", "in", "by", "on", "to", "from"]
_PROCESS_NOUN_SUFFIXES = ("ation", "tion", "sis", "ment", "ing", "ance", "ence", "al")


def _split_subject_on_preposition(subject: str) -> tuple[str, str] | None:
    for prep in _OBJECT_PREPOSITIONS:
        match = re.search(rf'\b{prep}\b\s+', subject, re.IGNORECASE)
        if match:
            process_phrase = subject[:match.start()].strip()
            object_phrase = subject[match.end():].strip()
            if process_phrase and object_phrase:
                return process_phrase, object_phrase
    return None


def _split_noun_compound(subject: str) -> str | None:
    words = subject.split()
    if len(words) < 2:
        return None
    last = words[-1].lower()
    if any(last.endswith(suffix) for suffix in _PROCESS_NOUN_SUFFIXES):
        return " ".join(words[:-1])
    return None


def _extract_biological_object(subject: str) -> str:
    split = _split_subject_on_preposition(subject)
    if split:
        return split[1]
    compound = _split_noun_compound(subject)
    if compound:
        return compound
    return subject


def _split_conjoined_subjects(subject: str) -> list[str]:
    parts = re.split(r'\s+and\s+', subject, flags=re.IGNORECASE)
    stripped = [p.strip() for p in parts if p.strip()]
    if len(stripped) > 1 and all(len(p.split()) > 1 for p in stripped):
        return stripped
    return [subject]


def parse_ke_title(title: str) -> dict:
    """
    Parse a KE title into candidate ECS component phrases.

    Returns dict with keys:
        raw_direction      – text before the first comma
        biological_action  – matched AOP-Wiki controlled-vocab term, or None
        subjects           – list of subject phrases (split on ' and ' conjunctions)
        full_subject       – full subject phrase (unmodified)
    """
    cleaned = re.sub(r'\s*\([^)]{1,4}\)', '', title).strip()
    parts = cleaned.split(',', 1)
    direction = parts[0].strip()
    subject = parts[1].strip() if len(parts) > 1 else cleaned

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


# ---------------------------------------------------------------------------
# BioPortal search
# ---------------------------------------------------------------------------

def normalize_phrase(phrase: str) -> str:
    tokens = [t for t in phrase.split() if t.lower() not in STOPWORDS]
    return " ".join(tokens)


def _iri_prefix(iri: str) -> str:
    """
    Extract the true ontology prefix from an OBO IRI.
    e.g. 'http://purl.obolibrary.org/obo/GO_0042921' → 'GO'
    Falls back to empty string for non-OBO IRIs.
    """
    m = re.search(r"/([A-Z]+)_\d+$", iri)
    return m.group(1) if m else ""


def search_bioportal(phrase: str, ontologies: str, api_key: str) -> list:
    """Search BioPortal for ontology terms matching a phrase."""
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
        term_id = item.get("@id", "")
        results.append({
            "ontology": _iri_prefix(term_id),
            "term_id": term_id,
            "label": item.get("prefLabel", ""),
            "synonyms": item.get("synonym", []),
        })
    return results


def search_with_fallback(phrase: str, ontologies: str, api_key: str) -> tuple[list, str]:
    """
    Search BioPortal with progressive fallback:
      1. Full phrase
      2. Normalized phrase (stopwords removed)
      3. Noun phrase after 'of'
    Returns (results, query_used).
    """
    results = search_bioportal(phrase, ontologies, api_key)
    if results:
        return results, phrase

    normalized = normalize_phrase(phrase)
    if normalized != phrase:
        results = search_bioportal(normalized, ontologies, api_key)
        if results:
            return results, f"{normalized!r} (stopwords removed)"

    of_match = re.search(r'\bof\s+(.+)$', phrase, re.IGNORECASE)
    if of_match:
        noun_phrase = normalize_phrase(of_match.group(1).strip())
        results = search_bioportal(noun_phrase, ontologies, api_key)
        if results:
            return results, f"{noun_phrase!r} (noun phrase fallback)"

    return [], phrase


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
# LLM functions  (all take an anthropic.Anthropic client; pass None to skip LLM)
# ---------------------------------------------------------------------------

def _make_client() -> anthropic.Anthropic | None:
    """Create and return an Anthropic client, or None if the API key is not set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


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
    parsed_resp = json.loads(json_match.group())
    idx_1based = parsed_resp.get("index")
    reason = parsed_resp.get("reason", "")
    if idx_1based is None:
        return None, reason
    return int(idx_1based) - 1, reason


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
    try:
        message = client.messages.create(
            model=LLM_MODEL,
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
    try:
        message = client.messages.create(
            model=LLM_MODEL,
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
        try:
            message = client.messages.create(
                model=LLM_MODEL,
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
# Term selection
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Per-component annotation helpers
# ---------------------------------------------------------------------------

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
    results, query_used = search_with_fallback(phrase, ontologies, api_key)
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
    Run biological_object, biological_process, and phenotype annotation for one subject phrase.
    When `ref` is supplied, any non-null property in it is used directly (query skipped).
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
        object_phrase = _extract_biological_object(subject)

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
            display_candidates(object_results[:5], object_used)
            result, source, reason = rank_term(title, "biological_object", object_results[:5], client)
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
        print(f"  Query phrase: {subject!r}")
        print(f"  Ontologies:   {ECS_ONTOLOGIES['biological_process']}")
        process_results, process_used = search_with_fallback(
            subject, ECS_ONTOLOGIES["biological_process"], api_key
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
                display_candidates(kept[:5], process_used)
                context = {"selected_object": selected_object_label} if selected_object_label else None
                result, source, reason = rank_term(title, "biological_process", kept[:5], client, context)
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
        print(f"  Ontologies:   {ECS_ONTOLOGIES['phenotype']}")
        phenotype_results, phenotype_used = search_with_fallback(
            subject, ECS_ONTOLOGIES["phenotype"], api_key
        )
        if phenotype_results:
            display_candidates(phenotype_results[:5], phenotype_used)
            result, source, reason = rank_term(title, "phenotype", phenotype_results[:5], client)
            if result:
                needs_review = result.get("ontology", "").upper() in _PHENOTYPE_GO_REVIEW_PREFIXES
                print(f"  → [{result['ontology']}] {result['label']}")
                print(f"     IRI:    {result['term_id']}")
                print(f"     reason: {reason}")
                if needs_review:
                    print("  ⚠ GO term assigned as phenotype — needs manual review")
                subj_annotation["phenotype"] = {
                    "term_id": result["term_id"],
                    "label": result["label"],
                    "ontology": result["ontology"],
                    "reason": reason,
                    "source": source,
                    **({"needs_review": True} if needs_review else {}),
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


def annotate_ke(
    ke_id: str,
    title: str,
    api_key: str,
    description: str = "",
    ref_ke: dict | None = None,
) -> dict:
    """
    Run the full ECS annotation workflow for a single KE.
    Returns the annotation dict.
    """
    client = _make_client()

    print(f"KE {ke_id}: {title}\n")

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

    # --- cell_term ---
    ref_cell = (ref_ke or {}).get("cell_term")
    if ref_cell is not None:
        print("--- cell_term ---")
        print(f"  (reference) {ref_cell.get('label', ref_cell)!r} — skipping query")
        annotation["cell_term"] = ref_cell
        print()
    elif org_level in _CELL_TERM_LEVELS:
        print("--- cell_term ---")
        annotation["cell_term"] = _annotate_term(
            parsed["full_subject"], CELL_TERM_ONTOLOGIES, "cell_term", description, api_key, client
        )
        print()

    # --- organ_term ---
    ref_organ = (ref_ke or {}).get("organ_term")
    if ref_organ is not None:
        print("--- organ_term ---")
        print(f"  (reference) {ref_organ.get('label', ref_organ)!r} — skipping query")
        annotation["organ_term"] = ref_organ
        print()
    elif org_level in _ORGAN_TERM_LEVELS:
        print("--- organ_term ---")
        annotation["organ_term"] = _annotate_term(
            parsed["full_subject"], ORGAN_TERM_ONTOLOGIES, "organ_term", description, api_key, client
        )
        print()

    # --- per-subject ECS annotation ---
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
# Storage
# ---------------------------------------------------------------------------

def _load_shared_store() -> dict:
    if os.path.exists(SHARED_STORE_PATH):
        with open(SHARED_STORE_PATH) as f:
            return json.load(f)
    return {}


def _save_shared_store(store: dict) -> None:
    os.makedirs(AOP_ANNOTATIONS_DIR, exist_ok=True)
    with open(SHARED_STORE_PATH, "w") as f:
        json.dump(store, f, indent=2)


def _load_aop_store() -> dict:
    if os.path.exists(AOP_STORE_PATH):
        with open(AOP_STORE_PATH) as f:
            return json.load(f)
    return {}


def _save_aop_store(aop_store: dict) -> None:
    os.makedirs(AOP_ANNOTATIONS_DIR, exist_ok=True)
    with open(AOP_STORE_PATH, "w") as f:
        json.dump(aop_store, f, indent=2)


def _register_ke_in_aop(aop_id: str, ke_id: str) -> None:
    aop_store = _load_aop_store()
    ke_ids = aop_store.setdefault(aop_id, [])
    if ke_id not in ke_ids:
        ke_ids.append(ke_id)
        _save_aop_store(aop_store)


def _cache_file(date_str: str) -> str:
    return os.path.join(CACHE_DIR_ROOT, date_str, f"all_events_{date_str}.json")


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def list_aop_kes(aop_id: str, cache_file: str) -> list[tuple[str, str]]:
    """Return [(ke_id, title), ...] for all KEs in the AOP, sorted by KE ID."""
    with open(cache_file) as f:
        events = json.load(f)
    kes = [
        (k, v.get("title", ""))
        for k, v in events.items()
        if aop_id in [str(x) for x in v.get("aop_ids", [])]
    ]
    return sorted(kes, key=lambda x: int(x[0]))


# ---------------------------------------------------------------------------
# CLI actions
# ---------------------------------------------------------------------------

def _strip_carried_suffix(comment: str) -> str:
    """Remove all trailing '[carried from reference]' suffixes from a comment string."""
    return re.sub(r'(\s*\[carried from reference\])+$', '', comment).strip()


def _mask_ref(ref_ke: dict, force_fields: set[str]) -> dict:
    """
    Return a copy of ref_ke with specified fields set to None.
    For ECS fields (phenotype, biological_process, biological_object, biological_action),
    the field is nulled in every subject within ec_annotations.
    """
    import copy
    masked = copy.deepcopy(ref_ke)
    top_level_fields = {"biological_organization", "cell_term", "organ_term"}
    ecs_fields = {"biological_object", "biological_process", "phenotype", "biological_action"}
    for field in force_fields:
        if field in top_level_fields and field in masked:
            masked[field] = None
        if field in ecs_fields:
            for subj in masked.get("ec_annotations", []):
                if field in subj:
                    subj[field] = None
    return masked


def annotate_single_ke(
    aop_id: str,
    ke_id: str,
    cache_file: str,
    force: bool = False,
    force_fields: set[str] | None = None,
) -> str:
    """
    Annotate one KE and write to the shared store. Registers the KE in the AOP index.

    force=True re-annotates all fields from scratch.
    force_fields re-annotates only the named fields, keeping all others from the reference.
    Returns the shared store path.
    """
    api_key = os.environ.get("BIOPORTAL_API_KEY")
    if not api_key:
        raise EnvironmentError("BIOPORTAL_API_KEY not set — add it to .env")

    with open(cache_file) as f:
        events = json.load(f)

    if ke_id not in events:
        print(f"KE {ke_id} not found in cache.")
        sys.exit(1)

    store = _load_shared_store()
    ref_ke = store.get(ke_id)
    if ref_ke:
        print(f"  (KE {ke_id} found in shared store — using as reference)")

    title = events[ke_id].get("title", "")
    description = events[ke_id].get("description", "")

    # Build the effective reference: mask selected fields when using --force-on
    if force:
        effective_ref = None
    elif force_fields:
        effective_ref = _mask_ref(ref_ke, force_fields) if ref_ke else None
    else:
        effective_ref = ref_ke

    annotation = annotate_ke(ke_id, title, api_key, description=description, ref_ke=effective_ref)

    # Carry comments forward, stripping duplicate "[carried from reference]" suffixes
    ref_comments = _flat_ref_comments((ref_ke or {}).get("comments"))
    clean_comments = [_strip_carried_suffix(c) for c in ref_comments]
    carried = [f"{c} [carried from reference]" for c in clean_comments]
    annotation["comments"] = {"carried": carried, "new": []}

    # newly_annotated_fields: compare against the original ref_ke (not effective_ref)
    # so only fields that genuinely didn't exist before are listed as new.
    ref_top_keys = {k for k, v in (ref_ke or {}).items() if v is not None}
    new_fields: list[str] = []
    for key, val in annotation.items():
        if key in ("ke_id", "title", "comments", "ec_annotations"):
            continue
        if val is not None and key not in ref_top_keys:
            new_fields.append(key)
    for subj in annotation.get("ec_annotations", []):
        ref_subj = next(
            (s for s in (ref_ke or {}).get("ec_annotations", [])
             if s.get("subject") == subj.get("subject")),
            {},
        )
        for field in ("biological_object", "biological_process", "phenotype"):
            if subj.get(field) is not None and ref_subj.get(field) is None:
                label = f"ec_annotations[{subj['subject']!r}].{field}"
                if label not in new_fields:
                    new_fields.append(label)
    if new_fields:
        annotation["newly_annotated_fields"] = new_fields

    store[ke_id] = annotation
    _save_shared_store(store)
    _register_ke_in_aop(aop_id, ke_id)

    print("\n" + "=" * 60)
    print(f"ANNOTATION SUMMARY — KE {ke_id}: {title}")
    print("=" * 60)
    print(f"  biological_organization: {annotation.get('biological_organization')}")
    cell = annotation.get("cell_term")
    organ = annotation.get("organ_term")
    print(f"  cell_term:  {cell.get('label') if cell else None}")
    print(f"  organ_term: {organ.get('label') if organ else None}")
    for subj in annotation.get("ec_annotations", []):
        print(f"\n  subject: {subj['subject']!r}")
        action = subj.get("biological_action", {})
        print(f"    biological_action:  {action.get('term') if action else None}")
        obj = subj.get("biological_object")
        proc = subj.get("biological_process")
        phen = subj.get("phenotype")
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
    print(f"\nSaved to {SHARED_STORE_PATH}")
    print("=" * 60)

    return SHARED_STORE_PATH


def add_comment(ke_id: str, comment: str) -> None:
    store = _load_shared_store()
    if ke_id not in store:
        print(f"KE {ke_id} not found in shared store — annotate it first.")
        sys.exit(1)
    store[ke_id].setdefault("comments", {"carried": [], "new": []})
    store[ke_id]["comments"]["new"].append(comment)
    _save_shared_store(store)
    print(f"Comment added to KE {ke_id}. Saved to {SHARED_STORE_PATH}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Annotate KEs for an AOP (one at a time)")
    parser.add_argument("--aop", required=True, help="AOP ID (e.g. 173)")
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
            "biological_object, biological_process, phenotype, biological_action."
        ),
    )
    parser.add_argument(
        "--date",
        default=datetime.date.today().strftime("%m-%d-%Y"),
        help="Cache date MM-DD-YYYY (default: today)",
    )
    args = parser.parse_args()

    cache = _cache_file(args.date)
    if not os.path.exists(cache):
        print(f"Cache file not found: {cache}")
        sys.exit(1)

    if args.add_comment:
        if not args.ke_id:
            print("--add-comment requires --ke-id")
            sys.exit(1)
        add_comment(args.ke_id, args.add_comment)
        return

    if args.ke_id is None:
        kes = list_aop_kes(args.aop, cache)
        if not kes:
            print(f"No KEs found for AOP {args.aop}")
            sys.exit(1)
        store = _load_shared_store()
        print(f"\nAOP {args.aop} — {len(kes)} KEs")
        print(f"Shared KE store: {SHARED_STORE_PATH}")
        print(f"AOP store:       {AOP_STORE_PATH}")
        print()
        for ke_id, title in kes:
            status = "✓ done" if ke_id in store else "pending"
            print(f"  [{status}] KE {ke_id}: {title}")
        return

    force_fields = set(args.force_fields) if args.force_fields else None

    store = _load_shared_store()
    if args.ke_id in store and not args.force and not force_fields:
        print(f"KE {args.ke_id} already in shared store. Use --force to re-annotate or --force-on <field> to re-annotate specific fields.")
        _register_ke_in_aop(args.aop, args.ke_id)
        return

    annotate_single_ke(args.aop, args.ke_id, cache, force=args.force, force_fields=force_fields)


if __name__ == "__main__":
    main()
