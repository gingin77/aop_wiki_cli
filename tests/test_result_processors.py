"""
Tests for search/result_processors.py — post-search serialization, filtering
and priority sorting of result dicts.

All three functions are pure dict transforms; a tiny recording logger captures
the optional ``logger.info`` calls.

Run with::

    $ uv run pytest tests/test_result_processors.py
"""

from aop_wiki_cli.search import result_processors as rp


class RecordingLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(msg)


# ---------------------------------------------------------------------------
# serialize_search_results
# ---------------------------------------------------------------------------

def test_serialize_search_results_converts_sets_to_sorted_lists():
    results = {
        "1": {
            "snippets_by_field": {"title": {"b", "a"}},
            "terms_found": {"y", "x"},
            "matched_fields": {"title", "abstract"},
            "co_occurrences": {("b", "a")},
            "co_occurrence_fields": {"abstract", "title"},
        }
    }
    out = rp.serialize_search_results(results)
    assert out is results  # mutates in place and returns for chaining
    r = out["1"]
    assert r["snippets_by_field"]["title"] == ["a", "b"]
    assert r["terms_found"] == ["x", "y"]
    assert r["matched_fields"] == ["abstract", "title"]
    # inner pair order preserved; only the outer list sorted
    assert r["co_occurrences"] == [["b", "a"]]
    assert r["co_occurrence_fields"] == ["abstract", "title"]


def test_serialize_search_results_without_co_occurrence_fields():
    results = {
        "1": {
            "snippets_by_field": {},
            "terms_found": set(),
            "matched_fields": set(),
            "co_occurrences": set(),
        }
    }
    out = rp.serialize_search_results(results)
    assert "co_occurrence_fields" not in out["1"]
    assert out["1"]["terms_found"] == []


# ---------------------------------------------------------------------------
# filter_by_co_occurrence
# ---------------------------------------------------------------------------

def test_filter_by_co_occurrence_keeps_only_entities_with_pairs():
    results = {
        "1": {"co_occurrences": [["a", "b"]]},
        "2": {"co_occurrences": []},
    }
    logger = RecordingLogger()
    filtered = rp.filter_by_co_occurrence(results, "aops", logger=logger)
    assert set(filtered) == {"1"}
    assert logger.messages == ["Filtered to 1 aops with co-occurrence matches"]


def test_filter_by_co_occurrence_without_logger():
    results = {"1": {"co_occurrences": []}}
    filtered = rp.filter_by_co_occurrence(results, "events")
    assert filtered == {}


# ---------------------------------------------------------------------------
# sort_by_priority_field
# ---------------------------------------------------------------------------

def test_sort_by_priority_field_orders_priority_first_then_by_id():
    results = {
        "10": {"has_priority_co_occurrence": False},
        "2": {"has_priority_co_occurrence": True},
        "1": {"has_priority_co_occurrence": False},
    }
    logger = RecordingLogger()
    sorted_results, count = rp.sort_by_priority_field(results, "title", "aops", logger=logger)
    # priority entity first, then remaining sorted numerically by id
    assert list(sorted_results) == ["2", "1", "10"]
    assert count == 1
    assert logger.messages == [
        "Found 1 aops with co-occurrences in priority field 'title'"
    ]


def test_sort_by_priority_field_no_priority_matches_is_quiet():
    results = {"2": {}, "1": {}}
    logger = RecordingLogger()
    sorted_results, count = rp.sort_by_priority_field(results, "title", "aops", logger=logger)
    assert list(sorted_results) == ["1", "2"]
    assert count == 0
    assert logger.messages == []  # no log emitted when priority_count == 0
