"""
Unit tests for aop_completion_score.

Tests cover:
- The minimum event and KER counts, matching AOP-Wiki EMOD
- A complete AOP scoring 100
- References and point of contact being scored
- HTML with no visible text counting as empty, and an image alone as content

Examples:
    Run all tests::

        $ python -m pytest tests/test_aop_completion_score.py
"""

from aop_wiki_cli.parsers.completion_score import aop_completion_score

FREE_TEXT = [
    'title', 'short_name', 'abstract', 'authors', 'background',
    'overall_assessment_description', 'doa_free_text', 'ke_essentiality',
    'woe_evidence', 'quantitative_considerations', 'potential_applications',
    'references',
]


def make_aop(event_ids, kers):
    aop = {field: 'text' for field in FREE_TEXT}
    aop.update({
        'handbook_version': 2.0,
        'event_ids': event_ids,
        'kers': kers,
        'point_of_contact': 'A. Person',
        'stressors': ['1'],
        'sex_applicability': ['Male'],
        'life_stage_applicability': ['Adult'],
        'taxonomy_applicability': ['human'],
    })
    return aop


def test_minimal_aop_scores_full():
    """MIE -> KE -> AO: 3 events and 2 KERs earn both points."""
    score = aop_completion_score(make_aop(['1', '2', '3'], {'10': {}, '11': {}}))
    assert score['percent'] == 100
    assert score['max_score'] == 19
    assert score['empty_structured'] == []


def test_mie_to_ao_misses_both_points():
    """MIE -> AO: 2 events and 1 KER earn neither point."""
    score = aop_completion_score(make_aop(['1', '2'], {'10': {}}))
    assert score['raw_score'] == 17
    assert score['empty_structured'] == ['event_ids', 'kers']


def test_repeated_event_ids_count_once():
    """An event listed twice is still one event."""
    score = aop_completion_score(make_aop(['1', '2', '2'], {'10': {}, '11': {}}))
    assert score['empty_structured'] == ['event_ids']


def test_handbook_fields_listed_when_empty():
    """Handbook 2.5 fields are listed as empty when empty, for any handbook version."""
    for version in (2.0, 2.5):
        aop = make_aop(['1', '2', '3'], {'10': {}, '11': {}})
        aop.update({'handbook_version': version, 'development_strategy': '', 'known_modulating_factors': ' '})
        assert aop_completion_score(aop)['empty_free_text'] == ['development_strategy', 'known_modulating_factors']


def test_handbook_fields_scored_only_from_2_5():
    """Filled handbook 2.5 fields are never listed as empty, and only score from 2.5."""
    for version, max_score in ((2.0, 19), (2.5, 21)):
        aop = make_aop(['1', '2', '3'], {'10': {}, '11': {}})
        aop.update({'handbook_version': version, 'development_strategy': 'text',
                    'known_modulating_factors': 'text'})
        score = aop_completion_score(aop)
        assert score['empty_free_text'] == []
        assert (score['raw_score'], score['max_score']) == (max_score, max_score)


def test_references_and_point_of_contact_scored():
    """Missing references and point of contact each cost a point."""
    aop = make_aop(['1', '2', '3'], {'10': {}, '11': {}})
    aop.update({'references': '', 'point_of_contact': ''})
    score = aop_completion_score(aop)
    assert score['raw_score'] == 17
    assert 'references' in score['empty_free_text']
    assert 'point_of_contact' in score['empty_structured']


def test_html_without_text_is_empty():
    """'<p>&nbsp;</p>' is empty; an image alone is content."""
    aop = make_aop(['1', '2', '3'], {'10': {}, '11': {}})
    aop.update({'abstract': '<p>&nbsp;</p>\n<span></span>',
                'background': '<p><img alt="" src="data:image/png;base64,AAAA"></p>'})
    empty = aop_completion_score(aop)['empty_free_text']
    assert 'abstract' in empty
    assert 'background' not in empty


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
