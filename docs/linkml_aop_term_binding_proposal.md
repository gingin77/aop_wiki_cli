# Proposal: machine-checkable ontology-term bindings in linkml-aop

**Audience:** linkml-aop maintainers (EHS-Data-Standards/linkml-aop).
**Context:** aop_wiki_cli now produces LLM-assisted ontology annotations for Key
Events (cell/organ/cellular-component terms, per-event-component
object/process/phenotype terms, assay terms). A prototype validator
(`aop_wiki_cli/src/aop_wiki_cli/annotation_scripts/validate_annotations.py`)
checks these against OAK, but the rules it enforces live in that script. This
proposal moves them into the linkml-aop schema, where `linkml-term-validator`
can enforce them for every producer — the same stack the Monarch dismech
knowledge base uses (LinkML dynamic enums + `reachable_from` roots, validated
by `linkml-term-validator` over an OAK adapter config).

## What the schema says today

In `aop_emod_linkml.yaml`, the term-bearing classes (`CellTerm`, `OrganTerm`,
`BiologicalObject`, `BiologicalProcess`, `TaxonTerm`) carry:

- `term` — a free string (the label);
- `source` — an enum of ontology *names* (`BiologicalObjectSourceEnum`:
  GO/CHEBI/CL/PR/UBERON/…), i.e. provenance only;
- `source_id` — a free string holding the ontology identifier.

Nothing constrains `source_id` to be a real identifier, to resolve in the named
ontology, to carry the canonical label in `term`, or to fall inside the branch
the field means (a GO molecular-function term is currently as valid a
"biological process" as a GO:0008150 descendant). Every check has to be
re-implemented by each consumer.

## Proposed changes

Because `aop_emod_linkml.yaml` is generated, these are changes to the curation
pipeline (`scripts/curate_emod_linkml.py` +
`curation_helpers/aop_definitions_and_enums.py`), not to the YAML by hand.

### 1. Ontology prefixes in the schema header

Add the OBO prefix expansions to `SCHEMA_HEADER` so CURIEs in data resolve:

```yaml
prefixes:
  GO: http://purl.obolibrary.org/obo/GO_
  CL: http://purl.obolibrary.org/obo/CL_
  UBERON: http://purl.obolibrary.org/obo/UBERON_
  CHEBI: http://purl.obolibrary.org/obo/CHEBI_
  PR: http://purl.obolibrary.org/obo/PR_
  HP: http://purl.obolibrary.org/obo/HP_
  MP: http://purl.obolibrary.org/obo/MP_
  UPHENO: http://purl.obolibrary.org/obo/UPHENO_
  OBI: http://purl.obolibrary.org/obo/OBI_
  BAO: http://www.bioassayontology.org/bao#BAO_
  NCBITaxon: http://purl.obolibrary.org/obo/NCBITaxon_
```

### 2. Type `source_id` as `uriorcurie`

On each term class, `source_id` should range over `uriorcurie` rather than the
default string. Encoding: an entry per class in `CURATED_RANGES` (or a small
new constant, e.g. `CURATED_SOURCE_ID_RANGES`, applied in the same grafting
pass).

### 3. Dynamic enums with `reachable_from` roots

Add branch-constrained enums for each term kind. These are the heart of the
proposal — they make "a biological process is a GO:0008150 descendant" a
schema fact instead of prose:

```yaml
enums:
  BiologicalProcessTermEnum:
    description: Any GO biological_process descendant
    reachable_from:
      source_nodes: [GO:0008150]
      is_direct: false
      relationship_types: [rdfs:subClassOf]
  CellularComponentTermEnum:
    reachable_from:
      source_nodes: [GO:0005575]
      is_direct: false
      relationship_types: [rdfs:subClassOf]
  CellTypeTermEnum:
    reachable_from:
      source_nodes: [CL:0000000]
      is_direct: false
      relationship_types: [rdfs:subClassOf]
  AnatomicalEntityTermEnum:
    reachable_from:
      source_nodes: [UBERON:0001062]
      is_direct: false
      relationship_types: [rdfs:subClassOf]
  PhenotypeTermEnum:
    reachable_from:
      source_nodes: [HP:0000118, MP:0000001, UPHENO:0001001]
      is_direct: false
      relationship_types: [rdfs:subClassOf]
  AssayTermEnum:
    reachable_from:
      source_nodes: [OBI:0000070, BAO:0000015]
      is_direct: false
      relationship_types: [rdfs:subClassOf]
  BiologicalObjectTermEnum:
    # heterogeneous by design: cells, anatomy, chemicals, proteins, genes
    reachable_from:
      source_nodes: [CL:0000000, UBERON:0001062, CHEBI:24431, PR:000000001]
      is_direct: false
      relationship_types: [rdfs:subClassOf]
```

Encoding: `ENUM_DEFINITIONS` currently holds flat value lists/dicts and
`build_enums_yaml()` emits only `permissible_values`. Add a parallel
`DYNAMIC_ENUM_DEFINITIONS` constant whose entries carry a `reachable_from`
mapping, and a branch in `build_enums_yaml()` that emits it. Example shape:

```python
DYNAMIC_ENUM_DEFINITIONS = {
    "biological_process_term_enum": {
        "description": "Any GO biological_process descendant",
        "source_nodes": ["GO:0008150"],
    },
    ...
}
```

### 4. Bind `source_id` to the enums

LinkML `bindings` attach a value constraint to a slot without changing its
range — exactly what dismech validates recursively with
`linkml-term-validator`. On each term class:

```yaml
  BiologicalProcess:
    attributes:
      source_id:
        range: uriorcurie
        bindings:
          - binds_value_of: id
            range: BiologicalProcessTermEnum
            obligation_level: RECOMMENDED
```

`RECOMMENDED` rather than `REQUIRED` at first: AOP-Wiki legacy data contains
off-branch and non-OBO identifiers (FMA, MESH, free text), and a required
binding would make the whole historical corpus invalid. Producers that want
strictness (such as aop_wiki_cli's pipeline) can treat the recommendation as
an error locally. Encoding: a `CLASS_TO_BINDING` constant beside
`CLASS_TO_ENUM`, e.g.
`{"BiologicalProcesses": ("source_id", "BiologicalProcessTermEnum"), ...}`,
applied in the same per-class curation pass.

### 5. Validation workflow (no schema change)

Ship an OAK adapter config and a target, mirroring dismech:

```yaml
# conf/oak_config.yaml
prefix_to_adapter:
  GO: sqlite:obo:go
  CL: sqlite:obo:cl
  UBERON: sqlite:obo:uberon
  CHEBI: sqlite:obo:chebi
  PR: sqlite:obo:pr
  HP: sqlite:obo:hp
  MP: sqlite:obo:mp
  OBI: sqlite:obo:obi
```

```
uv run linkml-term-validator validate-schema src/linkml_aop/schema/aop_emod_linkml.yaml -c conf/oak_config.yaml
uv run linkml-term-validator validate-data <instances> -s <schema> -c conf/oak_config.yaml
```

### 6. Discussion point: phenotype and cellular component on EventComponent

`EventComponent` today holds action/object/process. The aop_wiki_cli
annotations also capture a **phenotype** per event component and a
**cellular_component** per event (the `Observation` class already has a
`phenotype` attribute, so the concept exists in the model). If EMOD intends to
ingest these annotations, `EventComponent` would need an optional
`phenotype_id` (bound to `PhenotypeTermEnum`) and `Event` an optional
`cellular_component_id` (bound to `CellularComponentTermEnum`). This is a
modeling decision for EMOD rather than a validation mechanism, so it is listed
separately.

## Known caveats

- **HGNC** does not resolve through OAK sqlite builds, and OLS resolves the
  uppercase prefix to unrelated terms (dismech documents the same limitation
  and verifies gene CURIEs manually). Leave gene identifiers outside the
  bindings, or bind them with a pattern constraint only.
- **BAO** is not an OBO ontology; its sqlite build availability should be
  confirmed before including `BAO:0000015` in `AssayTermEnum`'s roots.
- Dynamic-enum validation needs the ontology closures; `linkml-term-validator`
  materializes/caches enum membership, and the first run downloads the SQLite
  ontology builds (GO and CHEBI are large, NCBITaxon very large — taxon
  bindings may be better left as existence checks only).

## Relationship to the aop_wiki_cli prototype

`validate_annotations.py` implements checks equivalent to §3/§4 today
(existence, canonical-label drift, prefix scope, ancestor closure) with the
field→root table hard-coded. Once the schema carries the bindings, that table
should be derived from (or replaced by) the schema, and the prototype retired
in favor of `linkml-term-validator`.
