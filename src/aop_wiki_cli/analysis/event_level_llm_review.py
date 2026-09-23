"""
Event level review by an LLM
============================

An opt-in second opinion on the check in ``event_content_internal_alignment``:
does an Event's description describe a change at the level of biological
organization the Event is assigned to?

The deterministic check searches the description for words drawn from the
schema's definition of each level. That is cheap and offline, and it misses
alignment it has no words for. KE 97 *Alkylation, DNA* is the worked case: its
description is unmistakably molecular - DNA adducts, alkylated nucleotides,
methyl and ethyl groups, the phosphate diester group - and shares not one word
with the Molecular definition's vocabulary, so the keyword pass can only report
that it recognised nothing. Widening the word lists fixes that Event and not the
next one, because a definition cannot enumerate the vocabulary of a level.

This module asks a model the same question the definitions ask, giving it the
definitions as the criterion. It does not replace the deterministic pass:

- the deterministic pass is unchanged, runs offline, and costs nothing;
- an Event with no description is never sent to the model;
- every record says which pass produced it, which model, and against which
  definitions, so a disagreement is traceable.

**A model's answer is a second opinion, not a verdict.** It is recorded as a
finding for a person to read, exactly like a keyword finding.

Usage::

    from aop_wiki_cli.analysis.event_level_llm_review import review_events
    result = review_events(events, ke_ids=["97", "1909"])

Requires credentials for the Anthropic API (``ANTHROPIC_API_KEY``, or a profile
from ``ant auth login``). Pass ``client=`` to inject a configured client, which
is also how the tests run without network access.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from aop_wiki_cli.analysis.event_content_internal_alignment import (
    DESCRIPTION,
    FLAG,
    LEVEL_ENUM,
    NOTE,
    UNCHECKED,
    enum_description,
    enum_values,
    strip_html,
)

CHECK = "level_llm"

# Claude Opus 5. Override per call; recorded on every finding either way.
DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 4000

# Longest description sent to the model. Long descriptions are truncated rather
# than dropped, and the finding says so.
DESCRIPTION_LIMIT = 12000

SYSTEM_PROMPT = """\
You are screening Key Event records from the AOP-Wiki for one specific problem: \
an Event assigned to a level of biological organization that its own description \
does not describe.

The levels and their definitions are below. They are the criterion. Judge the \
Event against these definitions and nothing else - not against how AOP-Wiki \
usually assigns levels, and not against your own preferred taxonomy.

{definitions}

Two rules from the AOP Developers' Handbook v2.8 bear on this:

- A Key Event is defined within a single level of biological organisation. Only a \
Key Event Relationship transitions from one level to another. So a description \
that describes changes at two levels is itself a finding.
- The level is the level at which the change *happens*, not the level at which it \
is *measured*. A change in a tissue that is measured in a whole animal is still a \
tissue-level change.

Judge only what the description says. If the description is too short, too \
vague, or says nothing about what changes, say so with best_fit_level "cannot \
tell" rather than inferring a level from the Event's title.\
"""

USER_PROMPT = """\
Key Event {ke_id}
Title: {title}
Assigned level: {level}

Description:
{description}\
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assigned_level_fits": {
            "type": "boolean",
            "description": "True if the description describes a change at the assigned level.",
        },
        "best_fit_level": {
            "type": "string",
            "description": (
                "The level the description best fits, or 'cannot tell' when the "
                "description does not say what changes."
            ),
        },
        "spans_multiple_levels": {
            "type": "boolean",
            "description": "True if the description describes changes at more than one level.",
        },
        "quoted_evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short verbatim quotes from the description that decided the answer.",
        },
        "reasoning": {
            "type": "string",
            "description": "One or two sentences saying why, referring to the definitions.",
        },
        "confidence": {
            "type": "string",
            "description": "high, moderate, or low.",
        },
    },
    "required": [
        "assigned_level_fits",
        "best_fit_level",
        "spans_multiple_levels",
        "quoted_evidence",
        "reasoning",
        "confidence",
    ],
    "additionalProperties": False,
}

CANNOT_TELL = "cannot tell"


def level_definitions() -> dict[str, str]:
    """The schema's definition of each level, in schema order."""
    return {level: (enum_description(LEVEL_ENUM, level) or "") for level in enum_values(LEVEL_ENUM)}


def definitions_digest() -> str:
    """A short hash of the definitions a review was made against.

    Recorded on every finding so a result can be told apart from one made
    against a later revision of the definitions in linkml-aop.
    """
    text = json.dumps(level_definitions(), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def build_system_prompt() -> str:
    """The system prompt, carrying the schema's level definitions as the criterion."""
    blocks = [f"{level}: {definition}" for level, definition in level_definitions().items() if definition]
    if not blocks:
        raise RuntimeError(
            "No level definitions in the linkml_aop schema; the review has no criterion to apply."
        )
    return SYSTEM_PROMPT.format(definitions="\n\n".join(blocks))


def build_user_prompt(ke_id: str, event: dict, description: str) -> str:
    return USER_PROMPT.format(
        ke_id=ke_id,
        title=(event.get("title") or "").strip(),
        level=event.get("level_of_biological_organization") or "(none assigned)",
        description=description,
    )


def _default_client():
    import anthropic  # imported here so the deterministic pass needs no SDK

    return anthropic.Anthropic()


def _parse_response(response: Any) -> dict:
    """Read the JSON object out of a Messages API response."""
    text = next(
        (block.text for block in response.content if getattr(block, "type", None) == "text"),
        None,
    )
    if text is None:
        raise ValueError("No text block in the model response")
    return json.loads(text)


def review_event(
    ke_id: str,
    event: dict,
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
    description_limit: int = DESCRIPTION_LIMIT,
) -> dict | None:
    """Ask the model whether one Event's description fits its assigned level.

    Returns a finding when the model disagrees with the assigned level (``flag``),
    when it cannot tell from the description (``note``), when the description
    spans several levels (``flag``, which the Handbook rule forbids), or when
    there is no description to send (``unchecked``). Returns ``None`` when the
    model agrees, so that a run reports what is worth reading, as the
    deterministic pass does.
    """
    level = event.get("level_of_biological_organization")
    description = strip_html(event.get(DESCRIPTION))
    truncated = False
    if description_limit and len(description) > description_limit:
        description = description[:description_limit].rstrip()
        truncated = True

    base = {
        "ke_id": str(ke_id),
        "check": CHECK,
        "field": DESCRIPTION,
        "model": model,
        "definitions_digest": definitions_digest(),
        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "description_truncated": truncated,
    }

    if not description:
        return {**base, "severity": UNCHECKED,
                "message": f"The Event has no description, so its assigned level ({level}) was not reviewed.",
                "model": None, "reviewed_at": None}
    if not level:
        return {**base, "severity": UNCHECKED,
                "message": "The Event has no assigned level, so there is nothing to review it against.",
                "model": None, "reviewed_at": None}

    client = client or _default_client()
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=build_system_prompt(),
        messages=[{"role": "user", "content": build_user_prompt(ke_id, event, description)}],
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    )
    verdict = _parse_response(response)

    finding = {
        **base,
        "assigned_level": level,
        "best_fit_level": verdict.get("best_fit_level"),
        "confidence": verdict.get("confidence"),
        "evidence": verdict.get("quoted_evidence") or [],
        "reasoning": verdict.get("reasoning", ""),
    }

    if not verdict.get("assigned_level_fits"):
        best = verdict.get("best_fit_level") or CANNOT_TELL
        if best.strip().lower() == CANNOT_TELL:
            return {**finding, "severity": NOTE,
                    "message": (f"The model could not tell from the description whether the assigned "
                                f"level ({level}) fits. {verdict.get('reasoning', '')}".strip())}
        return {**finding, "severity": FLAG,
                "message": (f"The model reads the description as describing a {best}-level change, "
                            f"not the assigned {level}. {verdict.get('reasoning', '')}".strip())}
    if verdict.get("spans_multiple_levels"):
        return {**finding, "severity": FLAG,
                "message": (f"The assigned level ({level}) fits, but the model reads the description as "
                            f"spanning more than one level, which a Key Event should not. "
                            f"{verdict.get('reasoning', '')}".strip())}
    return None


def review_events(
    events: dict,
    ke_ids: Iterable[str] | None = None,
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
    on_error: str = "record",
) -> dict:
    """Review a collection of Events, one request each.

    ``on_error`` decides what a failed request does: ``record`` keeps an error
    finding and carries on, ``raise`` stops the run.
    """
    ids = [str(k) for k in ke_ids] if ke_ids else list(events)
    findings: list[dict] = []
    missing: list[str] = []
    agreed = 0
    errors = 0

    for ke_id in ids:
        event = events.get(ke_id)
        if event is None and ke_id.isdigit():
            event = events.get(int(ke_id))
        if event is None:
            missing.append(ke_id)
            continue
        try:
            finding = review_event(ke_id, event, client=client, model=model)
        except Exception as exc:  # noqa: BLE001 - a failed request is a result, not a crash
            if on_error == "raise":
                raise
            errors += 1
            findings.append({
                "ke_id": ke_id, "check": CHECK, "severity": "error", "field": DESCRIPTION,
                "message": f"The review request failed: {type(exc).__name__}: {exc}",
                "model": model, "evidence": [],
            })
            continue
        if finding is None:
            agreed += 1
        else:
            findings.append(finding)

    by_severity: dict[str, int] = {}
    for f in findings:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    summary = {
        "events_read": len(ids) - len(missing),
        "events_not_found": missing,
        "events_model_agreed": agreed,
        "events_with_flags": len({f["ke_id"] for f in findings if f["severity"] == FLAG}),
        "request_errors": errors,
        "findings_by_severity": by_severity,
        "model": model,
        "definitions_digest": definitions_digest(),
    }
    return {"findings": findings, "summary": summary}
