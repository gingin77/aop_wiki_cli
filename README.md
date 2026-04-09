# AOP Analytics

Tools for analyzing AOP-Wiki content derived from XML data. In future, this repo will also include tools for processing
AOP content from literature and other sources, which may be compared against the AOP-Wiki XML content.

## Overview

This repository provides Python functions and CLI commands for analyzing content from the [AOP-Wiki](https://aopwiki.org/)
XML data export. The tools extract Adverse Outcome Pathways (AOPs), Key Events (KEs), and Key Event Relationships (KERs)
from the XML, calculate completion metrics, and support various analytical workflows.

## Key Features

- **XML Data Collection**: Automated download and parsing of AOP-Wiki XML exports
- **Entity Extraction**: Extract AOPs, Key Events, and KERs with full metadata
- **Completion Scoring**: Automated calculation of data completeness metrics
- **Event Ranking**: Scoring system for prioritizing Key Events based on multiple criteria
- **Evidence Harmonization**: Tools for standardizing tabulated evidence across KERs
- **Text Search**: Search AOP-Wiki entities for specific terms and patterns
- **Reference Analysis**: Search and analyze citations in AOP-Wiki content
- **CLI Interface**: Command-line tools for common analysis workflows
- **Tests**: Current test suite is limited to specific needs

## Installation

```bash
# Optional: Drop dependencies dir
rm -rf .venv

# Install dependencies with uv
uv sync

# Run CLI with help flag to view available commands
uv run python cli.py --help
```

## CLI Commands

```bash
# Collect all events and calculate integration rankings
uv run python cli.py collect-event-integration-rankings

# Collect KER analytics
uv run python cli.py collect-ker-analytics

# Search KERs for concordance evidence
uv run python cli.py search-kers-for-concordance-text

# Harmonize KER evidence tables
uv run python cli.py harmonize-ker-evidence

# Search entities using a config file
uv run python cli.py search-with-config <config_name>

# Collect and harmonize seizure AOP data (interactive review)
uv run python cli.py collect-harmonized-seizure-aops
uv run python -m cli collect-harmonized-seizure-aops --date 02-20-2026

# Manually review match results from a JSON file
uv run python cli.py manually-review-matches <input_file.json> [--threshold 0.9]

# Concrete example - with future oriented date
uv run python cli.py manually-review-matches outputs/seizure_aops/03-14-2026/mapping_ke_description_to_harmonized_ke_03-14-2026.json --threshold 0.9

uv run python cli.py manually-review-matches outputs/seizure_aops/{date}/mapping_ke_description_to_harmonized_ke_{date}.json --threshold 0.9
```

## Seizure AOP Workflow

Use this workflow to generate seizure-specific outputs, then move the selected files to the target project input folder.

### Two-Stage Human Review Process

The seizure workflow includes interactive human review for quality control:

1. **Stage 1: KE Descriptions → Harmonized KEs** - Review fuzzy matches between Key Event
   descriptions from the source workbook and harmonized KE titles
2. **Stage 2: Target Families → Events** - Review fuzzy matches between target family labels
   and AOP-Wiki event titles

During each stage, you'll be prompted to accept (`y`), reject (`n`), or quit (`q`) each match
below the confidence threshold. Rejected matches allow you to suggest a better match.

### Seizure AOP Workflow-Specific Caching Behavior

The workflow checks for previously curated input files in `outputs_for_vc/`:

- **KE description mappings**: `outputs_for_vc/reviewed_ke_description_to_harmonized_ke_mapping.json`
- **Event-target family mappings**: `outputs_for_vc/curated_event-target_family_mappings.json`

If these files exist, they are loaded and the interactive review is skipped. These files must be
manually placed there after review (e.g., by copying from dated output folders).

To regenerate matches (bypass curated inputs), use `--skip-curated`.

### CLI Options

```bash
# Basic usage (uses cached curations if available)
uv run python cli.py collect-harmonized-seizure-aops

# Specify a cache date for AOP-Wiki data
uv run python cli.py collect-harmonized-seizure-aops --date MM-DD-YYYY

# Force refresh of AOP-Wiki XML data
uv run python cli.py collect-harmonized-seizure-aops --force-refresh

# Skip curated inputs and regenerate via fuzzy matching + review
uv run python cli.py collect-harmonized-seizure-aops --skip-curated
```

### Export to Target Project

```bash
# Preview file moves (recommended)
./export_ready_for_emod_upload.sh --date MM-DD-YYYY --output /path/to/target/inputs/seizure_aops --dry-run

# Execute file moves
./export_ready_for_emod_upload.sh --date MM-DD-YYYY --output /path/to/target/inputs/seizure_aops
```

### Output Files

Outputs are written to `outputs/seizure_aops/{date}/`:

| File | Description |
| ---- | ----------- |
| `harmonized_events_{date}.csv` | Harmonized key events ready for analysis |
| `harmonized_events_with_wiki_content_{date}.json` | Events enriched with AOP-Wiki metadata |
| `assays_{date}.csv` | Assay data mapped to events |
| `seizure_aop_events_{date}.xlsx` | Combined workbook with all seizure AOP data |
| `mapping_ke_description_to_harmonized_ke_{date}.json` | KE description to harmonized KE mappings |
| `post_analysis_event_to_assays_{date}.json` | Event-to-assay mappings via target families |
| `biological_target_families_{date}.json` | Target family definitions |
| `aop_to_harmonized_events_validation_{date}.json` | Validation results comparing with AOP-Wiki |

## Development

### Project Organization

- **Entry point**: `cli.py` provides the main CLI interface
- **Source code**: All production code is in `src/` organized by functional domain
- **Configuration**: Analysis configurations are in `configs/`
- **Tests**:
  - Unit and integration tests are in `tests/` at project root
  - One test has been created as a shell script at project root
- **Scripts**: Catch all space for "scripts"

### Testing

```bash
# Run tests on content search functions
uv run python -m tests.test_search_text_by_field

# Run a test that all CLI functions are running with standard params
bash test_cli_integration.sh

# Alt version - just view results, using grep
bash test_cli_integration.sh 2>&1 | grep -E "(Testing:|PASSED|FAILED|Test Summary)"
```

## Project Structure ()

```sh
aop_analytics/
├── cli.py                              # Main CLI entry point
├── pyproject.toml                      # Project dependencies
├── test_cli_integration.sh             # CLI integration tests
├── export_ready_for_emod_upload.sh     # Seizure output export script
│
├── src/                          # Source code modules
│   ├── analysis/                 # Post-extraction analytics
│   ├── collection/               # Needs refactoring 
│   ├── parsers/                  # Parser for the XML and other sources
│   ├── search/                   # Text and reference searching
│   ├── harmonization/            # KER Evidence table standardization
│   ├── data_export/              # File generation (CSV, Excel, JSON)
│   ├── visualization/            # Graphical outputs
│   ├── utilities/                # Shared helper functions
│   └── standalone/               # Needs refactoring 
│
├── configs/                      # Analysis configuration files
├── tests/                        # Unit and integration tests
├── docs/                         # Project documentation
│
├── inputs/                       # Input data
│   ├── seizure_aops/             # Seizure AOP workbook inputs
│   ├── annotated_manually/       # Manual annotations
│   └── from_emod_prototypes/     # From earlier EMOD prototypes
│
├── outputs/                      # Generated outputs (git-ignored)
│   ├── seizure_aops/             # Seizure workflow outputs
│   ├── event_rankings/           # Event ranking results
│   ├── ker_evidence/             # KER evidence data
│   ├── ker_analytics/            # KER analytics
│   └── cache/                    # Cached XML/JSON data
│
├── outputs_for_vc/               # Curated outputs for version control
│
├── xml_inputs/                   # Downloaded AOP-Wiki XML files
├── logs/                         # Log files
├── archived/                     # Deprecated scripts
└── scratch/                      # Experimental code
```

> To generate dir and sud-dir, structure run: `tree src -L 2 -I '__pycache__|*.pyc'`. If tree is not
> available, install on a mac with homebrew, `brew install tree`

## Module Reference

In the module list below, ✅ indicate that the module is a dependency of functions that are currently available through
the `CLI` tool.

### Analysis (`src/analysis/`)

Post-extraction analytics and statistical operations.

- ✅ **meta_data_helpers.py** - Ranking, filtering, averaging, and summary statistics functions
- ✅ **collect_event_rankings.py** - Workflow for collecting and ranking events
- ✅ **map_ke_descriptions_to_harmonized.py** - Fuzzy matching for KE descriptions, target
  family enrichment, assay-event mapping
- ✅ **analyze_seizure_aop_content.py** - Seizure AOP analysis and comparison with AOP-Wiki data
- ✅ **manual_match_review.py** - Interactive terminal-based review workflow for validating fuzzy matches

### Collection (`src/collection/`)

Data fetching and initial processing from AOP-Wiki.

- ✅ **get_aop_wiki_xml_data.py** - Download and validate XML exports
- **collect_aops_and_kers_from_events.py** - Collect related entities

### Parsers (`src/parsers/`)

XML parsing and entity extraction.

- ✅ **parse_aop_wiki_xml_data.py** - Main XML parsing and entity collection
- ✅ **xml_processing_helpers.py** - XML utilities and table extraction
- ✅ **completion_score.py** - Calculate data completeness scores for AOPs, KERs, and Events
- ✅ **aop_wiki_content_parsers.py** - Event title/content parsing helpers (e.g., `strip_event_titles`)
- **parse_references.py** - Citation extraction and structuring

### Search (`src/search/`)

Text and reference searching capabilities.

- ✅ **search_text_by_field.py** - Search entity text fields for terms
- **search_references.py** - Search citations with flexible matching
- **aop_wiki_xml_ref_search.py** - Reference search workflows

### Harmonization (`src/harmonization/`)

Evidence table standardization.

- ✅ **harmonize_tabulated_evidence.py** - Column header harmonization
- ✅ **helpers_for_ker_evidence_harmonization.py** - Caching wrapper

### Data Export (`src/data_export/`)

File generation in various formats.

- ✅ **csv_writer.py** - Generic CSV export with field configurations
- ✅ **field_definitions.py** - Field configuration objects
- ✅ **transformers.py** - Data transformation functions
- ✅ **excel_workbook_initiator.py** - Excel workbook orchestration
- ✅ **export_harmonized_kers_to_excel.py** - KER evidence Excel exports
- **export_reference_search_results.py** - Reference search result exports

### Utilities (`src/utilities/`)

Shared helper functions.

- ✅ **helpers.py** - File I/O, logging, caching, downloads, URL generation
- **html_to_csv_converter.py** - HTML table conversion

### Visualization (`src/visualization/`)

Graphical output generation.

- **visualize_aop_as_box_diagram.py** - PDF diagram generation for AOPs
- **traversal_helpers.py** - Graph traversal utilities

## Debugging

## License

[TODO: Add license information]
