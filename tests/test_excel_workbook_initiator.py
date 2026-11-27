"""
Tests for data_export/excel_workbook_initiator.py — the orchestration that
harmonize-ker-evidence calls to build the harmonized-KER Excel workbooks.

The actual openpyxl writing (transform_outputs_for_excel) and the AOP collection
are monkeypatched, so the test exercises the orchestration logic — AOP→KER
mapping, the main workbook call, and the per-AOP workbook loop (including the
empty-AOP warning branch) — without generating real .xlsx files.

Run with::

    $ uv run pytest tests/test_excel_workbook_initiator.py
"""

from datetime import date
from types import SimpleNamespace

from aop_wiki_cli.data_export import excel_workbook_initiator as ewi


def test_initiate_workbook_creation_orchestrates_main_and_per_aop(tmp_path, monkeypatch):
    # AOP 1 has one KER; AOP 2 has none. build_aop_to_ker_mapping runs for real.
    monkeypatch.setattr(
        ewi, "collect_entity_with_cache",
        lambda *a, **k: {"1": {"kers": {"10": {}}}, "2": {"kers": {}}},
    )
    excel_calls = []
    monkeypatch.setattr(
        ewi, "transform_outputs_for_excel",
        lambda *args, **kwargs: excel_calls.append((args, kwargs)),
    )

    warnings = []
    logger = SimpleNamespace(info=lambda *a: None, warning=lambda m: warnings.append(m))

    harmonized = {"10": {"aop_ids": ["1"]}}
    # AOP "1" maps to KER 10 (present) -> workbook written; AOP "3" has no KERs -> warning
    ewi.initiate_workbook_creation_for_harmonized_kers(
        harmonized, date(2024, 1, 1), tmp_path, {"1": "desc", "3": "desc"}, logger, cache_dir=tmp_path,
    )

    # one main workbook + one AOP-specific workbook (AOP 1); AOP 3 produced only a warning
    assert len(excel_calls) == 2
    assert any("AOP 3" in w for w in warnings)


def test_create_aop_specific_workbook_warns_when_no_kers(tmp_path, monkeypatch):
    monkeypatch.setattr(ewi, "transform_outputs_for_excel", lambda *a, **k: None)
    warnings = []
    logger = SimpleNamespace(warning=lambda m: warnings.append(m))

    ewi.create_aop_specific_harmonized_ker_workbook(
        date(2024, 1, 1), harmonized_kers={}, aop_to_ker_dict={}, logger=logger,
        aop_id="99", output_dir=tmp_path,
    )
    assert any("AOP 99" in w for w in warnings)
