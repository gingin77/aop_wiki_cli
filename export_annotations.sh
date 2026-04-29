#!/bin/bash
# Copy outputs_for_vc/aop_based_ke_annotations to a target directory.
# Usage:
#   ./export_annotations.sh --output /path/to/target/dir [--dry-run]
#   ./export_annotations.sh --output ~/Developer/emod_3_OH.nosync/inputs/lung_and_immune_annotations --dry-run

set -euo pipefail

EXPORT_PATH=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output|-o) EXPORT_PATH="${2:-}"; shift 2 ;;
        --dry-run)   DRY_RUN=true; shift ;;
        *) echo "Usage: $0 --output /path/to/dir [--dry-run]"; exit 1 ;;
    esac
done

if [[ -z "$EXPORT_PATH" ]]; then
    echo "Error: --output is required"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$SCRIPT_DIR/outputs_for_vc/aop_based_ke_annotations"

if [[ ! -d "$SRC_DIR" ]]; then
    echo "Error: source directory not found: $SRC_DIR"
    exit 1
fi

if [[ ! -d "$EXPORT_PATH" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY RUN] Would create: $EXPORT_PATH"
    else
        mkdir -p "$EXPORT_PATH"
        echo "Created: $EXPORT_PATH"
    fi
fi

COUNT=0
while IFS= read -r -d '' src; do
    name="$(basename "$src")"
    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY RUN] Would copy: $name"
    else
        cp "$src" "$EXPORT_PATH/$name"
        echo "Copied: $name"
    fi
    COUNT=$((COUNT + 1))
done < <(find "$SRC_DIR" -maxdepth 1 -type f -print0)

echo "Done: $COUNT file(s)"

