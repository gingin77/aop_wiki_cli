"""
Tests for data_export/export_harmonized_kers_to_excel.py — building the
multi-sheet harmonized-KER evidence workbook.

Each sheet builder is tested against a fresh openpyxl Workbook, and
``transform_outputs_for_excel`` is tested end to end by saving a real .xlsx to
tmp_path and reading the sheets back. No network; the only I/O is the workbook
file under tmp_path.

Run with::

    $ uv run pytest tests/test_export_harmonized_kers_to_excel.py
"""

from openpyxl import Workbook, load_workbook

from aop_wiki_cli.data_export import export_harmonized_kers_to_excel as ex


def _new_wb():
    wb = Workbook()
    wb.remove(wb.active)
    return wb


# A realistic harmonized-data structure (shape produced by
# harmonize_evidence_headers, with per-KER records merged alongside 'summary').
HARMONIZED_DATA = {
    "summary": {
        "counts": {"Count KERs with tabulated evidence": 1, "Count Harmonized headers": 3},
        "harmonizable_kers": ["10"],
        "all_harmonized_headers": ["Upstream Key Event", "Downstream Key Event", "References"],
        "all_unmatched_headers": ["notes"],
        "aops_harm_evi": ["1"],
    },
    "10": {
        "upstream_ke": {"id": "100", "title": "Oxidative stress"},
        "downstream_ke": {"id": "200", "title": "Cell death"},
        "harmonized_tables": {
            "weight_of_evidence": {"0": [
                {"Upstream Key Event": "A", "Downstream Key Event": "B", "References": "R", "notes": "n"},
            ]},
        },
    },
}
AOP_TO_KER = {"1": ["10"]}
AOP_INFO = {"1": {"title": "An AOP title", "oecd_status": "WPHA/WNT Endorsed"}}
AOPS_SELECTED = {1: "desc"}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def test_add_rows_from_field_type():
    all_rows = []
    ex._add_rows_from_field_type(all_rows, "10", {"tables": {"0": [{"col": "v"}]}}, "weight_of_evidence")
    assert all_rows == [{
        "KER ID": "10", "Field Type": "weight_of_evidence", "Table Index": "0", "col": "v",
    }]


def test_write_ke_metadata_with_and_without_id():
    ws = Workbook().active
    nxt = ex._write_ke_metadata(ws, 1, "Upstream KE:", {"id": "100", "title": "Oxidative stress"})
    assert nxt == 2
    assert ws.cell(1, 1).value == "Upstream KE:"
    assert ws.cell(1, 2).value == "Oxidative stress"
    assert ws.cell(1, 2).hyperlink is not None
    # no id -> no hyperlink
    ex._write_ke_metadata(ws, 3, "Downstream KE:", {"title": "Cell death"})
    assert ws.cell(3, 2).hyperlink is None


# ---------------------------------------------------------------------------
# individual sheet builders
# ---------------------------------------------------------------------------

def test_create_summary_sheet():
    wb = _new_wb()
    ex._create_summary_sheet(wb, HARMONIZED_DATA["summary"])
    assert "Summary" in wb.sheetnames


def test_create_header_list_sheets():
    wb = _new_wb()
    ex._create_header_list_sheets(wb, HARMONIZED_DATA["summary"])
    assert "all_harmonized_headers" in wb.sheetnames
    assert "all_unmatched_headers" in wb.sheetnames
    assert wb["all_unmatched_headers"].cell(2, 1).value == "notes"


def test_create_harmonizable_kers_sheet():
    wb = _new_wb()
    ex._create_harmonizable_kers_sheet(wb, HARMONIZED_DATA, HARMONIZED_DATA["summary"])
    ws = wb["harmonizable_kers"]
    assert ws.cell(1, 1).value == "KER ID"
    assert ws.cell(2, 1).value == "KER 10"
    assert ws.cell(2, 2).value == "Oxidative stress"
    assert ws.cell(2, 3).value == "Cell death"


def test_create_sheet_for_aops():
    wb = _new_wb()
    ex._create_sheet_for_aops(wb, HARMONIZED_DATA["summary"], AOPS_SELECTED, AOP_TO_KER, AOP_INFO)
    ws = wb["AOPs_with_harmonizable_KERs"]
    assert ws.cell(1, 1).value == "AOP ID"
    assert ws.cell(2, 1).value == "AOP 1"
    assert ws.cell(2, 2).value == "An AOP title"
    assert ws.cell(2, 3).value == "Y"            # AOP 1 is selected
    assert ws.cell(2, 4).value == "WPHA/WNT Endorsed"


def test_create_sheet_for_aops_no_harmonizable_warns(capsys):
    wb = _new_wb()
    summary = dict(HARMONIZED_DATA["summary"], aops_harm_evi=[])
    ex._create_sheet_for_aops(wb, summary, AOPS_SELECTED, AOP_TO_KER, AOP_INFO)
    assert "No AOPs with harmonizable KERs" in capsys.readouterr().out
    assert "AOPs_with_harmonizable_KERs" not in wb.sheetnames


def test_create_ker_sheet():
    wb = _new_wb()
    ex._create_ker_sheet(wb, "10", HARMONIZED_DATA["10"])
    assert "KER_10" in wb.sheetnames
    assert wb["KER_10"].cell(1, 1).value == "KER 10"


def test_create_ker_sheet_no_tables_skips():
    wb = _new_wb()
    ex._create_ker_sheet(wb, "10", {"harmonized_tables": {}})
    assert wb.sheetnames == []  # nothing created


# ---------------------------------------------------------------------------
# transform_outputs_for_excel (end to end)
# ---------------------------------------------------------------------------

def test_transform_outputs_for_excel_full_workbook(tmp_path):
    out = tmp_path / "harmonized.xlsx"
    ex.transform_outputs_for_excel(
        HARMONIZED_DATA, str(out), aops_selected_for_workbooks=AOPS_SELECTED,
        aop_to_ker_dict=AOP_TO_KER, aop_info=AOP_INFO,
    )
    wb = load_workbook(out)
    for expected in ("Summary", "AOPs_with_harmonizable_KERs", "all_harmonized_headers",
                     "harmonizable_kers", "KER_10"):
        assert expected in wb.sheetnames


def test_transform_outputs_for_excel_ker_pages_only(tmp_path):
    out = tmp_path / "kers_only.xlsx"
    ex.transform_outputs_for_excel(HARMONIZED_DATA, str(out), ker_pages_only=True)
    wb = load_workbook(out)
    assert wb.sheetnames == ["KER_10"]  # summary/list sheets skipped
