"""Regression test: Pass 3 prompt must render existing-group members by title.

Previously `run_pass3` built its title lookup only from the ungrouped events,
so members of EXISTING GROUPS appeared in the prompt as bare IDs.

Run under pytest::

    python -m pytest tests/test_pass3_prompt_titles.py
"""

from __future__ import annotations

from types import SimpleNamespace

from aop_wiki_cli.annotation_scripts import collect_similar_events as cse


def test_pass3_prompt_includes_existing_group_member_titles(tmp_path, monkeypatch):
    captured: list[str] = []

    def fake_call(client, **kwargs):
        captured.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text='{"existing_group_assignments": [], "new_groups": []}')],
        )

    monkeypatch.setattr(cse, "_call_with_retry", fake_call)

    all_events = {
        "1": "Increased oxidative stress",
        "2": "Oxidative stress, increased",
        "3": "Decreased fertility",
    }
    final_groups = [{"group_key": "oxidative_stress", "member_ids": ["1", "2"], "rationale": "same"}]

    cse.run_pass3(
        client=None,
        ungrouped_events={"3": all_events["3"]},
        final_groups=final_groups,
        pass3_dir=str(tmp_path / "pass3"),
        pass3_cache_path=str(tmp_path / "pass3.json"),
        all_events=all_events,
    )

    assert len(captured) == 1
    prompt = captured[0]
    assert '"Increased oxidative stress"' in prompt
    assert '"Oxidative stress, increased"' in prompt
    assert "ID 3: Decreased fertility" in prompt
