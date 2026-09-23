"""
Tests for event_level_llm_review.

No network access: every test injects a fake client that records the request it
was given and returns a canned response, so what is asserted is the prompt this
module builds and how it reads a verdict back. Whether the model answers well is
not something a unit test can decide.

Run with::

    $ uv run pytest tests/test_event_level_llm_review.py
"""

import json
from pathlib import Path

import pytest

from aop_wiki_cli.analysis.event_level_llm_review import (
    CHECK,
    DEFAULT_MODEL,
    build_system_prompt,
    definitions_digest,
    level_definitions,
    review_event,
    review_events,
)

FIXTURE = Path(__file__).parent / "mock_data" / "alignment_events_09-03-2026.json"


class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, payload):
        self.content = [FakeBlock(json.dumps(payload))]


class FakeMessages:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


class FakeClient:
    """Stands in for anthropic.Anthropic."""

    def __init__(self, payload=None, error=None):
        self.messages = FakeMessages(payload or {}, error)


def verdict(fits=True, best="Molecular", spans=False, quotes=None, reasoning="Because.", confidence="high"):
    return {
        "assigned_level_fits": fits,
        "best_fit_level": best,
        "spans_multiple_levels": spans,
        "quoted_evidence": quotes or ["a quote"],
        "reasoning": reasoning,
        "confidence": confidence,
    }


@pytest.fixture(scope="module")
def events():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- the prompt ------------------------------------------------------------

def test_system_prompt_carries_every_schema_definition():
    """The definitions are the criterion, so all six must reach the model."""
    prompt = build_system_prompt()
    for level, definition in level_definitions().items():
        assert level in prompt
        assert definition[:60] in prompt


def test_system_prompt_states_the_handbook_rules():
    prompt = build_system_prompt()
    assert "single level" in prompt
    assert "not the level at which it is *measured*" in prompt.replace("\n", " ")


def test_request_carries_the_event_and_a_json_schema(events):
    client = FakeClient(verdict())
    review_event("1909", events["1909"], client=client)
    call = client.messages.calls[0]
    assert call["model"] == DEFAULT_MODEL
    assert call["output_config"]["format"]["type"] == "json_schema"
    user = call["messages"][0]["content"]
    assert "Key Event 1909" in user
    assert "Assigned level: Individual" in user
    assert "tracheal mucus movement" in user


def test_description_html_is_stripped_before_sending(events):
    client = FakeClient(verdict())
    review_event("1250", events["1250"], client=client)
    user = client.messages.calls[0]["messages"][0]["content"]
    assert "<p" not in user and "&nbsp;" not in user


def test_long_description_is_truncated_and_recorded(events):
    client = FakeClient(verdict(fits=False, best="Tissue"))
    finding = review_event("1908", events["1908"], client=client, description_limit=200)
    assert finding["description_truncated"] is True
    assert len(client.messages.calls[0]["messages"][0]["content"]) < 700


# --- reading the verdict ---------------------------------------------------

def test_agreement_returns_no_finding(events):
    assert review_event("1908", events["1908"], client=FakeClient(verdict())) is None


def test_disagreement_is_a_flag_naming_both_levels(events):
    client = FakeClient(verdict(fits=False, best="Organ", reasoning="It is about airways."))
    finding = review_event("1909", events["1909"], client=client)
    assert finding["severity"] == "flag"
    assert finding["check"] == CHECK
    assert finding["assigned_level"] == "Individual"
    assert finding["best_fit_level"] == "Organ"
    assert "Organ-level change" in finding["message"]
    assert "It is about airways." in finding["message"]


def test_cannot_tell_is_a_note_not_a_flag(events):
    client = FakeClient(verdict(fits=False, best="cannot tell"))
    finding = review_event("1909", events["1909"], client=client)
    assert finding["severity"] == "note"


def test_spanning_two_levels_is_flagged_even_when_the_level_fits(events):
    """The Handbook rule: a Key Event sits within one level."""
    client = FakeClient(verdict(fits=True, spans=True))
    finding = review_event("1908", events["1908"], client=client)
    assert finding["severity"] == "flag"
    assert "spanning more than one level" in finding["message"]


# --- provenance and skipping ----------------------------------------------

def test_findings_record_model_and_definitions(events):
    client = FakeClient(verdict(fits=False, best="Organ"))
    finding = review_event("1909", events["1909"], client=client)
    assert finding["model"] == DEFAULT_MODEL
    assert finding["definitions_digest"] == definitions_digest()
    assert finding["reviewed_at"].endswith("+00:00")


def test_definitions_digest_changes_with_the_definitions(monkeypatch):
    first = definitions_digest()
    monkeypatch.setattr(
        "aop_wiki_cli.analysis.event_level_llm_review.level_definitions",
        lambda: {"Molecular": "something else"},
    )
    assert definitions_digest() != first


def test_an_event_without_a_description_is_never_sent():
    client = FakeClient(verdict())
    finding = review_event("x", {"level_of_biological_organization": "Cellular", "description": None},
                           client=client)
    assert finding["severity"] == "unchecked"
    assert finding["model"] is None
    assert client.messages.calls == []


def test_an_event_without_a_level_is_never_sent():
    client = FakeClient(verdict())
    finding = review_event("x", {"description": "<p>Some real text about cells.</p>"}, client=client)
    assert finding["severity"] == "unchecked"
    assert client.messages.calls == []


# --- the batch entry point -------------------------------------------------

def test_review_events_summarises(events):
    client = FakeClient(verdict(fits=False, best="Organ"))
    result = review_events(events, ke_ids=["1908", "1909", "1250", "999999"], client=client)
    summary = result["summary"]
    assert summary["events_read"] == 3
    assert summary["events_not_found"] == ["999999"]
    assert summary["events_with_flags"] == 3
    assert summary["model"] == DEFAULT_MODEL
    assert summary["request_errors"] == 0


def test_review_events_counts_agreement_without_findings(events):
    result = review_events(events, ke_ids=["1908", "1909"], client=FakeClient(verdict()))
    assert result["findings"] == []
    assert result["summary"]["events_model_agreed"] == 2


def test_a_failed_request_is_recorded_not_raised(events):
    client = FakeClient(error=RuntimeError("no credentials"))
    result = review_events(events, ke_ids=["1909"], client=client)
    assert result["summary"]["request_errors"] == 1
    assert result["findings"][0]["severity"] == "error"
    assert "no credentials" in result["findings"][0]["message"]


def test_raise_mode_propagates(events):
    client = FakeClient(error=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        review_events(events, ke_ids=["1909"], client=client, on_error="raise")
