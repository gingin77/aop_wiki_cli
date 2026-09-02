#!/bin/bash
# Run with:
# ./export_ready_for_emod_upload.sh  --date 08-30-2024 --output /path/to/export/dir [--dry-run]
# ./export_ready_for_emod_upload.sh  --date 03-19-2026 --output /Users/ginniehench/Desktop/dev_projects/emod_3_OH.nosync/inputs/seizure_aops --dry-run

set -euo pipefail

if [[ -t 1 ]]; then
    C_RESET='\033[0m'
    C_BOLD='\033[1m'
    C_GREEN='\033[0;32m'
    C_YELLOW='\033[1;33m'
    C_RED='\033[0;31m'
    C_CYAN='\033[0;36m'
    C_GRAY='\033[0;90m'
else
    C_RESET=''
    C_BOLD=''
    C_GREEN=''
    C_YELLOW=''
    C_RED=''
    C_CYAN=''
    C_GRAY=''
fi

info() { echo -e "${C_CYAN}$*${C_RESET}"; }
ok() { echo -e "${C_GREEN}$*${C_RESET}"; }
warn() { echo -e "${C_YELLOW}$*${C_RESET}"; }
err() { echo -e "${C_RED}$*${C_RESET}"; }
muted() { echo -e "${C_GRAY}$*${C_RESET}"; }

usage() {
    echo "Usage: $0 --date MM-DD-YYYY --output /path/to/output/dir [--dry-run]"
}

WORK_DATE=""
EXPORT_PATH=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --date|-d)
            WORK_DATE="${2:-}"
            shift 2
            ;;
        --output|-o)
            EXPORT_PATH="${2:-}"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            usage
            exit 1
            ;;
    esac
done

if [[ -z "$WORK_DATE" || -z "$EXPORT_PATH" ]]; then
    err "Error: --date and --output are required"
    usage
    exit 1
fi

OUTPUT_DIR="$EXPORT_PATH"
EXPORT_BASENAME=""
PATH_BASENAME="$(basename "$EXPORT_PATH")"
if [[ "$PATH_BASENAME" == *.* ]]; then
    EXPORT_BASENAME="$(basename "$EXPORT_PATH")"
    OUTPUT_DIR="$(dirname "$EXPORT_PATH")"
fi

if [[ ! "$OUTPUT_DIR" =~ (^|/)"$WORK_DATE"(/|$) ]]; then
    OUTPUT_DIR="$OUTPUT_DIR/$WORK_DATE"
    if [[ -n "$EXPORT_BASENAME" ]]; then
        EXPORT_PATH="$OUTPUT_DIR/$EXPORT_BASENAME"
    else
        EXPORT_PATH="$OUTPUT_DIR"
    fi
fi

if [[ ! -d "$OUTPUT_DIR" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        warn "[DRY RUN] Would create output directory: $OUTPUT_DIR"
    else
        info "Creating output directory: $OUTPUT_DIR"
        mkdir -p "$OUTPUT_DIR"
    fi
else
    muted "Output directory already exists: $OUTPUT_DIR"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Read from the same data directory the CLI writes to; defaults to the clone
DATA_DIR="${AOP_WIKI_CLI_DATA_DIR:-$SCRIPT_DIR}"
SRC_BASE="$DATA_DIR/outputs/seizure_aops/$WORK_DATE"

muted "Source base: $SRC_BASE"
muted "Destination base: $OUTPUT_DIR"

FILE_LABELS=(
    "aops"
    "assays_by_aeid"
    "biological_target_families"
    "chemicals"
    "harmonized_ke_titles"
    "harmonized_event_mappings"
    "biological_target_families_enriched"
    "event_to_assay_mappings"
)

FILE_NAMES=(
    "aop_to_harmonized_events_dict_${WORK_DATE}.json"
    "assays_by_aeid_${WORK_DATE}.json"
    "biological_target_families_${WORK_DATE}.json"
    "chemicals_by_casrn_with_seizure_details_${WORK_DATE}.json"
    "harmonized_kes_${WORK_DATE}.json"
    "event_mappings_orig_to_harmonized_${WORK_DATE}.json"
    "biological_target_families_enriched_${WORK_DATE}.json"
    "event_to_assays_via_target_families_${WORK_DATE}.json"
)

MOVED_COUNT=0
MISSING_COUNT=0

for idx in "${!FILE_LABELS[@]}"; do
    label="${FILE_LABELS[$idx]}"
    name="${FILE_NAMES[$idx]}"
    src="$SRC_BASE/$name"
    dest="$OUTPUT_DIR/$name"
    

    if [[ ! -f "$src" ]]; then
        echo -e "${C_RED}Missing${C_RESET} (${C_CYAN}${label}${C_RESET}): ${C_YELLOW}${name}${C_RESET}"
        MISSING_COUNT=$((MISSING_COUNT + 1))
        continue
    fi

    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${C_YELLOW}[DRY RUN] Would copy${C_RESET} (${C_CYAN}${label}${C_RESET}): ${C_YELLOW}${name}${C_RESET}"
    else
        cp "$src" "$dest"
        echo -e "${C_GREEN}Copied${C_RESET} (${C_CYAN}${label}${C_RESET}): ${C_YELLOW}${name}${C_RESET}"
    fi
    MOVED_COUNT=$((MOVED_COUNT + 1))
done

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${C_BOLD}Dry-run summary:${C_RESET} would_copy=${C_GREEN}${MOVED_COUNT}${C_RESET} missing=${C_RED}${MISSING_COUNT}${C_RESET}"
else
    echo -e "${C_BOLD}Copy summary:${C_RESET} copied=${C_GREEN}${MOVED_COUNT}${C_RESET} missing=${C_RED}${MISSING_COUNT}${C_RESET}"
fi



