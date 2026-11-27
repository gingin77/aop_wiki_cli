"""
Tests for harmonization/helpers_for_ker_evidence_harmonization.py — the thin
caching wrapper around ``harmonize_evidence_headers``.

Driven against ``tmp_path`` so the real ``generic_cache_wrapper`` exercises both
the miss (harmonize + write) and hit (load cached) paths.

Run with::

    $ uv run pytest tests/test_helpers_for_ker_evidence_harmonization.py
"""

import json
from datetime import date

from aop_wiki_cli.harmonization.helpers_for_ker_evidence_harmonization import (
    harmonize_kers_with_cache,
)

KERS_WITH_TABLES = {
    "10": {
        "upstream_ke": {"id": "1", "title": "Oxidative stress"},
        "downstream_ke": {"id": "2", "title": "Cell death"},
        "aop_ids": ["100"],
        "weight_of_evidence": {
            "headers": ["ke up", "ke down", "ref"],
            "tables": {"t1": [{"ke up": "A", "ke down": "B", "ref": "R"}]},
        },
    }
}


def test_harmonize_kers_with_cache_miss_harmonizes_and_writes(tmp_path):
    result = harmonize_kers_with_cache(KERS_WITH_TABLES, date(2024, 1, 1), tmp_path)
    assert "summary" in result
    assert result["summary"]["harmonizable_kers"] == ["10"]
    # cache file written with the dated key
    assert (tmp_path / "kers_with_harmonized_evi_tables_01-01-2024.json").exists()


def test_harmonize_kers_with_cache_hit_returns_cached(tmp_path):
    cached = {"summary": {"sentinel": True}}
    (tmp_path / "kers_with_harmonized_evi_tables_01-01-2024.json").write_text(json.dumps(cached))
    # force_refresh defaults to False → the cached file is returned, not recomputed
    result = harmonize_kers_with_cache({}, date(2024, 1, 1), tmp_path)
    assert result == cached


def test_harmonize_kers_with_cache_force_refresh_recomputes(tmp_path):
    (tmp_path / "kers_with_harmonized_evi_tables_01-01-2024.json").write_text('{"summary": {"sentinel": true}}')
    result = harmonize_kers_with_cache(KERS_WITH_TABLES, date(2024, 1, 1), tmp_path, force_refresh=True)
    assert "sentinel" not in result["summary"]
    assert result["summary"]["harmonizable_kers"] == ["10"]
