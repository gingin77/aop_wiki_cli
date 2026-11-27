"""
Tests for data_export/excel_writer.py — the generic, field-config-driven Excel
writer (the openpyxl counterpart of csv_writer).

Writes into real openpyxl worksheets/workbooks under tmp_path and reads the
cells back, so value transformation, sorting, header styling, column sizing and
the multi-sheet workbook assembly are all exercised for real.

Run with::

    $ uv run pytest tests/test_excel_writer.py
"""

from openpyxl import Workbook, load_workbook

from aop_wiki_cli.data_export import excel_writer as xw
from aop_wiki_cli.data_export.field_definitions import FieldConfig, FieldConfigSet

CFG = FieldConfigSet("s", [
    FieldConfig("ID", "id"),
    FieldConfig("Flag", "flag", transformer="yes_no"),
])


# ---------------------------------------------------------------------------
# _transform_value
# ---------------------------------------------------------------------------

def test_transform_value():
    assert xw._transform_value(True, "yes_no") == "Yes"
    assert xw._transform_value("x", None) == "x"            # no transformer
    assert xw._transform_value("x", "does_not_exist") == "x"  # unknown name


# ---------------------------------------------------------------------------
# write_excel_sheet
# ---------------------------------------------------------------------------

def test_write_excel_sheet_writes_header_and_rows():
    ws = Workbook().active
    last = xw.write_excel_sheet(ws, [{"id": "a", "flag": True}, {"id": "b", "flag": False}], CFG)
    assert last == 3
    assert ws.cell(1, 1).value == "ID"
    assert ws.cell(1, 1).font.bold is True
    assert (ws.cell(2, 1).value, ws.cell(2, 2).value) == ("a", "Yes")
    assert ws.cell(3, 2).value == "No"


def test_write_excel_sheet_from_dict_and_sorted():
    ws = Workbook().active
    data = {"x": {"id": "a", "flag": True}, "y": {"id": "b", "flag": False}}
    xw.write_excel_sheet(ws, data, CFG, sort_key="id", reverse_sort=True)
    assert [ws.cell(r, 1).value for r in (2, 3)] == ["b", "a"]


def test_write_excel_sheet_empty_returns_start_row():
    ws = Workbook().active
    assert xw.write_excel_sheet(ws, [], CFG, start_row=5) == 5
    assert ws.cell(5, 1).value is None  # nothing written


def test_write_excel_sheet_unsortable_warns_but_writes(capsys):
    ws = Workbook().active
    id_only = FieldConfigSet("c", [FieldConfig("ID", "id")])
    xw.write_excel_sheet(ws, [{"id": "a"}, {"id": 5}], id_only, sort_key="id")
    assert "Could not sort" in capsys.readouterr().out
    assert ws.cell(1, 1).value == "ID"  # still wrote the sheet


# ---------------------------------------------------------------------------
# auto_size_columns
# ---------------------------------------------------------------------------

def test_auto_size_columns_widths():
    ws = Workbook().active
    cfg = FieldConfigSet("s", [
        FieldConfig("A" * 35, "a"),                      # long name -> wraps
        FieldConfig("List", "b", transformer="join_list"),  # -> max width
    ])
    xw.write_excel_sheet(ws, [{"a": "x", "b": [1, 2]}], cfg)
    xw.auto_size_columns(ws, cfg, min_width=10, max_width=40)
    assert ws.column_dimensions["A"].width == 37   # 35 chars + 2
    assert ws.column_dimensions["B"].width == 40   # join_list -> max_width


# ---------------------------------------------------------------------------
# write_excel_workbook
# ---------------------------------------------------------------------------

def test_write_excel_workbook_multiple_sheets(tmp_path):
    out = tmp_path / "report.xlsx"
    sheets = [
        {"name": "Events", "data": [{"id": "a", "flag": True}], "field_config": CFG, "sort_key": "id"},
        {"name": "Empty", "data": [], "field_config": CFG},
    ]
    xw.write_excel_workbook(sheets, out)
    wb = load_workbook(out)
    assert wb.sheetnames == ["Events", "Empty"]
    assert wb["Events"].cell(1, 1).value == "ID"
    assert wb["Events"].cell(2, 2).value == "Yes"
    # auto-filter set on the populated sheet, not the empty one
    assert wb["Events"].auto_filter.ref is not None
    assert wb["Empty"].auto_filter.ref is None


def test_write_excel_workbook_truncates_long_sheet_name(tmp_path):
    out = tmp_path / "r.xlsx"
    xw.write_excel_workbook(
        [{"name": "E" * 40, "data": [{"id": "a", "flag": True}], "field_config": CFG}], out
    )
    wb = load_workbook(out)
    assert len(wb.sheetnames[0]) == 31
