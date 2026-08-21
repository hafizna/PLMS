#!/usr/bin/env python3
"""Read-only profiler for the PLMS v2 relay-setting sources.

This is deliberately a profiling stage, not a loader.  It maps every physical
worksheet to the 17 logical sources named in the rebuild prompt, inventories
columns/formulas, emits deterministic relay identity candidates, and exposes
cross-sheet conflicts for review.  It never writes to a source workbook or DB.

Usage:
    python plms_v2_profile.py [source_dir] [output_dir]
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula


UPT_WORKBOOK = "Data Setting Penghantar UPT DKSBI.xlsx"
OFFICIAL_WORKBOOK = "List Official Setting & Resetting UPT Durikosambi.xlsx"

PLACEHOLDERS = {
    "", "-", "--", "N/A", "NA", "NONE", "NULL", "NO DATA", "TIDAK ADA",
    "BELUM ADA", "BELUM TERPASANG", "TIDAK TERPASANG",
}


@dataclass(frozen=True)
class DeviceBlock:
    slot: str
    function_type: str
    coordination_class: str
    manufacturer: int | None = None
    model: int | None = None
    serial_no: int | None = None
    relay_kind: int | None = None
    operation_year: int | None = None
    status: int | None = None
    role_value: str | None = None
    role_column: int | None = None


@dataclass(frozen=True)
class SheetConfig:
    logical_source: str
    role: str
    layout: str
    header_rows: tuple[int, ...]
    data_start: int | None
    base_columns: dict[str, int] = field(default_factory=dict)
    devices: tuple[DeviceBlock, ...] = ()
    note: str = ""


PHT_BASE = {
    "asset_id": 1, "ultg": 3, "gi": 4, "bay": 5, "circuit": 6,
}

# Explicit mapping: no tab is silently discarded.  REVIEW is intentional for
# functions not classified by the prompt's GRADED/UNIT/AUXILIARY table.
UPT_SHEETS: dict[str, SheetConfig] = {
    "FR_OCR": SheetConfig("FR_OCR", "register", "wide_form", (1,), 2,
        note="Wide Google Form response; must be unpivoted in v2b."),
    "Rekap": SheetConfig("Rekap", "summary", "summary", (1, 2, 3, 4), None),
    "MASTER_PHT": SheetConfig("LCD+DIST", "helper", "master", (4, 5, 6, 7, 8, 9), 11,
        note="Master asset/helper table shared by protection sheets."),
    "LCD": SheetConfig("LCD+DIST", "register", "row_register", (4, 5, 6, 7, 8, 9), 11,
        {**PHT_BASE, "ct_ratio": 7, "pt_ratio": 8},
        (DeviceBlock("LCD", "LCD", "UNIT", 12, 13, 14, 15, 16, role_column=9),)),
    "Rekap1": SheetConfig("Rekap1", "summary", "summary", (1, 2, 3, 4, 5, 6), None),
    "Pivot Table 1": SheetConfig("Pivot Table 1", "summary", "pivot", (1, 2, 3, 4), None),
    "DIFF Pilot": SheetConfig("DIFF Pilot", "register", "multi_device_row", (4, 5, 6, 7, 8, 9), 10,
        {"ultg": 5, "gi": 6, "bay": 7, "circuit": 8, "ct_ratio": 9, "asset_id": 3},
        (DeviceBlock("PILOT_1", "DIFF_PILOT", "UNIT", 10, 11, 12, 13, 14, role_value="PILOT_1"),
         DeviceBlock("PILOT_2", "DIFF_PILOT", "UNIT", 19, 20, 21, 22, 23, role_value="PILOT_2"))),
    "DIST": SheetConfig("LCD+DIST", "register", "row_register", (4, 5, 6, 7, 8, 9), 11,
        {**PHT_BASE, "ct_ratio": 7, "pt_ratio": 8},
        (DeviceBlock("DIST", "DIST", "GRADED", 12, 13, 14, 15, 16, role_column=9),)),
    "OCR_PHT": SheetConfig("OCR", "register", "row_register", (4, 5, 6, 7, 8, 9), 11,
        {**PHT_BASE, "ct_ratio": 7},
        (DeviceBlock("OCR", "OCR_GFR", "GRADED", 10, 11, 12, 13, 14, role_value="BPU"),)),
    "AR": SheetConfig("AR", "register", "row_register", (4, 5, 6, 7, 8, 9), 11,
        PHT_BASE,
        (DeviceBlock("AR", "AR", "AUXILIARY", 10, 11, 12, 13, 14, role_column=7),)),
    "HEL_PHT_SET": SheetConfig("LCD+DIST", "helper", "calculation_helper", (1, 2, 3, 4, 5, 6), None),
    "HEL_PHT_TAP": SheetConfig("LCD+DIST", "helper", "calculation_helper", (1, 2, 3, 4, 5, 6), None),
    "OCR_KOPEL": SheetConfig("OCR KOPEL", "register", "row_register", (4, 5, 6, 7, 8, 9), 11,
        {**PHT_BASE, "ct_ratio": 8},
        (DeviceBlock("OCR_KOPEL", "OCR_GFR", "GRADED", 13, 14, 15, 16, 17, role_value="KOPEL"),)),
    "DV_HELPER_KPL": SheetConfig("DV", "helper", "validation_helper", (1, 2, 3), 4,
        note="DV validation/helper; not a relay register."),
    "SYNCHRO": SheetConfig("Synchro", "register", "row_register", (4, 5, 6, 7, 8, 9), 11,
        {**PHT_BASE, "pt_ratio": 7},
        (DeviceBlock("SYNCHRO", "SYNCHRO", "AUXILIARY", 9, 10, 11, 12, 13,
                     role_value="SYNCHRO"),)),
    "SYNCHROx": SheetConfig("Synchro", "helper", "alternate_helper", (1, 2, 3, 4), None,
        note="Alternate/helper synchro sheet; retained in profile."),
    "BUSPRO": SheetConfig("BUSPRO", "register", "row_register", (4, 5, 6, 7, 8, 9), 10,
        {"ultg": 3, "gi": 4, "bay": 5, "ct_ratio": 7},
        (DeviceBlock("BUSPRO", "BUSPRO", "UNIT", 8, 9, 10, 12, 13, 14, role_column=5),)),
    "KAPASITOR": SheetConfig("KAPASITOR", "register", "multi_device_row", (4, 5, 6, 7, 8, 9), 10,
        {"asset_id": 1, "ultg": 6, "gi": 7, "bay": 8, "circuit": 9},
        (DeviceBlock("OCR_GFR", "OCR_GFR", "GRADED", 13, 14, 15, 16, 17, role_value="OCR_GFR"),
         DeviceBlock("UNBALANCE", "CAP_UNBALANCE", "REVIEW", 29, 30, 31, 32, 33,
                     role_value="UNBALANCE"),
         DeviceBlock("UVR_OVR", "UVR_OVR", "REVIEW", 42, 43, 44, 45, 46,
                     role_value="UVR_OVR")),
        "UNBALANCE and UVR/OVR are not classified in the prompt; kept as REVIEW."),
    "CBF": SheetConfig("CBF", "register", "row_register", (4, 5, 6, 7, 8, 9), 10,
        {"ultg": 7, "gi": 8, "bay": 9, "circuit": 10, "ct_ratio": 14},
        (DeviceBlock("CBF", "CBF", "AUXILIARY", 15, 16, 17, 18, 19, role_value="CBF"),)),
    "CCP": SheetConfig("CCP", "register", "multi_device_row", (4, 5, 6, 7, 8, 9), 10,
        {"ultg": 5, "gi": 6, "bay": 7, "circuit": 8, "ct_ratio": 11},
        (DeviceBlock("CCP_1", "CCP", "AUXILIARY", 12, 13, 14, 15, 16, role_value="CCP_1"),
         DeviceBlock("CCP_2", "CCP", "AUXILIARY", 24, 25, 26, 27, 28, role_value="CCP_2"))),
    "SZP": SheetConfig("SZP", "register", "row_register", (4, 5, 6, 7, 8, 9), 10,
        {"ultg": 8, "gi": 9, "bay": 10, "circuit": 11, "ct_ratio": 15},
        (DeviceBlock("SZP", "SZP", "AUXILIARY", 16, 17, 18, 19, 20, role_value="SZP"),)),
    "CBF&CCP": SheetConfig("CBF&CCP", "summary", "grouped_setting_summary", (4, 5, 6, 7), 8,
        note="Multiple setting rows per asset; v2b needs grouped-row parser."),
}

OFFICIAL_SHEETS = {
    "2019-2021": {"role": "event_register", "header_row": 2, "data_start": 3},
    "2022": {"role": "event_register", "header_row": 3, "data_start": 5},
    "2023": {"role": "event_register", "header_row": 3, "data_start": 5},
    "2024": {"role": "event_register", "header_row": 3, "data_start": 5},
    "2025": {"role": "event_register", "header_row": 3, "data_start": 5},
    "2026": {"role": "event_register", "header_row": 3, "data_start": 5},
    "DV": {"role": "helper", "header_row": 1, "data_start": 2},
}


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return re.sub(r"\s+", " ", str(value)).strip()


def norm(value: Any) -> str:
    return clean(value).upper()


def norm_serial(value: Any) -> str:
    """Normalize Excel's numeric rendering without changing serial punctuation."""
    serial = norm(value)
    if re.fullmatch(r"\d+\.0", serial):
        return serial[:-2]
    return serial


def meaningful(value: Any) -> bool:
    return norm(value) not in PLACEHOLDERS


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cell_value(sheet, row: int, column: int | None) -> Any:
    return sheet.cell(row, column).value if column else None


def header_path(sheet, column: int, rows: tuple[int, ...]) -> str:
    parts = []
    for row in rows:
        cell = sheet.cell(row, column)
        value = cell.value
        if value in (None, ""):
            for merged in sheet.merged_cells.ranges:
                if merged.min_row <= row <= merged.max_row and merged.min_col <= column <= merged.max_col:
                    value = sheet.cell(merged.min_row, merged.min_col).value
                    break
        value = clean(value)
        if value and value not in parts:
            parts.append(value)
    return " > ".join(parts)


def infer_column_role(header: str) -> str:
    value = norm(header)
    if not value:
        return "UNLABELED"
    if any(token in value for token in ("PDF", "OFFICIAL", "TANGGAL", "TGL", "STATUS", "KET", "FILE", "SUMBER")):
        return "PROVENANCE"
    if any(token in value for token in ("HELPER", "VALIDASI", "FORMULA")):
        return "HELPER"
    if any(token in value for token in (
        "GI /", "GI/GIS", "GITET", "ULTG", "BAY", "SIRKIT", "MERK", "TYPE", "TIPE",
        "SERI", "JENIS RELE", "TH OPERASI", "RATIO CT", "RASIO CT", "RATIO PT", "RASIO PT",
    )):
        return "IDENTITY"
    return "SETTING_OR_DOMAIN"


def formula_count(sheet) -> int:
    return sum(
        1 for row in sheet.iter_rows() for cell in row
        if cell.data_type == "f" or isinstance(cell.value, ArrayFormula)
    )


def count_meaningful_rows(sheet, start: int | None = None) -> int:
    first = start or 1
    return sum(
        1 for row in sheet.iter_rows(min_row=first)
        if any(meaningful(cell.value) for cell in row)
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def identity_for(candidate: dict[str, Any]) -> tuple[str, str, str]:
    serial = norm_serial(candidate.get("serial_no"))
    if meaningful(serial):
        return f"SERIAL|{serial}", "HIGH", "exact normalized serial"

    parts = [norm(candidate.get(field)) for field in
             ("gi", "bay", "circuit", "manufacturer", "model", "relay_role")]
    completeness = sum(bool(part) for part in parts)
    key = "ASSET|" + "|".join(part or "?" for part in parts)
    if completeness == 6:
        return key, "MEDIUM", "exact normalized asset attributes"
    return key, "LOW", "incomplete exact attributes; no fuzzy merge"


def candidate_rows(sheet, config: SheetConfig, workbook: str, source_hash: str,
                   observed_at: str) -> list[dict[str, Any]]:
    if config.role != "register" or config.layout == "wide_form" or not config.devices:
        return []
    result = []
    for row in range(config.data_start or 1, sheet.max_row + 1):
        base = {field: clean(cell_value(sheet, row, col)) for field, col in config.base_columns.items()}
        if not meaningful(base.get("gi")) and not meaningful(base.get("bay")):
            continue
        for block in config.devices:
            metadata = [
                cell_value(sheet, row, block.manufacturer), cell_value(sheet, row, block.model),
                cell_value(sheet, row, block.serial_no), cell_value(sheet, row, block.relay_kind),
            ]
            # Multi-device rows can have empty secondary blocks.  A single-device
            # register still represents an explicit gap even when metadata is blank.
            if config.layout == "multi_device_row" and not any(meaningful(v) for v in metadata):
                continue
            relay_role = block.role_value or clean(cell_value(sheet, row, block.role_column))
            item = {
                "source_workbook": workbook, "source_sheet": sheet.title, "source_row": row,
                "source_hash": source_hash, "observed_at": observed_at,
                "logical_source": config.logical_source, "device_slot": block.slot,
                "function_type": block.function_type, "coordination_class": block.coordination_class,
                **base,
                "relay_role": relay_role,
                "manufacturer": clean(cell_value(sheet, row, block.manufacturer)),
                "model": clean(cell_value(sheet, row, block.model)),
                "serial_no": clean(cell_value(sheet, row, block.serial_no)),
                "relay_kind": clean(cell_value(sheet, row, block.relay_kind)),
                "operation_year": clean(cell_value(sheet, row, block.operation_year)),
                "status": clean(cell_value(sheet, row, block.status)),
            }
            item["identity_key"], item["identity_confidence"], item["identity_rule"] = identity_for(item)
            result.append(item)
    return result


def column_rows(sheet, header_rows: tuple[int, ...], data_start: int | None,
                workbook: str, logical_source: str, sheet_role: str) -> list[dict[str, Any]]:
    rows = []
    start = data_start or (max(header_rows) + 1 if header_rows else 1)
    for column in range(1, sheet.max_column + 1):
        values = [sheet.cell(row, column).value for row in range(start, sheet.max_row + 1)]
        nonempty = [clean(value) for value in values if meaningful(value)]
        header = header_path(sheet, column, header_rows)
        if not header and not nonempty:
            continue
        types = Counter()
        for value in values:
            if not meaningful(value):
                continue
            if isinstance(value, bool):
                types["boolean"] += 1
            elif isinstance(value, (dt.datetime, dt.date)):
                types["date"] += 1
            elif isinstance(value, (int, float)):
                types["number"] += 1
            else:
                types["text"] += 1
        unique = sorted(set(nonempty))
        rows.append({
            "source_workbook": workbook, "source_sheet": sheet.title,
            "logical_source": logical_source, "sheet_role": sheet_role,
            "column_index": column, "column_letter": get_column_letter(column),
            "header_path": header, "inferred_role": infer_column_role(header),
            "nonempty_values": len(nonempty), "unique_values": len(unique),
            "value_types": ";".join(f"{key}:{types[key]}" for key in sorted(types)),
            "samples": " | ".join(unique[:3]),
        })
    return rows


def header_lookup(sheet, row: int) -> dict[str, int]:
    return {norm(sheet.cell(row, col).value): col for col in range(1, sheet.max_column + 1)
            if meaningful(sheet.cell(row, col).value)}


def first_header(headers: dict[str, int], *names: str) -> int | None:
    for name in names:
        if norm(name) in headers:
            return headers[norm(name)]
    return None


def official_events(sheet, config: dict[str, Any], source_hash: str,
                    observed_at: str) -> list[dict[str, Any]]:
    headers = header_lookup(sheet, config["header_row"])
    columns = {
        "ultg": first_header(headers, "ULTG"),
        "gi": first_header(headers, "GI", "GI/GIS", "GI / GIS"),
        "bay": first_header(headers, "BAY"),
        "protections": first_header(headers, "PROTEKSI"),
        "requester": first_header(headers, "PEMOHON"),
        "sequence_no": first_header(headers, "NO URUT", "NO. URUT"),
        "effective_date": first_header(headers, "TANGGAL BUAT", "TANGGAL"),
        "official_setting": first_header(headers, "OFFICIAL SETTING"),
        "note": first_header(headers, "KETERANGAN"),
        "status": first_header(headers, "STATUS"),
    }
    result = []
    for row in range(config["data_start"], sheet.max_row + 1):
        values = {key: clean(cell_value(sheet, row, column)) for key, column in columns.items()}
        if not any(meaningful(values.get(key)) for key in ("gi", "bay", "protections", "effective_date")):
            continue
        result.append({
            "source_workbook": OFFICIAL_WORKBOOK, "source_sheet": sheet.title,
            "source_row": row, "source_hash": source_hash, "observed_at": observed_at,
            **values,
        })
    return result


def protection_tokens(raw: str) -> list[str]:
    return [token.strip() for token in re.split(r"\s*[,;/&+]\s*", norm(raw)) if token.strip()]


# Sheet CBF/SZP/CCP mencatat bay CBF sbg nama PENGHANTAR yang dilindungi
# (mis. 'PHT 500KV LENGKONG', 'IBT'), sementara CBF&CCP mencatat POSISI
# FISIK breaker-nya ('CUT-OFF 1 DIAMETER 4', 'PMT 5B2') -- dua konvensi
# label utk breaker/IED yang SAMA, bukan konflik data. Diverifikasi 30/40
# kasus IDENTITY_METADATA_CONFLICT awal persis pola ini (serial cocok
# 1:1, source sheet selalu subset {CBF,SZP,CCP,CBF&CCP}) -- lihat commit
# message. Field lain (manufacturer/model/gi/serial_no) TETAP dibanding
# spt biasa; hanya 'bay' yang dikecualikan, dan HANYA kalau field lain
# tidak py konflik sendiri (mis. 1 kasus py manufacturer+model beda
# beneran, ALSTOM/P821 vs AREVA/P841 -- itu tetap harus masuk review).
_DIAMETER_LABEL_SHEETS = {"CBF", "SZP", "CCP", "CBF&CCP"}


def _bay_conflict_is_diameter_labeling(group: list[dict[str, Any]]) -> bool:
    sheets = {row["source_sheet"] for row in group}
    return bool(sheets) and sheets <= _DIAMETER_LABEL_SHEETS and "CBF&CCP" in sheets


# Sheet CBF&CCP kadang mencantumkan brand-family Siemens ('SIPROTEC') di
# depan nomor model (mis. 'SIPROTEC 7VK61'), sheet CBF/SZP/CCP hanya
# nomor model polos ('7VK61') -- model FISIK sama, cuma penulisan beda.
_MODEL_BRAND_PREFIX = re.compile(r"^SIPROTEC\s+", re.I)


def _norm_model_for_compare(value: str) -> str:
    return _MODEL_BRAND_PREFIX.sub("", norm(value))


def overlap_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        groups[row["identity_key"]].append(row)
    output = []
    for key, group in sorted(groups.items()):
        sources = sorted({f'{row["source_sheet"]}:{row["device_slot"]}' for row in group})
        functions = sorted({row["function_type"] for row in group})
        if len(sources) < 2:
            continue
        conflicts = []
        for field in ("gi", "bay", "manufacturer", "model", "serial_no"):
            if field == "bay":
                raw_values = {row.get(field) for row in group if meaningful(row.get(field))}
                values = sorted({norm(v) for v in raw_values})
                if len(values) > 1 and _bay_conflict_is_diameter_labeling(group):
                    continue
            elif field == "model":
                values = sorted({_norm_model_for_compare(row.get(field)) for row in group
                                  if meaningful(row.get(field))})
            else:
                values = sorted({norm(row.get(field)) for row in group if meaningful(row.get(field))})
            if len(values) > 1:
                conflicts.append(f'{field}={" <> ".join(values)}')
        output.append({
            "identity_key": key,
            "identity_confidence": min((row["identity_confidence"] for row in group),
                                       key=lambda value: {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[value]),
            "candidate_count": len(group), "sheet_slots": " | ".join(sources),
            "source_refs": " | ".join(sorted(
                f'{row["source_sheet"]}!{row["source_row"]}:{row["device_slot"]}' for row in group
            )),
            "function_types": " | ".join(functions),
            "metadata_conflict": "YES" if conflicts else "NO",
            "conflict_detail": "; ".join(conflicts),
            "review_action": "REVIEW" if conflicts else "LINK_EXACT",
        })
    return output


def profile(source_dir: Path, output_dir: Path, observed_at: str | None = None) -> dict[str, Any]:
    observed_at = observed_at or dt.date.today().isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    upt_path = source_dir / UPT_WORKBOOK
    official_path = source_dir / OFFICIAL_WORKBOOK
    for path in (upt_path, official_path):
        if not path.exists():
            raise FileNotFoundError(path)

    upt_hash, official_hash = sha256(upt_path), sha256(official_path)
    sheet_profiles: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    upt_values = load_workbook(upt_path, data_only=True, read_only=False)
    upt_formulas = load_workbook(upt_path, data_only=False, read_only=False)
    if set(upt_values.sheetnames) != set(UPT_SHEETS):
        missing = sorted(set(UPT_SHEETS) - set(upt_values.sheetnames))
        extra = sorted(set(upt_values.sheetnames) - set(UPT_SHEETS))
        raise ValueError(f"UPT sheet mapping drift: missing={missing}, extra={extra}")
    for name in upt_values.sheetnames:
        sheet, formula_sheet, config = upt_values[name], upt_formulas[name], UPT_SHEETS[name]
        count = count_meaningful_rows(sheet, config.data_start)
        sheet_profiles.append({
            "source_workbook": UPT_WORKBOOK, "source_hash": upt_hash,
            "physical_sheet": name, "logical_source": config.logical_source,
            "sheet_role": config.role, "layout": config.layout,
            "header_rows": ",".join(map(str, config.header_rows)),
            "data_start": config.data_start or "", "max_rows": sheet.max_row,
            "max_columns": sheet.max_column, "meaningful_data_rows": count,
            "formula_cells": formula_count(formula_sheet), "notes": config.note,
        })
        columns.extend(column_rows(sheet, config.header_rows, config.data_start,
                                   UPT_WORKBOOK, config.logical_source, config.role))
        candidates.extend(candidate_rows(sheet, config, UPT_WORKBOOK, upt_hash, observed_at))

    official_values = load_workbook(official_path, data_only=True, read_only=False)
    official_formulas = load_workbook(official_path, data_only=False, read_only=False)
    if set(official_values.sheetnames) != set(OFFICIAL_SHEETS):
        missing = sorted(set(OFFICIAL_SHEETS) - set(official_values.sheetnames))
        extra = sorted(set(official_values.sheetnames) - set(OFFICIAL_SHEETS))
        raise ValueError(f"Official sheet mapping drift: missing={missing}, extra={extra}")
    for name in official_values.sheetnames:
        sheet, formula_sheet, config = official_values[name], official_formulas[name], OFFICIAL_SHEETS[name]
        role = config["role"]
        count = count_meaningful_rows(sheet, config["data_start"])
        sheet_profiles.append({
            "source_workbook": OFFICIAL_WORKBOOK, "source_hash": official_hash,
            "physical_sheet": name, "logical_source": "OFFICIAL_HISTORY" if role == "event_register" else "DV",
            "sheet_role": role, "layout": "event_rows" if role == "event_register" else "validation_helper",
            "header_rows": str(config["header_row"]), "data_start": config["data_start"],
            "max_rows": sheet.max_row, "max_columns": sheet.max_column,
            "meaningful_data_rows": count, "formula_cells": formula_count(formula_sheet),
            "notes": "Official history event rows" if role == "event_register" else "Helper, not event history",
        })
        columns.extend(column_rows(sheet, (config["header_row"],), config["data_start"],
                                   OFFICIAL_WORKBOOK,
                                   "OFFICIAL_HISTORY" if role == "event_register" else "DV", role))
        if role == "event_register":
            events.extend(official_events(sheet, config, official_hash, observed_at))

    candidates.sort(key=lambda row: (row["source_sheet"], int(row["source_row"]), row["device_slot"]))
    events.sort(key=lambda row: (row["source_sheet"], int(row["source_row"])))
    overlaps = overlap_rows(candidates)
    reviews = []
    for row in overlaps:
        if row["metadata_conflict"] == "YES":
            reviews.append({
                "review_type": "IDENTITY_METADATA_CONFLICT", "source_ref": row["source_refs"],
                "identity_key": row["identity_key"], "logical_source": "",
                "detail": row["conflict_detail"],
                "recommended_action": "Verify source rows; do not link until conflict is resolved.",
            })
    for row in candidates:
        source_ref = f'{row["source_sheet"]}!{row["source_row"]}:{row["device_slot"]}'
        if row["identity_confidence"] == "LOW":
            reviews.append({
                "review_type": "LOW_IDENTITY_CONFIDENCE", "source_ref": source_ref,
                "identity_key": row["identity_key"], "logical_source": row["logical_source"],
                "detail": "Serial absent and exact fallback attributes are incomplete.",
                "recommended_action": "Keep separate unless an authoritative exact identifier is found.",
            })
        if row["coordination_class"] == "REVIEW":
            reviews.append({
                "review_type": "COORDINATION_CLASS_REVIEW", "source_ref": source_ref,
                "identity_key": row["identity_key"], "logical_source": row["logical_source"],
                "detail": f'{row["function_type"]} is not classified by the prompt table.',
                "recommended_action": "Owner must classify or approve an explicit out-of-scope class.",
            })
    for name, config in UPT_SHEETS.items():
        if config.layout in {"wide_form", "grouped_setting_summary"}:
            reviews.append({
                "review_type": "SPECIAL_LAYOUT_PARSER", "source_ref": name,
                "identity_key": "", "logical_source": config.logical_source,
                "detail": config.note,
                "recommended_action": "Use a dedicated provenance-preserving parser in v2b.",
            })
    reviews.sort(key=lambda row: (row["review_type"], row["source_ref"], row["identity_key"]))
    vocabulary = Counter(token for event in events for token in protection_tokens(event["protections"]))
    vocab_rows = [{"protection_token": token, "event_count": count}
                  for token, count in sorted(vocabulary.items())]

    write_csv(output_dir / "sheet_profile.csv", sheet_profiles, [
        "source_workbook", "source_hash", "physical_sheet", "logical_source", "sheet_role",
        "layout", "header_rows", "data_start", "max_rows", "max_columns", "meaningful_data_rows",
        "formula_cells", "notes",
    ])
    write_csv(output_dir / "column_profile.csv", columns, [
        "source_workbook", "source_sheet", "logical_source", "sheet_role", "column_index",
        "column_letter", "header_path", "inferred_role", "nonempty_values", "unique_values",
        "value_types", "samples",
    ])
    candidate_fields = [
        "source_workbook", "source_sheet", "source_row", "source_hash", "observed_at",
        "logical_source", "device_slot", "function_type", "coordination_class", "asset_id",
        "ultg", "gi", "bay", "circuit", "ct_ratio", "pt_ratio", "relay_role", "manufacturer",
        "model", "serial_no", "relay_kind", "operation_year", "status", "identity_key",
        "identity_confidence", "identity_rule",
    ]
    write_csv(output_dir / "relay_candidates.csv", candidates, candidate_fields)
    write_csv(output_dir / "identity_overlaps.csv", overlaps, [
        "identity_key", "identity_confidence", "candidate_count", "sheet_slots", "source_refs",
        "function_types", "metadata_conflict", "conflict_detail", "review_action",
    ])
    write_csv(output_dir / "review_queue.csv", reviews, [
        "review_type", "source_ref", "identity_key", "logical_source", "detail", "recommended_action",
    ])
    write_csv(output_dir / "official_events.csv", events, [
        "source_workbook", "source_sheet", "source_row", "source_hash", "observed_at", "ultg", "gi",
        "bay", "protections", "requester", "sequence_no", "effective_date", "official_setting", "note",
        "status",
    ])
    write_csv(output_dir / "official_function_vocabulary.csv", vocab_rows,
              ["protection_token", "event_count"])

    logical_sources = sorted({config.logical_source for config in UPT_SHEETS.values()})
    class_counts = Counter(row["coordination_class"] for row in candidates)
    conflict_count = sum(row["metadata_conflict"] == "YES" for row in overlaps)
    review_candidates = sum(row["coordination_class"] == "REVIEW" for row in candidates)
    review_counts = Counter(row["review_type"] for row in reviews)
    report = f"""# PLMS v2a — source profiling report

Generated read-only on `{observed_at}`. No source workbook, database, or UI was changed.

## Coverage

- UPT workbook: **{len(UPT_SHEETS)}/22 physical tabs** mapped.
- Logical UPT sources: **{len(logical_sources)}/17** — {', '.join(logical_sources)}.
- Official workbook: **{len(OFFICIAL_SHEETS)}/7 physical tabs** profiled; DV remains an explicit helper.
- Relay candidates: **{len(candidates)}** exact-source rows/device slots.
- Official history events: **{len(events)}** meaningful rows.
- Cross-sheet exact-identity groups: **{len(overlaps)}**; metadata conflicts requiring review: **{conflict_count}**.
- Review queue rows: **{len(reviews)}** — {', '.join(f'{key}: {review_counts[key]}' for key in sorted(review_counts))}.

## Coordination classification (candidate rows)

{chr(10).join(f'- `{key}`: {class_counts[key]}' for key in sorted(class_counts))}

`REVIEW` is not silently coerced into a production class. It currently covers **{review_candidates}**
candidate devices in capacitor UNBALANCE and UVR/OVR blocks because the v2 prompt does not classify
those labels explicitly.

## Identity rule

1. A meaningful normalized serial number creates `SERIAL|...` (HIGH confidence).
2. Without serial, exact normalized GI + bay + circuit + manufacturer + model + relay role creates `ASSET|...`
   (MEDIUM when complete, otherwise LOW).
3. Function type is deliberately excluded from the identity key: one physical IED can appear in LCD,
   DIST, AR, CBF, or other function sheets.
4. No fuzzy matching is performed. Conflicting exact groups are emitted to `identity_overlaps.csv`.

## Explicit v2b parser work

- Unpivot `FR_OCR` (143-column form response) with source-column provenance.
- Parse grouped multi-row settings in `CBF&CCP`.
- Convert setting columns to long form while retaining workbook/sheet/row/column/header/hash.
- Resolve the capacitor `CAP_UNBALANCE` and `UVR_OVR` coordination classification.
- Link official events to relay identities and determine `is_current` by effective date without overwrites.
- Review LOW-confidence identities and all metadata conflicts before database load.
"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return {
        "sheet_profiles": sheet_profiles, "columns": columns, "candidates": candidates,
        "overlaps": overlaps, "reviews": reviews, "events": events, "vocabulary": vocab_rows,
        "logical_sources": logical_sources,
    }


def main(argv: list[str]) -> int:
    source_dir = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    output_dir = Path(argv[2]).resolve() if len(argv) > 2 else source_dir / "v2a_profile"
    result = profile(source_dir, output_dir)
    print(f"v2a profile written to {output_dir}")
    print(f"29 sheets; {len(result['candidates'])} relay candidates; "
          f"{len(result['events'])} official events; {len(result['overlaps'])} identity overlaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
