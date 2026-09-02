# AOP-Wiki CLI

Tools for analyzing AOP-Wiki content derived from XML data along with scripts to process AOP content
from literature sources.

## Overview

This repository provides Python functions and CLI commands for analyzing content from the [AOP-Wiki](https://aopwiki.org/)
XML data export. The CLI functions extract Adverse Outcome Pathways (AOPs), Key Events (KEs), and Key Event Relationships
(KERs) from the XML, calculate completion metrics, and support various analytical workflows.

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

### As a tool (no clone needed)

```bash
# Run without installing
uvx --from git+https://github.com/gingin77/aop_wiki_cli aop-wiki-cli --help

# Or install the `aop-wiki-cli` command onto your PATH
uv tool install git+https://github.com/gingin77/aop_wiki_cli
pip install git+https://github.com/gingin77/aop_wiki_cli   # equivalent with pip
```

### From a clone (development)

```bash
# Optional: Drop dependencies dir
rm -rf .venv

# Install dependencies (and the project itself) with uv
uv sync

# Run CLI with help flag to view available commands
uv run aop-wiki-cli --help
```

## Where files are read and written

Every input, output, cache and log path is resolved against a single **data
directory**, chosen in this order:

1. `--data-dir <path>`, a global option that comes before the command name
2. the `AOP_WIKI_CLI_DATA_DIR` environment variable
3. the current working directory (the default)

Under that directory the tool uses `outputs/`, `outputs/cache/`, `xml_inputs/`,
`logs/`, and looks in `inputs/` and `curated/` for files you supply yourself.

```bash
# Write everything under ~/aop-work instead of the current directory
aop-wiki-cli --data-dir ~/aop-work collect-event-integration-rankings

# Same thing via the environment
export AOP_WIKI_CLI_DATA_DIR=~/aop-work
aop-wiki-cli collect-event-integration-rankings
```

The seizure workbook and the curated review files ship inside the package, so
the commands that need them work from any directory. To use your own copies,
place them at `<data-dir>/inputs/seizure_aops/behl_seizure_supp_data.xlsx` and
`<data-dir>/curated/<filename>.json`; those take precedence over the shipped ones.

## CLI Commands

Installed, the command is `aop-wiki-cli`. From a clone, prefix it with
`uv run` (`uv run aop-wiki-cli …`) or use `uv run python -m aop_wiki_cli …`.

```bash
# Collect all events and calculate integration rankings
aop-wiki-cli collect-event-integration-rankings

# Collect KER analytics
aop-wiki-cli collect-ker-analytics

# Find the KERs a key event participates in
aop-wiki-cli find-kers-for-events --ke-ids 1346

# Search KERs for concordance evidence
aop-wiki-cli search-kers-for-concordance-text

# Harmonize KER evidence tables
aop-wiki-cli harmonize-ker-evidence

# Search entities using a config file
aop-wiki-cli search-with-config <config_name>

# Collect and harmonize seizure AOP data (interactive review)
aop-wiki-cli collect-harmonized-seizure-aops
aop-wiki-cli collect-harmonized-seizure-aops --date 02-20-2026

# Manually review match results from a JSON file
aop-wiki-cli manually-review-matches <input_file.json> [--threshold 0.9]

# Concrete example - with future oriented date
aop-wiki-cli manually-review-matches outputs/seizure_aops/03-14-2026/mapping_ke_description_to_harmonized_ke_03-14-2026.json --threshold 0.9
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

The workflow uses two curated input files:

- **KE description mappings**: `reviewed_ke_description_to_harmonized_ke_mapping.json`
- **Event-target family mappings**: `curated_event-target_family_mappings.json`

Both ship with the tool (`src/aop_wiki_cli/data/curated/`). A copy placed at
`<data-dir>/curated/<filename>` overrides the shipped one, which is how a fresh
round of review is adopted: copy the reviewed file out of the dated output
folder into `<data-dir>/curated/` (and into `src/aop_wiki_cli/data/curated/` to
ship it). Whenever a curated file is found, interactive review is skipped.

To regenerate matches (bypass curated inputs), use `--skip-curated`.

### CLI Options

```bash
# Basic usage (uses cached curations if available)
aop-wiki-cli collect-harmonized-seizure-aops

# Specify a cache date for AOP-Wiki data
aop-wiki-cli collect-harmonized-seizure-aops --date MM-DD-YYYY

# Force refresh of AOP-Wiki XML data
aop-wiki-cli collect-harmonized-seizure-aops --force-refresh

# Skip curated inputs and regenerate via fuzzy matching + review
aop-wiki-cli collect-harmonized-seizure-aops --skip-curated
```

### Export to Target Project

```bash
# Preview file moves (recommended)
./export_ready_for_emod_upload.sh --date MM-DD-YYYY --output /path/to/target/inputs/seizure_aops --dry-run

# Execute file moves
./export_ready_for_emod_upload.sh --date MM-DD-YYYY --output /path/to/target/inputs/seizure_aops
```

### Output Files

Outputs are written to `<data-dir>/outputs/seizure_aops/{date}/`:

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

- **Entry point**: the `aop-wiki-cli` console script, defined by `aop_wiki_cli.cli:app`
- **Source code**: all production code is in `src/aop_wiki_cli/`, organized by functional domain
- **Configuration**: analysis configurations are in `src/aop_wiki_cli/configs/`
- **Path resolution**: `src/aop_wiki_cli/paths.py` resolves every input, output,
  cache and log root; modules never build paths from bare relative strings
- **Tests**:
  - Unit and integration tests are in `tests/` at project root
  - One test has been created as a shell script at project root
- **Scripts**: Catch all space for "scripts"

### Testing

```bash
# Run the test suite
uv run pytest

# Run a test that all CLI functions are running with standard params
bash test_cli_integration.sh

# Alt version - just view results, using grep
bash test_cli_integration.sh 2>&1 | grep -E "(Testing:|PASSED|FAILED|Test Summary)"
```

Packaging itself is not covered by the test suite. To verify that the tool still installs and runs from outside a
clone — after any change to the package layout, the entry point, or `src/aop_wiki_cli/paths.py` — work through
[docs/module_testing.md](docs/module_testing.md).

## Project Structure ()

```sh
aop_wiki_cli/
├── pyproject.toml                      # Project metadata, dependencies, entry point
├── test_cli_integration.sh             # CLI integration tests
├── export_ready_for_emod_upload.sh     # Seizure output export script
│
├── src/aop_wiki_cli/             # The installable package
│   ├── cli.py                    # Typer app; the `aop-wiki-cli` entry point
│   ├── __main__.py               # `python -m aop_wiki_cli`
│   ├── paths.py                  # Data-directory and package-data resolution
│   ├── analysis/                 # Post-extraction analytics
│   ├── collection/               # Needs refactoring
│   ├── parsers/                  # Parser for the XML and other sources
│   ├── search/                   # Text and reference searching
│   ├── harmonization/            # KER Evidence table standardization
│   ├── data_export/              # File generation (CSV, Excel, JSON)
│   ├── utilities/                # Shared helper functions
│   ├── configs/                  # Analysis configuration files
│   └── data/                     # Files shipped in the wheel
│       ├── seizure_aops/         # Behl seizure AOP workbook
│       └── curated/              # Human-reviewed mapping inputs
│
├── tests/                        # Unit and integration tests
├── docs/                         # Project documentation
├── outputs_for_vc/               # Curated outputs for version control
└── ...
```

At runtime, under the data directory (`--data-dir`, `$AOP_WIKI_CLI_DATA_DIR`, or cwd):

```sh
<data-dir>/
├── inputs/                       # Optional user-supplied inputs
├── curated/                      # Optional overrides of the shipped curated files
├── outputs/                      # Generated outputs
│   ├── seizure_aops/             # Seizure workflow outputs
│   ├── event_rankings/           # Event ranking results
│   ├── ker_evidence/             # KER evidence data
│   ├── ker_lookups/              # KER lookups by key event
│   └── cache/                    # Cached XML/JSON data
├── xml_inputs/                   # Downloaded AOP-Wiki XML files
└── logs/                         # Log files
```


## License

This project is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 Ginnie Hench
