"""AOP-Wiki database identifiers for values the XML export gives only by name.

The XML export names an Event's level of biological organization as text
(``Cellular``). The AOP-Wiki production database identifies the same level by
the integer primary key of its lookup table, which the export does not carry.
A record written for that database, or for a schema generated from it, needs
the integer, so it is recorded here once, where every downstream project can
read it.

The level ids were supplied by Ginnie Hench on 2026-10-03. The names are spelled
as the XML export spells them.
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
