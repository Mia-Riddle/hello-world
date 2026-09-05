"""Turns a saved build (see build_store.py) into a clean, budget-ready .xlsx
-- something you can actually plan a purchase from, not just a data dump.
"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HEADER_FILL = PatternFill("solid", fgColor="1F2937")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
TITLE_FONT = Font(bold=True, size=16, color="1F2937")
SUBTITLE_FONT = Font(italic=True, size=10, color="6B7280")
GOOD_FILL = PatternFill("solid", fgColor="D1FAE5")
WARN_FILL = PatternFill("solid", fgColor="FEF3C7")
BAD_FILL = PatternFill("solid", fgColor="FEE2E2")
INFO_FILL = PatternFill("solid", fgColor="E0E7FF")
THIN = Side(style="thin", color="D1D5DB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
STATUS_FILL = {"GOOD": GOOD_FILL, "WARN": WARN_FILL, "BAD": BAD_FILL, "INFO": INFO_FILL}


def _style_header_row(ws, row, ncols):
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = BORDER


def _autosize(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def export_build_to_xlsx(data: dict, out_path: str) -> str:
    wb = Workbook()

    # --- Summary sheet ---
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"PC Readiness Report -- {data['name']}"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Saved {data['saved_at']}"
    ws["A2"].font = SUBTITLE_FONT

    ws["A4"] = "Editing workflow"
    ws["A4"].font = Font(bold=True)
    wa = data["workflow_answers"]
    ws["A5"] = (f"Resolution: {wa['resolution']}   Codec: {wa['codec']}   "
                f"Concurrent streams: {wa['multicam_streams']}   Grading: {wa['grading_intensity']}")

    ws["A7"] = "Component"
    ws["B7"] = "Status"
    ws["C7"] = "Why"
    _style_header_row(ws, 7, 3)
    row = 8
    for v in data["evaluation"]:
        ws.cell(row=row, column=1, value=v["category"]).border = BORDER
        status_cell = ws.cell(row=row, column=2, value=v["status"])
        status_cell.fill = STATUS_FILL.get(v["status"], INFO_FILL)
        status_cell.alignment = Alignment(horizontal="center")
        status_cell.border = BORDER
        why_cell = ws.cell(row=row, column=3, value=v["summary"])
        why_cell.border = BORDER
        why_cell.alignment = Alignment(wrap_text=True)
        row += 1

    total = data.get("estimated_upgrade_total_usd", 0)
    row += 1
    ws.cell(row=row, column=1, value="Estimated total to fix all bottlenecks").font = Font(bold=True)
    total_cell = ws.cell(row=row, column=2, value=total)
    total_cell.number_format = '"$"#,##0.00'
    total_cell.font = Font(bold=True)

    _autosize(ws, [24, 12, 75])
    ws.freeze_panes = "A8"

    # --- Current Build sheet ---
    ws2 = wb.create_sheet("Current Build")
    headers = ["Component", "Detected / Entered Spec", "Measured Benchmark", "Notes"]
    for i, h in enumerate(headers, start=1):
        ws2.cell(row=1, column=i, value=h)
    _style_header_row(ws2, 1, len(headers))

    hw = data["hardware"]
    bench = data["benchmark"]
    cpu_spec = f"{hw['cpu_name']} -- {hw['physical_cores']}c/{hw['logical_cores']}t"
    if hw.get("cpu_max_ghz"):
        cpu_spec += f" @ {hw['cpu_max_ghz']}GHz"
    gpu_spec = hw["gpu_name"]
    gpu_spec += f" -- {hw['gpu_vram_gb']}GB VRAM" if hw.get("gpu_vram_gb") else " -- VRAM not entered"

    rows = [
        ("CPU", cpu_spec, f"{bench['cpu_hash_mb_per_sec']} MB/s hashing throughput", ""),
        ("RAM", f"{hw['ram_total_gb']} GB installed", f"{bench['ram_copy_gb_per_sec']} GB/s copy bandwidth", ""),
        ("GPU", gpu_spec, "-", "Enter VRAM manually from the main menu if it shows unknown"),
        ("Storage (tested drive)", f"{len(hw['disks'])} drive(s) detected",
         f"Write {bench['disk_write_mb_per_sec']} MB/s / Read {bench['disk_read_mb_per_sec']} MB/s",
         "Benchmark ran against the folder you pointed it at"),
        ("OS", hw["os_name"], "-", ""),
    ]
    for r, row_data in enumerate(rows, start=2):
        for c, val in enumerate(row_data, start=1):
            cell = ws2.cell(row=r, column=c, value=val)
            cell.border = BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws2, [22, 42, 34, 36])
    ws2.freeze_panes = "A2"

    # --- Upgrade Budget sheet ---
    ws3 = wb.create_sheet("Upgrade Budget")
    headers = ["Buy?", "Category", "Suggested Part", "Why", "Price (USD)", "Notes", "Shop (search links)"]
    for i, h in enumerate(headers, start=1):
        ws3.cell(row=1, column=i, value=h)
    _style_header_row(ws3, 1, len(headers))

    suggestions = data.get("upgrade_suggestions", [])
    start_row = 2
    for r, s in enumerate(suggestions, start=start_row):
        ws3.cell(row=r, column=1, value="No")
        ws3.cell(row=r, column=2, value=s["category"])
        ws3.cell(row=r, column=3, value=s["part_name"])
        why_cell = ws3.cell(row=r, column=4, value=s["reason"])
        why_cell.alignment = Alignment(wrap_text=True)
        price_cell = ws3.cell(row=r, column=5, value=s["price_usd"])
        price_cell.number_format = '"$"#,##0.00'
        note_cell = ws3.cell(row=r, column=6, value=s["note"])
        note_cell.alignment = Alignment(wrap_text=True)
        links = "  |  ".join(f"{store}: {url}" for store, url in s["shop_links"].items())
        ws3.cell(row=r, column=7, value=links)
        for c in range(1, 8):
            ws3.cell(row=r, column=c).border = BORDER

    end_row = start_row + len(suggestions) - 1
    if suggestions:
        dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
        ws3.add_data_validation(dv)
        dv.add(f"A{start_row}:A{end_row}")

        total_row = end_row + 2
        ws3.cell(row=total_row, column=4, value='Total if buying everything checked "Yes":').font = Font(bold=True)
        total_cell = ws3.cell(
            row=total_row, column=5,
            value=f'=SUMIF(A{start_row}:A{end_row},"Yes",E{start_row}:E{end_row})',
        )
        total_cell.number_format = '"$"#,##0.00'
        total_cell.font = Font(bold=True)
    else:
        ws3.cell(row=2, column=1, value="No bottlenecks found -- nothing to buy right now!").font = Font(italic=True)

    _autosize(ws3, [8, 12, 28, 46, 12, 36, 65])
    ws3.freeze_panes = "A2"

    wb.save(out_path)
    return out_path
