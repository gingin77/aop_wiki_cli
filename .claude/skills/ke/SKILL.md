---
name: ke
description: |
  Skills for annotating AOP-Wiki Key Events (KEs). KEs are the most atomic
  and reusable entity in the AOP-Wiki data model.

  Sub-skills:
  - annotate-structured-ke-fields: Apply bio-ontology annotation to KE-specific structured fields, 
  including level of biological_organization, cell_term, organ_term, and event components, action,
  object, process and phenotype.
  - annotate-assays: extract and annotate measurement methods from the measurement_method field
  - compare: compare KE annotations against the AOP-Wiki cache and report divergences
  - review: identify and resolve KEs flagged needs_review

  Script: scripts/annotate_ke.py
  Store:  outputs_for_vc/annotations/ke_annotations.json
---
