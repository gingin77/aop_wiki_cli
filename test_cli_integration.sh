#!/bin/bash

# Integration test script for CLI commands
# Tests each CLI command with actual execution

set -e  # Exit on first error

echo "=================================="
echo "CLI Integration Tests"
echo "=================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test date - dynamically set to today
TEST_DATE=$(date +%m-%d-%Y)

# The CLI under test. Override to exercise an installed copy, e.g.
#   CLI="aop-wiki-cli" bash test_cli_integration.sh
CLI="${CLI:-uv run aop-wiki-cli}"

# Where the CLI reads and writes; must match what the CLI itself resolves
DATA_DIR="${AOP_WIKI_CLI_DATA_DIR:-$(pwd)}"

# Counter for passed/failed tests
PASSED=0
FAILED=0

# Helper function to run a test
run_test() {
    local test_name="$1"
    local command="$2"
    
    echo -e "${YELLOW}Testing: ${test_name}${NC}"
    echo "Command: $command"
    
    if eval "$command"; then
        echo -e "${GREEN}✓ PASSED${NC}"
        ((PASSED++))
        echo ""
        return 0
    else
        echo -e "${RED}✗ FAILED (exit code: $?)${NC}"
        ((FAILED++))
        echo ""
        return 1
    fi
}

# Test 1: Help command (should always work)
run_test "CLI Help" \
    "$CLI --help"

# Test 2: Collect event integration rankings
run_test "Collect Event Integration Rankings" \
    "$CLI collect-event-integration-rankings --date $TEST_DATE"

# Test 3: Collect event rankings with force refresh
run_test "Event Rankings (Force Refresh)" \
    "$CLI collect-event-integration-rankings --date $TEST_DATE --force-refresh"

# Test 4: Collect KER analytics
run_test "Collect KER Analytics" \
    "$CLI collect-ker-analytics --date $TEST_DATE"

# Test 5: Search KERs for concordance text
run_test "Search KERs for Concordance" \
    "$CLI search-kers-for-concordance-text --date $TEST_DATE"

# Test 6: Harmonize KER evidence
run_test "Harmonize KER Evidence" \
    "$CLI harmonize-ker-evidence --date $TEST_DATE"

# Test 7: Search with config (regulatory_relevance)
run_test "Search with Config: Regulatory Relevance" \
    "$CLI search-with-config regulatory_relevance --date $TEST_DATE"

# Test 8: Search with config (methods_nams)
run_test "Search with Config: Methods NAMS" \
    "$CLI search-with-config methods_nams --date $TEST_DATE"

# Test 9: Search with config (lung_and_immune_aops)
run_test "Search with Config: Lung and Immune AOPs" \
    "$CLI search-with-config lung_and_immune_aops --date $TEST_DATE"

# Test 10: Search with config and --co-occurrence-only flag
run_test "Search with Co-occurrence Only Flag" \
    "$CLI search-with-config lung_and_immune_aops --co-occurrence-only --date $TEST_DATE"

# Test 11: Search with config and force refresh
run_test "Search with Config (Force Refresh)" \
    "$CLI search-with-config regulatory_relevance --force-refresh --date $TEST_DATE"

# Test 12: Check help for each command
echo -e "${YELLOW}Testing: Command Help Pages${NC}"
COMMANDS=("collect-event-integration-rankings" "collect-ker-analytics" "find-kers-for-events" "search-kers-for-concordance-text" "harmonize-ker-evidence" "search-with-config")

for cmd in "${COMMANDS[@]}"; do
    echo "  Checking: $cmd --help"
    if $CLI "$cmd" --help > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $cmd help works"
        ((PASSED++))
    else
        echo -e "  ${RED}✗${NC} $cmd help failed"
        ((FAILED++))
    fi
done
echo ""

# Test 13: Verify JSON output structure for co-occurrence-only
echo -e "${YELLOW}Testing: JSON Output Verification${NC}"
LUNG_IMMUNE_JSON=$(find "$DATA_DIR/outputs/lung_and_immune" -name "lung_and_immune_aops_*.json" -type f 2>/dev/null | head -n 1)
if [ -f "$LUNG_IMMUNE_JSON" ]; then
    echo "  Checking JSON structure in: $LUNG_IMMUNE_JSON"
    
    # Check for co_occurrence_only flag
    if python3 -c "import json; data = json.load(open('$LUNG_IMMUNE_JSON')); assert data.get('co_occurrence_only') == True, 'co_occurrence_only should be True'" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} co_occurrence_only flag is set correctly"
        ((PASSED++))
    else
        echo -e "  ${RED}✗${NC} co_occurrence_only flag not found or incorrect"
        ((FAILED++))
    fi
    
    # Check for has_priority_co_occurrence in results
    if python3 -c "import json; data = json.load(open('$LUNG_IMMUNE_JSON')); results = data.get('results', {}); assert any('has_priority_co_occurrence' in r for r in results.values()), 'has_priority_co_occurrence should be in results'" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} has_priority_co_occurrence field present in results"
        ((PASSED++))
    else
        echo -e "  ${RED}✗${NC} has_priority_co_occurrence field missing"
        ((FAILED++))
    fi
    
    # Check for total_entities_with_co_occurrence_matches in summary
    if python3 -c "import json; data = json.load(open('$LUNG_IMMUNE_JSON')); assert 'total_entities_with_co_occurrence_matches' in data.get('summary', {}), 'total_entities_with_co_occurrence_matches should be in summary'" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} total_entities_with_co_occurrence_matches in summary"
        ((PASSED++))
    else
        echo -e "  ${RED}✗${NC} total_entities_with_co_occurrence_matches missing from summary"
        ((FAILED++))
    fi
    
    # Check for co_occurrence_fields in results
    if python3 -c "import json; data = json.load(open('$LUNG_IMMUNE_JSON')); results = data.get('results', {}); assert any('co_occurrence_fields' in r for r in results.values()), 'co_occurrence_fields should be in results'" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} co_occurrence_fields field present in results"
        ((PASSED++))
    else
        echo -e "  ${RED}✗${NC} co_occurrence_fields field missing"
        ((FAILED++))
    fi
else
    echo -e "  ${YELLOW}⚠${NC} No lung_and_immune_aops JSON file found for verification"
fi
echo ""

# Summary
echo "=================================="
echo "Test Summary"
echo "=================================="
echo -e "${GREEN}Passed: $PASSED${NC}"
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $FAILED${NC}"
else
    echo -e "${GREEN}Failed: $FAILED${NC}"
fi
echo ""

# Verify output files were created
echo "=================================="
echo "Output File Verification"
echo "=================================="

OUTPUT_DIRS=(
    "$DATA_DIR/outputs/event_rankings"
    "$DATA_DIR/outputs/ker_evidence"
    "$DATA_DIR/outputs/ker_lookups"
    "$DATA_DIR/outputs/lung_and_immune"
    "$DATA_DIR/outputs/nams_methods"
    "$DATA_DIR/outputs/regulatory_relevance_screening"
)

for dir in "${OUTPUT_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        file_count=$(find "$dir" -type f | wc -l)
        echo -e "${GREEN}✓${NC} $dir exists ($file_count files)"
    else
        echo -e "${YELLOW}⚠${NC} $dir does not exist"
    fi
done

echo ""

# Exit with appropriate code
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    exit 1
fi
