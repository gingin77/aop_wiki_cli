# Seizure AOP Analysis

The seizure use case leverages AOP curation work already performed and published by Behl, et al.

## Behl et al Curation Workflow 

Collect 7 Seizure AOPs  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;↓  
Review X# KEs from those AOPs  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;↓  
Define a set of X# Harmonized KEs for redefined AOPs  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;↓  
Redefine 5 Seizure AOPs by merging 2 pairs of the original 7 AOPs into 1 (shown in fig 3)

## Harmonization Process

The supplemental data from Behl et al was extracted and analyzed using the `collect_harmonized_seizure_aops` CLI function.

| Worksheet name | DF name in code | Output |
|-----------|-----------|--------|
| Suppl2_KEs AOP Harmonization  | harmonized   | - harmonized KE list<br> - orginal KE to harmonized KE mappings<br>  - harmonized KE to AOP mappings<br> - harmonized KE to target family mappings    |
| Suppl6_ICE Assays  |  assays        | - biological target families list<br> - assays list<br> - assays to target families mappings<br> - biological target family to KE description mappings     |

### Additional Curations Needed

| Goal | Transformation Comments | Source Files |
|-----------|-----------|--------|
| Showcase relationships between Assays::KEs & possiblty Assays::AOPs | 1) Available by combining harmonization worksheet, KEs to biological target families with assay worksheet biological target families to assay <br><br> 2) Via KE descriptions in the assays worksheet | 1) Mappings from each sheet should be in `dict` format, but a json path is needed for export.<br><br><br> 2) ✅ Mapings between KE descriptions and the harmonized KEs |
| Demonstrate merging of original Wiki content into Harmonized content | ✅  orginal KE to harmonized KE mappings<br> ✅ orginal AOPs to harmonized AOP mappings | EMOD data model needs a convention for tracking provenance from "old" to "new" content<br> - I need a `dict` defining the old to new AOPs

> As of 2/20/26, the content `dict` returned by the seizure parser and the export functions have been refactored to
> improve ease of tracking content variables to data export file paths.

## EMOD Import Path Map

### Source + run command

- Source workbook: `inputs/seizure_aops/behl_seizure_supp_data.xlsx`
- Output directory: `outputs/seizure_aops/<MM-DD-YYYY>/`
- Run: `uv run python -m cli collect-harmonized-seizure-aops`

### Canonical JSON outputs for EMOD imports

Typical path to export:
`outputs/seizure_aops/<MM-DD-YYYY>/biological_target_families_<MM-DD-YYYY>.json`

### Manual curation output

A manually curated JSON file, representing harmonized seizure AOPs is available at:
[outputs_for_vc/manually_curated_seizure_aops.json](../outputs_for_vc/manually_curated_seizure_aops.json). This file was
manually curated based upon information illustrated in a figure in the Behl manuscript. The
 amount of content is brief and was easy to assemble manually.

## Key Modules Added

| Module | Purpose |
|--------|---------|
| `src/parsers/parse_behl_seizure_aop_workbook.py` | Parses Behl Excel workbook, extracts harmonized KEs, assay mappings, and target families |
| `src/analysis/map_ke_descriptions_to_harmonized.py` | Fuzzy matching to map KE descriptions from assays to harmonized KE titles |
| `src/analysis/analyze_seizure_aop_content.py` | Analyzes seizure AOPs against AOP-Wiki XML data |
| `src/data_export/seizure_aop_export.py` | Export functions for seizure AOP results (JSON, CSV, Excel) |
| `src/data_export/excel_writer.py` | Excel workbook generation |
| `export_ready_for_emod_upload.sh` | Shell script to migrate seizure files to external directory for EMOD upload |

## Validation Features

The parser includes validation checks that print warnings/success messages:

- **Duplicate harmonized title check**: Alerts when multiple original events map to the same harmonized event title
- **MIE title verification**: Confirms expected MIE titles exist in harmonized AOPs
- **Event count comparison**: Validates that paired AOPs have matching event counts
- **AEID uniqueness check**: Verifies each AEID maps to a single assay and target family

## Completed Work

- ✅ Created seizure workbook parser (`parse_behl_seizure_aop_workbook.py`)
- ✅ Added assay DF parser with AEID-based mappings
- ✅ Implemented fuzzy matching for KE descriptions → harmonized KEs
- ✅ Added validation for incomplete harmonized event mappings
- ✅ Created functions to extract and validate harmonized AOPs
- ✅ Built Excel workbook export functionality
- ✅ Created shell script for migrating files to external directory (`export_ready_for_emod_upload.sh`)
- ✅ Centralized cache directory for XML-derived data
- ✅ Created manually curated seizure AOPs JSON

## Current TODO inventory

- `cli.py`: compare assay metadata to Comptox data (`collect_harmonized_seizure_aops` flow)
- `src/analysis/analyze_seizure_aop_content.py`: add fuzzy title similarity scoring/reporting
