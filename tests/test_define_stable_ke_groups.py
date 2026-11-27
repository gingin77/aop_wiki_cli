"""Tests for define_stable_ke_groups: the stable/unstable/attention split and
the single-workbook output (three sheets replacing the former three CSVs).

Run directly:    python -m tests.test_define_stable_ke_groups
Under pytest:    python -m pytest tests/test_define_stable_ke_groups.py
"""

from __future__ import annotations

from openpyxl import load_workbook

from aop_wiki_cli.annotation_scripts.define_stable_ke_groups import (
    define_stable_groups,
    write_workbook,
)


def _run(groups, ungrouped=()):
    return {
        "groups": [
            {"key": k, "type": t, "member_ids": frozenset(ids),
             "titles": {i: f"title {i}" for i in ids},
             "rationale": f"r-{k}", "shared_aop_check": {}}
            for k, t, ids in groups
        ],
        "ungrouped": set(ungrouped),
    }


def _two_runs():
    run1 = _run([
        ("g1", "merge", ["1", "2"]),            # stable (same set in both)
        ("g2", "merge", ["3", "4"]),            # unstable: run2 words it as 3,4,5
        ("s1", "soda", ["8", "9"]),             # other type: ignored for merge
    ])
    run2 = _run([
        ("h1", "merge", ["1", "2"]),
        ("h2", "merge", ["3", "4", "5"]),
    ], ungrouped=["9"])
    return {"runA": run1, "runB": run2}


def test_stable_unstable_attention_split():
    result = define_stable_groups(_two_runs(), "merge")
    assert [r["set_id"] for r in result["stable_groups"]] == ["1+2"]
    assert {r["set_id"] for r in result["unstable_groups"]} == {"3+4", "3+4+5"}
    attention = {a["event_id"]: a for a in result["attention_events"]}
    # 3 and 4 are merged in both runs but with differing membership; 5 only in runB.
    assert attention["3"]["reason"] == "membership_differs"
    assert attention["5"]["reason"] == "not_in_every_run"
    assert set(attention) == {"3", "4", "5"}
    s = result["summary"]
    assert (s["stable_groups"], s["unstable_groups"], s["attention_events"]) == (1, 2, 3)


def test_workbook_has_three_sheets_with_the_section_rows(tmp_path):
    result = define_stable_groups(_two_runs(), "merge")
    path = write_workbook(result, tmp_path)
    assert path.name == "merge_stable_groups.xlsx"
    wb = load_workbook(path)
    assert wb.sheetnames == ["stable_groups", "unstable_groups", "attention_events"]

    stable = wb["stable_groups"]
    assert [c.value for c in stable[1]][:4] == ["set_id", "size", "events", "shared_aop_check"]
    assert stable["A2"].value == "1+2"
    assert "1: title 1" in stable["C2"].value  # stacked multi-line titles

    attention = wb["attention_events"]
    header = [c.value for c in attention[1]]
    assert header == ["event_id", "title", "reason", "runA", "runB"]
    rows = {r[0].value: [c.value for c in r] for r in attention.iter_rows(min_row=2)}
    assert rows["5"][2] == "not_in_every_run"
    # Per-run cells describe what each run did with the event.
    assert "merge:h2" in rows["5"][4]
    assert rows["5"][3] == "not_in_run"


if __name__ == "__main__":
    import pathlib
    import tempfile
    test_stable_unstable_attention_split()
    with tempfile.TemporaryDirectory() as td:
        test_workbook_has_three_sheets_with_the_section_rows(pathlib.Path(td))
    print("ALL TESTS PASSED ✓")
