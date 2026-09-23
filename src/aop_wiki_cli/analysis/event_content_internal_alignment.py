"""
Event content internal alignment
================================

Checks whether an AOP-Wiki Event's structured properties agree with what its own
free text says. It is meant to run before an Event's structured properties are
used to decide what to look for elsewhere, so that an Event whose level, taxa,
sex or life stage contradicts its own description is caught first.

**Prototype scope: the level check only.** One check runs:

- ``level``: the level of biological organization against the description.

Three further checks - taxa, sex and life stage against the description and the
domain-of-applicability text - are written and commented out further down, with
the reason there.

Both halves of the level check come from the AOP-Wiki EMOD LinkML schema (the
``linkml_aop`` package) rather than from this module: the permitted levels are
BiologicalOrganizationEnum's values, and the words the check searches for are
derived from each value's *definition*. Refining a definition in linkml-aop
refines this check, with no edit here.

**This is a screening report, not a gate.** Every check is a keyword heuristic
over prose. A ``flag`` means the structured value and the text look inconsistent
and a person should read the Event; a ``note`` is weaker, and is worth a look
only when reviewing that Event anyway; ``unchecked`` means the text the check
reads is empty, so nothing was compared. None is a verdict. In particular, the
level check reads cue words for the level at which a change *happens*, and cannot
tell that apart from where it happens to be *measured* - the distinction that
makes it worth running at all has to be confirmed by a reader.

The Handbook rule the level check rests on (AOP Developers' Handbook v2.8,
Section 2): "KEs should be defined within a particular level of biological
organisation. Only KERs should be used to transition from one level of
organisation to another."
"""

from __future__ import annotations

import html
import re
from functools import lru_cache
from importlib.resources import files
from typing import Iterable

from linkml_runtime.utils.schemaview import SchemaView

FLAG = "flag"
NOTE = "note"
# The check could not be made at all: the field it reads is empty. Kept separate
# from NOTE so that "nothing to read" is never counted as a weak observation
# about text. Most of AOP-Wiki's Events have no description.
UNCHECKED = "unchecked"
SEVERITIES = (FLAG, NOTE, UNCHECKED)

# Text fields read by the checks. Measurement-method text is deliberately not
# read: it names test systems, and a species used as a test system is not a
# statement about the Event's applicability.
DESCRIPTION = "description"
DOMAIN_OF_APPLICABILITY = "doa_free_text"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def schema_view() -> SchemaView:
    """Load the AOP-Wiki EMOD LinkML schema shipped in the linkml_aop package."""
    path = files("linkml_aop") / "schema" / "aop_emod_linkml.yaml"
    return SchemaView(str(path))


def enum_values(enum_name: str) -> list[str]:
    """Permissible values of one schema enum, in schema order."""
    enum = schema_view().get_enum(enum_name)
    if enum is None:
        raise KeyError(f"{enum_name} is not defined in the linkml_aop schema")
    return list(enum.permissible_values)


def enum_description(enum_name: str, value: str) -> str | None:
    """A permissible value's description in the schema, when it has one."""
    pv = schema_view().get_enum(enum_name).permissible_values.get(value)
    return pv.description if pv is not None else None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def strip_html(text: str | None) -> str:
    """Remove HTML tags and entities and collapse whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _find(patterns: Iterable[str], text: str) -> list[str]:
    """Return the distinct matched strings, lowercased, in order of first match."""
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            word = match.group(0).lower()
            if word not in found:
                found.append(word)
    return found


def _finding(ke_id, check, severity, message, field=None, evidence=None, definition=None) -> dict:
    """One finding. ``definition`` carries the schema text the check was made against."""
    return {
        "ke_id": str(ke_id),
        "check": check,
        "severity": severity,
        "message": message,
        "field": field,
        "evidence": evidence or [],
        "definition": definition,
    }


# ---------------------------------------------------------------------------
# Level of biological organization
# ---------------------------------------------------------------------------

# The level check's vocabulary is derived from the schema's own definition of each
# level (BiologicalOrganizationEnum), so refining a definition in linkml-aop changes
# what this check looks for. Derivation is deliberately mechanical: take the words
# of the definition, drop the quoted examples, drop a stop list of framework and
# grammatical words, and match each remaining word with its plural.
#
# What that costs: a definition's incidental words become cues too. "described
# without regard to the cell it occurs in" puts "cell" among the Molecular cues,
# and an example-free definition yields no cue for a term it never spells
# ("trachea" is not in the Organ definition). Both failures make the check quieter
# rather than noisier, because a flag needs the assigned level to have *no* cue.
LEVEL_ENUM = "BiologicalOrganizationEnum"

# Words carried by the definitions that describe the framework rather than the
# biology. They would otherwise match almost any Event text.
DEFINITION_STOP_WORDS = frozenset("""
a an and are as at be been between by can for from in is it its of on or other others
rather than that the their these this to used using where which while with without within
level levels event events key sits sit occurs occur example examples such state states
unit units scale term terms list fixed permitted value values definition definitions
adverse outcome outcomes initiating regulatory toxicity test tests endpoint endpoints
apical typically mainly most also described regard mechanism inside group groups
considered individuals amount handbook says wildlife pollinator pathway pathways concern
will often demographic significance eusocial species them whose here type changes whole
increase decrease loss reduction occur
""".split())

# Cues this module adds to the schema's own. Deliberately empty: a word the level
# check needs is a gap in the schema definition, and belongs in linkml-aop rather
# than here. Anything added here should carry a note saying why it could not.
SUPPLEMENTARY_LEVEL_CUES: dict[str, list[str]] = {}


def _cue_pattern(word: str) -> str:
    """Word-boundary pattern for one cue word, matching its plural too."""
    stem = word[:-1] if word.endswith("s") and not word.endswith(("ss", "is", "us")) else word
    return rf"\b{re.escape(stem)}(?:s|es)?\b"


@lru_cache(maxsize=1)
def level_cues() -> dict[str, list[str]]:
    """Cue patterns per level, derived from the schema's definition of each level.

    Quoted examples are excluded: they illustrate the level with particular Key
    Event titles, and their words (a receptor name, a cell type) are not vocabulary
    for the level itself.
    """
    cues: dict[str, list[str]] = {}
    for level in enum_values(LEVEL_ENUM):
        definition = enum_description(LEVEL_ENUM, level) or ""
        without_examples = re.sub(r'"[^"]*"', " ", definition)
        words: list[str] = []
        for token in re.findall(r"[A-Za-z][A-Za-z-]{3,}", without_examples.lower()):
            if token not in DEFINITION_STOP_WORDS and token not in words:
                words.append(token)
        patterns = [_cue_pattern(w) for w in words]
        patterns += [p for p in SUPPLEMENTARY_LEVEL_CUES.get(level, []) if p not in patterns]
        cues[level] = patterns
    return cues


# Levels above which carrying a cell term is unexpected.
_ABOVE_TISSUE = {"Organ", "Individual", "Population"}


def check_level(ke_id: str, event: dict) -> list[dict]:
    """Compare the assigned level of biological organization with the description.

    Flags when the description carries cue words for other levels and none for
    the assigned one. Notes when the description carries no cues at all (nothing
    to judge from), and when a cell term is attached to an Event above tissue
    level.
    """
    findings: list[dict] = []
    level = event.get("level_of_biological_organization")
    valid = enum_values("BiologicalOrganizationEnum")

    if not level:
        return [_finding(ke_id, "level", NOTE, "No level of biological organization is assigned.")]
    if level not in valid:
        return [_finding(ke_id, "level", FLAG,
                         f"Assigned level {level!r} is not a value of BiologicalOrganizationEnum.",
                         evidence=valid)]

    text = strip_html(event.get(DESCRIPTION))
    all_cues = level_cues()
    cues = {lvl: _find(all_cues.get(lvl, []), text) for lvl in valid}
    other = {lvl: words for lvl, words in cues.items() if lvl != level and words}

    if not text:
        findings.append(_finding(ke_id, "level", UNCHECKED,
                                 f"The Event has no description, so its assigned level ({level}) "
                                 "was not checked.", field=DESCRIPTION))
    elif not any(cues.values()):
        findings.append(_finding(ke_id, "level", NOTE,
                                 "The description has text but no level cue words, so the assigned "
                                 f"level ({level}) cannot be checked against it. The cue words come "
                                 "from the schema's definitions, so this may be a gap in them.",
                                 field=DESCRIPTION))
    elif not cues[level] and other:
        summary = "; ".join(f"{lvl}: {', '.join(words)}" for lvl, words in other.items())
        findings.append(_finding(
            ke_id, "level", FLAG,
            f"Assigned level is {level}, but the description has no {level}-level cue words "
            f"and does have cue words for other levels ({summary}). Read the description to "
            "decide whether the change happens at another level, or whether the assigned "
            "level reflects where the change is measured rather than where it happens.",
            field=DESCRIPTION,
            evidence=[f"{lvl}: {w}" for lvl, words in other.items() for w in words],
            definition=enum_description(LEVEL_ENUM, level),
        ))

    cell_term = (event.get("cell_term") or {}).get("term")
    if cell_term and level in _ABOVE_TISSUE:
        findings.append(_finding(ke_id, "level", NOTE,
                                 f"A cell term ({cell_term}) is attached to an Event at {level} level.",
                                 field="cell_term", evidence=[cell_term]))
    return findings


# ---------------------------------------------------------------------------
# Taxonomic applicability, sex and life stage - COMMENTED OUT
# ---------------------------------------------------------------------------
#
# Held back from the prototype, which checks the level of biological organization
# only. The code below works and its tests passed (see the commented-out tests in
# tests/test_event_content_internal_alignment.py), but unlike the level check it
# cannot read its vocabulary from the schema:
#
# - the species names and the taxonomy-term titles that list them are written
#   here, because the schema carries no species vocabulary and none is expected;
# - which sex and life-stage values mean "applies to every sex" or "every life
#   stage" is asserted here, because the permissible values of SexTermEnum and
#   LifeStageTermEnum carry no descriptions. The SexTerm, LifeStageTerm and
#   TaxonTerm *class* descriptions exist; the values themselves are bare.
#
# Restoring these means uncommenting the code below, adding the checks back to
# CHECKS, and uncommenting their tests. Do it once the enum values are defined in
# linkml-aop, so the local lists can be replaced the way the level cues were.
#
# # ---------------------------------------------------------------------------
# # Taxonomic applicability
# # ---------------------------------------------------------------------------
#
# # Each species key maps to the text patterns that name it and the taxonomy-term
# # titles (scientific or common, lowercased) that list it. Multi-word patterns are
# # matched first and removed from the text, so "guinea pigs" is not also read as
# # "pigs".
# SPECIES: dict[str, dict[str, list[str]]] = {
#     "human": {"text": [r"\bhumans?\b"], "titles": ["homo sapiens", "human"]},
#     "mouse": {"text": [r"\bmouse\b", r"\bmice\b"], "titles": ["mus musculus", "mouse"]},
#     "rat": {"text": [r"\brats?\b"], "titles": ["rattus norvegicus", "rat"]},
#     "guinea pig": {"text": [r"\bguinea pigs?\b"], "titles": ["cavia porcellus", "guinea pig"]},
#     "rabbit": {"text": [r"\brabbits?\b"], "titles": ["oryctolagus cuniculus", "rabbit"]},
#     "pig": {"text": [r"\bpigs?\b", r"\bswine\b", r"\bporcine\b"],
#             "titles": ["sus scrofa", "sus scrofa domesticus", "pig"]},
#     "sheep": {"text": [r"\bsheep\b", r"\bovine\b"], "titles": ["ovis aries", "sheep"]},
#     "cattle": {"text": [r"\bcattle\b", r"\bbovine\b", r"\bcows?\b"], "titles": ["bos taurus", "cattle"]},
#     "dog": {"text": [r"\bdogs?\b", r"\bcanine\b"], "titles": ["canis lupus", "canis lupus familiaris", "dog"]},
#     "cat": {"text": [r"\bcats?\b", r"\bfeline\b"], "titles": ["felis catus", "cat"]},
#     "horse": {"text": [r"\bhorses?\b", r"\bequine\b"], "titles": ["equus caballus", "horse"]},
#     "bullfrog": {"text": [r"\bbullfrogs?\b"],
#                  "titles": ["lithobates catesbeianus", "rana catesbeiana", "bullfrog"]},
#     "zebrafish": {"text": [r"\bzebrafish\b"], "titles": ["danio rerio", "zebrafish"]},
# }
#
# # Group words, satisfied if any member species is listed.
# SPECIES_GROUPS: dict[str, dict] = {
#     "rodents": {"text": [r"\brodents?\b"], "members": ["mouse", "rat", "guinea pig"]},
# }
#
#
# def _mentioned_species(text: str) -> tuple[list[str], list[str]]:
#     """Species keys and group keys named in the text."""
#     remaining = text
#     species: list[str] = []
#     ordered = sorted(SPECIES.items(), key=lambda kv: -max(len(p) for p in kv[1]["text"]))
#     for key, spec in ordered:
#         for pattern in spec["text"]:
#             if re.search(pattern, remaining, flags=re.IGNORECASE):
#                 if key not in species:
#                     species.append(key)
#                 remaining = re.sub(pattern, " ", remaining, flags=re.IGNORECASE)
#     groups = [g for g, spec in SPECIES_GROUPS.items()
#               if any(re.search(p, remaining, flags=re.IGNORECASE) for p in spec["text"])]
#     return species, groups
#
#
# def _listed_species(event: dict) -> tuple[list[str], list[str]]:
#     """Species keys the taxonomy terms list, and titles this module cannot map."""
#     listed, unmapped = [], []
#     for term in event.get("taxonomy_terms") or []:
#         title = (term.get("title") or "").strip().lower()
#         key = next((k for k, spec in SPECIES.items() if title in spec["titles"]), None)
#         if key:
#             if key not in listed:
#                 listed.append(key)
#         elif title:
#             unmapped.append(term.get("title"))
#     return listed, unmapped
#
#
# def check_taxa(ke_id: str, event: dict) -> list[dict]:
#     """Compare the taxonomy terms with species named in the Event's text.
#
#     Flags a species named in the domain-of-applicability text but not listed.
#     Notes the same in the description, where a species is often a study system
#     rather than a claim of applicability, and notes listed species the text never
#     names.
#     """
#     findings: list[dict] = []
#     listed, unmapped = _listed_species(event)
#
#     mentioned_anywhere: set[str] = set()
#     for field, severity in ((DOMAIN_OF_APPLICABILITY, FLAG), (DESCRIPTION, NOTE)):
#         text = strip_html(event.get(field))
#         if not text:
#             continue
#         species, groups = _mentioned_species(text)
#         mentioned_anywhere.update(species)
#         missing = [s for s in species if s not in listed]
#         missing += [g for g in groups
#                     if not any(m in listed for m in SPECIES_GROUPS[g]["members"])]
#         if missing:
#             findings.append(_finding(
#                 ke_id, "taxa", severity,
#                 f"The {field} names {', '.join(missing)}, which the taxonomy terms do not list.",
#                 field=field, evidence=missing))
#         for g in groups:
#             mentioned_anywhere.update(m for m in SPECIES_GROUPS[g]["members"] if m in listed)
#
#     unnamed = [s for s in listed if s not in mentioned_anywhere]
#     if unnamed:
#         findings.append(_finding(
#             ke_id, "taxa", NOTE,
#             f"Listed taxa not named in the description or applicability text: {', '.join(unnamed)}. "
#             "Their support may be in references or other fields.",
#             field="taxonomy_terms", evidence=unnamed))
#     if unmapped:
#         findings.append(_finding(
#             ke_id, "taxa", NOTE,
#             f"Taxonomy terms this check cannot map to a species: {', '.join(unmapped)}.",
#             field="taxonomy_terms", evidence=unmapped))
#     return findings
#
#
# # ---------------------------------------------------------------------------
# # Sex and life stage
# # ---------------------------------------------------------------------------
#
# # Phrases stating that an Event applies regardless of a property.
# _UNIVERSAL = r"(?:independent of|regardless of|irrespective of)[^.]{0,60}?\b{target}\b"
# _SEX_UNIVERSAL = [_UNIVERSAL.replace("{target}", r"(?:gender|sex)"), r"\bboth sexes\b"]
# _LIFE_STAGE_UNIVERSAL = [_UNIVERSAL.replace("{target}", r"(?:life stages?|age)"), r"\ball life stages\b"]
#
# # Values meaning "applies to all", per the schema's enums. Checked against the
# # schema at run time so a renamed value fails loudly instead of silently.
# SEX_ALL = ["Mixed", "Unspecific"]
# LIFE_STAGE_ALL = ["All life stages", "Not Otherwise Specified"]
#
#
# def _universal_check(ke_id, event, check, terms_key, enum_name, all_values, patterns) -> list[dict]:
#     valid = enum_values(enum_name)
#     for value in all_values:
#         if value not in valid:
#             raise KeyError(f"{value!r} is no longer a value of {enum_name}; update {check} check")
#
#     findings: list[dict] = []
#     terms = event.get(terms_key) or []
#     bad = [t for t in terms if t not in valid]
#     if bad:
#         findings.append(_finding(ke_id, check, FLAG,
#                                  f"Values not in {enum_name}: {', '.join(bad)}.",
#                                  field=terms_key, evidence=bad))
#
#     covers_all = any(t in all_values for t in terms)
#     for field in (DOMAIN_OF_APPLICABILITY, DESCRIPTION):
#         text = strip_html(event.get(field))
#         hits = _find(patterns, text)
#         if hits and terms and not covers_all:
#             findings.append(_finding(
#                 ke_id, check, FLAG,
#                 f"The {field} says the Event applies regardless of {check.replace('_', ' ')} "
#                 f"({hits[0]!r}), but the {terms_key} are restricted to {', '.join(terms)}.",
#                 field=field, evidence=hits))
#     return findings
#
#
# def check_sex(ke_id: str, event: dict) -> list[dict]:
#     """Flag sex terms that the Event's text contradicts."""
#     return _universal_check(ke_id, event, "sex", "sex_terms", "SexTermEnum",
#                             SEX_ALL, _SEX_UNIVERSAL)
#
#
# def check_life_stage(ke_id: str, event: dict) -> list[dict]:
#     """Flag life-stage terms that the Event's text contradicts."""
#     return _universal_check(ke_id, event, "life_stage", "life_stage_terms", "LifeStageTermEnum",
#                             LIFE_STAGE_ALL, _LIFE_STAGE_UNIVERSAL)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

# Prototype: the level check only. See the commented-out block above.
CHECKS = (check_level,)


def check_event(ke_id: str, event: dict) -> list[dict]:
    """Run every check on one Event and return its findings."""
    findings: list[dict] = []
    for check in CHECKS:
        findings.extend(check(ke_id, event))
    return findings


# Columns of the review report, in reading order: what the Event is, what the
# check concluded, and the text it concluded it from. A reader should not have to
# open AOP-Wiki to judge a finding, so the description travels with it.
REPORT_COLUMNS = (
    "ke_id",
    "title",
    "assigned_level",
    "severity",
    "check",
    "cue_words_found",
    "message",
    "description",
    "url",
    "level_definition",
)

# Longest description carried into the CSV. The JSON report keeps the full text.
DESCRIPTION_LIMIT = 1500


def finding_rows(findings: list[dict], events: dict, description_limit: int = DESCRIPTION_LIMIT) -> list[dict]:
    """Turn findings into review rows, each carrying the Event text it was made from."""
    rows = []
    for f in findings:
        event = events.get(f["ke_id"]) or {}
        text = strip_html(event.get(DESCRIPTION))
        if description_limit and len(text) > description_limit:
            text = text[:description_limit].rstrip() + " [...]"
        rows.append({
            "ke_id": f["ke_id"],
            "title": (event.get("title") or "").strip(),
            "assigned_level": event.get("level_of_biological_organization") or "",
            "severity": f["severity"],
            "check": f["check"],
            "cue_words_found": "; ".join(f["evidence"]),
            "message": f["message"],
            "description": text,
            "url": f"https://aopwiki.org/events/{f['ke_id']}",
            "level_definition": f.get("definition") or "",
        })
    return rows


def check_events(events: dict, ke_ids: Iterable[str] | None = None) -> dict:
    """Run every check on a collection of Events keyed by Key Event ID.

    Returns ``{"findings": [...], "summary": {...}}``. The summary counts Events
    read, Events with at least one flag, Events no check could read at all, and
    findings by check and severity.
    """
    ids = [str(k) for k in ke_ids] if ke_ids else list(events)
    findings: list[dict] = []
    missing: list[str] = []
    for ke_id in ids:
        event = events.get(ke_id)
        if event is None and ke_id.isdigit():
            event = events.get(int(ke_id))
        if event is None:
            missing.append(ke_id)
            continue
        findings.extend(check_event(ke_id, event))

    by_check: dict[str, dict[str, int]] = {}
    for f in findings:
        by_check.setdefault(f["check"], {sev: 0 for sev in SEVERITIES})[f["severity"]] += 1
    unchecked = {f["ke_id"] for f in findings if f["severity"] == UNCHECKED}
    summary = {
        "events_read": len(ids) - len(missing),
        "events_not_found": missing,
        "events_with_flags": len({f["ke_id"] for f in findings if f["severity"] == FLAG}),
        "events_unchecked": len(unchecked),
        "findings_by_check": by_check,
    }
    return {"findings": findings, "summary": summary}
