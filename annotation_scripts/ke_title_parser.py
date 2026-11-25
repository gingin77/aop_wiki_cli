"""
Rule-based parsing of AOP-Wiki Key Event titles into ECS component phrases.

KE titles follow the pattern: "<direction>, <subject>"
e.g. "increased, sodium channel opening" → direction="increased", subject="sodium channel opening"
"""

import re

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

ALTERNATIVE_ACTION_WORDS = {
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

# Backwards-compatible alias for the previous (misspelled) name
ALTERATIVE_ACTION_WORDS = ALTERNATIVE_ACTION_WORDS

_OBJECT_PREPOSITIONS = ["of", "in", "by", "on", "to", "from"]
_PROCESS_NOUN_SUFFIXES = ("ation", "tion", "sis", "ment", "ing", "ance", "ence", "al")


def _detect_biological_action(direction: str) -> str | None:
    for word in sorted(WIKI_ACTION_WORDS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(word)}\b', direction, re.IGNORECASE):
            return word
    for alt, canonical in sorted(ALTERNATIVE_ACTION_WORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf'\b{re.escape(alt)}\b', direction, re.IGNORECASE):
            return canonical
    return None


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


def extract_biological_object(subject: str) -> str:
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
