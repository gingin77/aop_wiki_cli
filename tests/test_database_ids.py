"""
Tests for database_ids.py — the AOP-Wiki database identifier lookup tables.

Pure data: the forward (id -> name) and inverse (name -> id) maps must stay in
sync, and the documented values (including the biological-action ids that
differ from the XML export's <source-id>) must hold.

Run with::

    $ uv run pytest tests/test_database_ids.py
"""

from aop_wiki_cli import database_ids as db


def test_level_maps_are_inverses():
    assert db.LEVEL_OF_BIOLOGICAL_ORGANIZATION_IDS == {
        name: lid for lid, name in db.LEVEL_OF_BIOLOGICAL_ORGANIZATION_BY_ID.items()
    }
    assert db.LEVEL_OF_BIOLOGICAL_ORGANIZATION_BY_ID[2] == "Cellular"
    assert db.LEVEL_OF_BIOLOGICAL_ORGANIZATION_IDS["Tissue"] == 3


def test_biological_action_maps_are_inverses():
    assert db.BIOLOGICAL_ACTION_IDS == {
        name: aid for aid, name in db.BIOLOGICAL_ACTION_BY_ID.items()
    }


def test_biological_action_ids_are_the_database_values_not_source_ids():
    # The module docstring warns these differ from the XML export's <source-id>
    # (which numbers occurrence 3 and functional change 7).
    assert db.BIOLOGICAL_ACTION_IDS["occurrence"] == 6
    assert db.BIOLOGICAL_ACTION_IDS["functional change"] == 3
