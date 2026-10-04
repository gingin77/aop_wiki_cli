"""AOP-Wiki database identifiers for values the XML export gives only by name.

The XML export names an Event's level of biological organization as text
(``Cellular``). The AOP-Wiki production database identifies the same level by
the integer primary key of its lookup table, which the export does not carry.
A record written for that database, or for a schema generated from it, needs
the integer, so it is recorded here once, where every downstream project can
read it.

The level and biological action ids were supplied by Ginnie Hench on
2026-10-03. The names are spelled as the XML export spells them.

The XML export also gives each biological action a ``<source-id>`` whose
``<source>`` is ``WIKI``. That number is not the database id: the export numbers
``occurrence`` 3 and ``functional change`` 7, where the database has them as 6
and 3. Take a biological action's id from the table below, never from the
export's ``<source-id>``.
"""

# Level of biological organization: database id -> name.
LEVEL_OF_BIOLOGICAL_ORGANIZATION_BY_ID = {
    1: "Molecular",
    2: "Cellular",
    3: "Tissue",
    4: "Organ",
    5: "Individual",
    6: "Population",
}

# The same table read the other way: name -> database id.
LEVEL_OF_BIOLOGICAL_ORGANIZATION_IDS = {
    name: level_id for level_id, name in LEVEL_OF_BIOLOGICAL_ORGANIZATION_BY_ID.items()
}

# Biological action: database id -> name. Not the XML export's <source-id>.
BIOLOGICAL_ACTION_BY_ID = {
    1: "increased",
    2: "decreased",
    3: "functional change",
    4: "abnormal",
    5: "pathological",
    6: "occurrence",
    7: "disrupted",
    8: "morphological change",
    9: "arrested",
    10: "delayed",
    11: "premature",
}

# The same table read the other way: name -> database id.
BIOLOGICAL_ACTION_IDS = {
    name: action_id for action_id, name in BIOLOGICAL_ACTION_BY_ID.items()
}
