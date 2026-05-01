Annotate domain of applicability (DOA) fields for an AOP-Wiki entity (KE, KER, or AOP).

## DOA fields

- taxonomy: species or taxonomic group the entity applies to
- life_stage: developmental or life stage (e.g. adult, juvenile, embryo)
- sex: biological sex applicability (e.g. male, female, mixed, not specified)

## Usage

Invoked with an entity type and ID as $ARGUMENTS (e.g. "ke 122", "ker 456", "aop 14").

## Steps

1. Read the entity's current annotation from the relevant store.
2. Extract DOA field values from the free-text description or existing cache fields.
3. Present extracted values to the user for confirmation.
4. Write confirmed values back to the store.

## Notes

- taxonomy_terms in the cache (ke field: taxonomy_terms) may already have structured values — check before extracting
- DOA fields apply equally to KEs, KERs, and AOPs; this skill is shared across all three entity types
