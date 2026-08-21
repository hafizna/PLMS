#!/usr/bin/env python3
"""PLMS v2b ETL: relay settings and official events with cell provenance.

The source workbooks are read-only.  Outputs are CSVs consumed by ``load.py``;
no database is mutated here.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, column_index_from_string
from openpyxl.worksheet.formula import ArrayFormula

from plms_v2_profile import (
    OFFICIAL_WORKBOOK,
    UPT_SHEETS,
    UPT_WORKBOOK,
    clean,
    header_path,
    identity_for,
    meaningful,
    overlap_rows,
    profile,
    sha256,
    write_csv,
)


@dataclass(frozen=True)
class SettingRange:
    group: str
    start: int
    end: int
    source_doc_column: int | None = None
    date_column: int | None = None
    exclude: tuple[int, ...] = ()


# Setting blocks are explicit because neighboring identity, helper, file, and
# date columns must not leak into relay_setting.  Columns are 1-based.
SETTING_RANGES: dict[tuple[str, str], tuple[SettingRange, ...]] = {
    ("LCD", "LCD"): (
        SettingRange("TAP_SET", 17, 29, source_doc_column=30, date_column=31),
        SettingRange("SET_RELAY", 32, 46, source_doc_column=45, exclude=(45,)),
    ),
    ("DIFF Pilot", "PILOT_1"): (SettingRange("SETTING", 15, 18),),
    ("DIFF Pilot", "PILOT_2"): (SettingRange("SETTING", 24, 27),),
    ("DIST", "DIST"): (
        SettingRange("TAP_SET", 17, 37),
        SettingRange("SET_RELAY", 38, 59),
    ),
    ("OCR_PHT", "OCR"): (
        SettingRange("TAP_SET", 15, 22, source_doc_column=23, date_column=24),
        SettingRange("SET_RELAY", 25, 32, source_doc_column=34, date_column=33),
    ),
    ("AR", "AR"): (
        SettingRange("TAP_SET", 15, 19), SettingRange("SET_RELAY", 20, 24),
    ),
    ("OCR_KOPEL", "OCR_KOPEL"): (
        SettingRange("TAP_SET", 18, 25, source_doc_column=26, date_column=27),
        SettingRange("SET_RELAY", 28, 35, source_doc_column=37, date_column=36),
    ),
    ("SYNCHRO", "SYNCHRO"): (
        SettingRange("TAP_SET", 14, 23), SettingRange("SET_RELAY", 24, 33),
    ),
    ("BUSPRO", "BUSPRO"): (SettingRange("SETTING", 16, 20),),
    ("KAPASITOR", "OCR_GFR"): (SettingRange("SETTING", 18, 27),),
    ("KAPASITOR", "UNBALANCE"): (SettingRange("SETTING", 34, 40),),
    ("KAPASITOR", "UVR_OVR"): (SettingRange("SETTING", 47, 51),),
    ("CBF", "CBF"): (SettingRange("SETTING", 20, 25),),
    ("CCP", "CCP_1"): (SettingRange("SETTING", 17, 22),),
    ("CCP", "CCP_2"): (SettingRange("SETTING", 29, 34),),
    ("SZP", "SZP"): (SettingRange("SETTING", 21, 25),),
}

GENERIC_HEADER_PARTS = {
    "LCD", "DIST", "OCR", "AR", "SYNC", "CBF", "SZP", "BUSPRO",
    "TAP SET", "SET RELAY", "SETTING", "SOURCE : FORM IMPLEMENTASI SCANNING",
}

PARAMETER_OVERRIDES = {
    ("KAPASITOR", 20): "OCR/GFR > tms OC",
    ("KAPASITOR", 21): "OCR/GFR > I>> OC",
    ("KAPASITOR", 22): "OCR/GFR > time I>> OC",
    ("KAPASITOR", 24): "OCR/GFR > tms GF",
    ("KAPASITOR", 25): "OCR/GFR > I>> GF",
    ("KAPASITOR", 26): "OCR/GFR > time I>> GF",
    ("KAPASITOR", 48): "UVR/OVR > time U<",
    ("KAPASITOR", 50): "UVR/OVR > time U>",
}


def candidate_ref(sheet: str, row: int | str, slot: str) -> str:
    return f"{sheet}!{row}:{slot}"


def make_candidate(*, sheet: str, row: int, slot: str, logical_source: str,
                   function_type: str, coordination_class: str, source_hash: str,
                   observed_at: str, **fields: Any) -> dict[str, Any]:
    item = {
        "source_workbook": UPT_WORKBOOK, "source_sheet": sheet, "source_row": row,
        "source_hash": source_hash, "observed_at": observed_at,
        "logical_source": logical_source, "device_slot": slot,
        "function_type": function_type, "coordination_class": coordination_class,
        "asset_id": "", "ultg": "", "gi": "", "bay": "", "circuit": "",
        "ct_ratio": "", "pt_ratio": "", "relay_role": slot,
        "manufacturer": "", "model": "", "serial_no": "", "relay_kind": "",
        "operation_year": "", "status": "", **fields,
    }
    item["identity_key"], item["identity_confidence"], item["identity_rule"] = identity_for(item)
    item["candidate_ref"] = candidate_ref(sheet, row, slot)
    return item


def split_make_model(value: Any) -> tuple[str, str]:
    parts = [part.strip() for part in clean(value).split("/", 1)]
    return (parts[0], parts[1] if len(parts) > 1 else "")


# Level tegangan transmisi yang valid di scope ini (lihat VOLTAGE_SUFFIX
# di plms_etl.py). Dipakai utk memvalidasi tebakan dari rasio CT --
# supaya tidak asal terima angka yg tidak masuk akal sbg voltage.
_KNOWN_TRANSMISSION_KV = {70, 150, 500}


def ratio_kv_hint(value: Any) -> str:
    """Dari string rasio CT (mis. '500000/100') di sheet CBF&CCP kolom
    'RATIO (kV)', tebak level tegangan sbg suffix teks (mis. '500KV') utk
    disisipkan ke 'gi' -- disambiguasi resolve_ss() (load.py) yang
    butuh voltage eksplisit saat 1 nama GI py >1 opsi level tegangan
    (mis. 'GITET Balaraja' 150kV vs 500kV).

    PENTING: kolom ini secara harfiah 'RATIO (kV)' tapi isinya rasio CT
    primary/secondary (Ampere), BUKAN kV langsung -- dikonfirmasi
    pemilik data: rating CT primary diskalakan mengikuti level tegangan
    pemasangan (sirkuit 500kV pakai CT primary lebih besar), jadi
    dipakai sbg SINYAL, bukan definisi voltage yg eksak. Hanya diterima
    kalau primary/1000 persis cocok salah satu level transmisi yang
    dikenal (70/150/500) -- kalau tidak cocok, kembalikan '' (tidak
    menebak) drpd menyisipkan angka yang salah."""
    raw = clean(value)
    match = re.match(r"^(\d+)\s*/\s*\d+", raw)
    if not match:
        return ""
    primary = int(match.group(1))
    if primary % 1000 != 0:
        return ""
    kv = primary // 1000
    return f"{kv}KV" if kv in _KNOWN_TRANSMISSION_KV else ""


_GI_PREFIX_WORD = re.compile(r"^(GISTET|GITET|GIS|GI)\b", re.IGNORECASE)


def insert_voltage_hint(gi: str, voltage_hint: str) -> str:
    """Sisipkan hint voltage (mis. '500KV') tepat setelah prefix
    GI/GIS/GITET/GISTET, meniru pola raw_gi asli di sheet lain ('GITET
    500KV BALARAJA') -- BUKAN di akhir string, krn normalized_gi()
    (load.py) mendeteksi voltage dari pola '<prefix> <NNN>KV <nama>'.
    Kalau gi tidak diawali prefix yang dikenal, kembalikan gi apa adanya
    (tidak menebak posisi sisipan)."""
    if not voltage_hint:
        return gi
    match = _GI_PREFIX_WORD.match(gi)
    if not match:
        return gi
    prefix = match.group(1)
    rest = gi[match.end():].strip()
    return f"{prefix} {voltage_hint} {rest}".strip()


def special_candidates(source_dir: Path, observed_at: str) -> list[dict[str, Any]]:
    path = source_dir / UPT_WORKBOOK
    source_hash = sha256(path)
    workbook = load_workbook(path, data_only=True, read_only=False)
    output = []

    fr = workbook["FR_OCR"]
    for row in range(2, fr.max_row + 1):
        if not meaningful(fr.cell(row, 4).value):
            continue
        ct_primary, ct_secondary = clean(fr.cell(row, 77).value), clean(fr.cell(row, 78).value)
        output.append(make_candidate(
            sheet="FR_OCR", row=row, slot="FR_OCR", logical_source="FR_OCR",
            function_type="OCR_GFR", coordination_class="GRADED",
            source_hash=source_hash, observed_at=observed_at,
            ultg=clean(fr.cell(row, 3).value), gi=clean(fr.cell(row, 4).value),
            bay=clean(fr.cell(row, 10).value),
            ct_ratio=f"{ct_primary}/{ct_secondary}" if ct_primary or ct_secondary else "",
            manufacturer=clean(fr.cell(row, 79).value), model=clean(fr.cell(row, 80).value),
            serial_no=clean(fr.cell(row, 81).value), relay_kind=clean(fr.cell(row, 142).value),
            operation_year=clean(fr.cell(row, 143).value),
        ))

    grouped = workbook["CBF&CCP"]
    current_gi = current_bay = current_make_model = current_serial = ""
    current_ratio_kv = ""
    for row in range(8, grouped.max_row + 1):
        if meaningful(grouped.cell(row, 2).value):
            current_gi = clean(grouped.cell(row, 2).value)
        if meaningful(grouped.cell(row, 3).value):
            current_bay = clean(grouped.cell(row, 3).value)
        if meaningful(grouped.cell(row, 4).value):
            current_ratio_kv = ratio_kv_hint(grouped.cell(row, 4).value)
        if meaningful(grouped.cell(row, 6).value):
            current_make_model = clean(grouped.cell(row, 6).value)
        if meaningful(grouped.cell(row, 7).value):
            current_serial = clean(grouped.cell(row, 7).value)
        label = clean(grouped.cell(row, 12).value).upper()
        if not label:
            continue
        function_type = "CBF" if label.startswith("CBF") else "SZP" if label.startswith("SZP") else "CCP" if label.startswith("CCP") else ""
        if not function_type:
            continue
        make, model = split_make_model(current_make_model)
        slot = re.sub(r"\s+", "_", label)
        # gi tanpa embel-embel voltage (mis. 'GITET Balaraja') ambigu di
        # resolve_ss() krn ada opsi 150kV DAN 500kV utk nama serupa (lihat
        # load.py RAW_GI_OVERRIDE/MANUAL_SUBSTATIONS -- kasus yang sama
        # persis menimpa raw_gi eksplisit 'GITET 500KV BALARAJA' di sheet
        # lain). Kolom 'RATIO (kV)' di sheet ini sbnrnya rasio CT (mis.
        # '500000/100'), BUKAN kV langsung -- tapi primary rating CT
        # diskalakan mengikuti level tegangan pemasangan (dikonfirmasi
        # pemilik data), jadi dipakai sbg sinyal voltage tambahan pada gi.
        #
        # Hint HARUS disisipkan setelah prefix GI/GIS/GITET/GISTET, bukan
        # di akhir string -- normalized_gi() (load.py) cuma mendeteksi
        # voltage dari pola '<PREFIX> <NNN>KV <nama>' (spt raw_gi asli di
        # sheet lain, mis. 'GITET 500KV BALARAJA'), bukan '<nama> <NNN>KV'
        # di akhir (itu malah ikut jadi bagian nama & gagal match).
        gi_with_hint = insert_voltage_hint(current_gi, current_ratio_kv)
        output.append(make_candidate(
            sheet="CBF&CCP", row=row, slot=slot, logical_source="CBF&CCP",
            function_type=function_type, coordination_class="AUXILIARY",
            source_hash=source_hash, observed_at=observed_at,
            gi=gi_with_hint, bay=current_bay, manufacturer=make, model=model,
            serial_no=current_serial, relay_role=slot,
        ))
    return output


def cell_formula_metadata(sheet, row: int, column: int) -> tuple[int, str]:
    value = sheet.cell(row, column).value
    if isinstance(value, ArrayFormula):
        formula = clean(value.text)
    elif sheet.cell(row, column).data_type == "f":
        formula = clean(value)
    else:
        return 0, ""
    return 1, hashlib.sha256(formula.encode("utf-8")).hexdigest()


def parameter_parts(source_header: str) -> list[str]:
    parts = [part.strip() for part in source_header.split(" > ") if part.strip()]
    result = []
    for part in parts:
        upper = re.sub(r"\s+", " ", part.upper()).strip()
        if upper in GENERIC_HEADER_PARTS or upper.startswith("SOURCE : FORM IMPLEMENTASI"):
            continue
        result.append(part)
    return result


def parameter_and_unit(source_header: str, column: int, sheet_name: str = "") -> tuple[str, str]:
    parts = parameter_parts(source_header)
    parameter = PARAMETER_OVERRIDES.get(
        (sheet_name, column), " > ".join(parts) if parts else f"COLUMN_{get_column_letter(column)}")
    unit = ""
    match = re.search(r"\s*\((A|MA|MS|S|PU|V|KV|OHM|Ω|DEG)\)\s*$", parameter, re.I)
    if match:
        unit = match.group(1).replace("Ω", "ohm")
        parameter = parameter[:match.start()].strip()
    return parameter, unit


def setting_rows(source_dir: Path, candidates: list[dict[str, Any]], observed_at: str) -> list[dict[str, Any]]:
    path = source_dir / UPT_WORKBOOK
    source_hash = sha256(path)
    values = load_workbook(path, data_only=True, read_only=False)
    formulas = load_workbook(path, data_only=False, read_only=False)
    candidates_by_sheet_row_slot = {
        candidate_ref(row["source_sheet"], row["source_row"], row["device_slot"]): row
        for row in candidates
    }
    output = []
    for (sheet_name, slot), ranges in SETTING_RANGES.items():
        sheet, formula_sheet, config = values[sheet_name], formulas[sheet_name], UPT_SHEETS[sheet_name]
        for row_number in range(config.data_start or 1, sheet.max_row + 1):
            ref = candidate_ref(sheet_name, row_number, slot)
            if ref not in candidates_by_sheet_row_slot:
                continue
            for block in ranges:
                source_doc = clean(sheet.cell(row_number, block.source_doc_column).value) if block.source_doc_column else ""
                effective_date = clean(sheet.cell(row_number, block.date_column).value) if block.date_column else ""
                for column in range(block.start, block.end + 1):
                    if column in block.exclude:
                        continue
                    value = sheet.cell(row_number, column).value
                    if value is None or clean(value) == "":
                        continue
                    source_header = header_path(sheet, column, config.header_rows)
                    parameter, unit = parameter_and_unit(source_header, column, sheet_name)
                    formula_present, formula_hash = cell_formula_metadata(formula_sheet, row_number, column)
                    output.append({
                        "candidate_ref": ref, "source_workbook": UPT_WORKBOOK,
                        "source_sheet": sheet_name, "source_row": row_number,
                        "source_column": get_column_letter(column), "source_header": source_header,
                        "source_formula_present": formula_present, "source_formula_hash": formula_hash,
                        "source_hash": source_hash, "observed_at": observed_at,
                        "setting_group": block.group, "parameter_name": parameter,
                        "parameter_value": clean(value), "unit": unit,
                        "effective_date": effective_date, "source_doc": source_doc,
                        "is_current": 1,
                    })

    # Current is resolved per candidate/parameter: installed SET_RELAY wins;
    # TAP_SET remains current only when no installed counterpart exists.
    installed = {
        (row["candidate_ref"], row["parameter_name"])
        for row in output if row["setting_group"] == "SET_RELAY"
    }
    for row in output:
        if row["setting_group"] == "TAP_SET" and (row["candidate_ref"], row["parameter_name"]) in installed:
            row["is_current"] = 0
    output.sort(key=lambda row: (
        row["source_sheet"], int(row["source_row"]), row["candidate_ref"],
        row["setting_group"], row["source_column"],
    ))
    return output


def special_setting_rows(source_dir: Path, candidates: list[dict[str, Any]], observed_at: str) -> list[dict[str, Any]]:
    path = source_dir / UPT_WORKBOOK
    source_hash = sha256(path)
    values = load_workbook(path, data_only=True, read_only=False)
    formulas = load_workbook(path, data_only=False, read_only=False)
    refs = {row["candidate_ref"] for row in candidates}
    output = []

    fr, fr_formula = values["FR_OCR"], formulas["FR_OCR"]
    for row in range(2, fr.max_row + 1):
        ref = candidate_ref("FR_OCR", row, "FR_OCR")
        if ref not in refs:
            continue
        for column in range(column_index_from_string("CD"), column_index_from_string("CO") + 1):
            value = fr.cell(row, column).value
            if value is None or clean(value) == "":
                continue
            formula_present, formula_hash = cell_formula_metadata(fr_formula, row, column)
            header = clean(fr.cell(1, column).value)
            output.append({
                "candidate_ref": ref, "source_workbook": UPT_WORKBOOK, "source_sheet": "FR_OCR",
                "source_row": row, "source_column": get_column_letter(column), "source_header": header,
                "source_formula_present": formula_present, "source_formula_hash": formula_hash,
                "source_hash": source_hash, "observed_at": observed_at, "setting_group": "SETTING",
                "parameter_name": header, "parameter_value": clean(value), "unit": "",
                "effective_date": clean(fr.cell(row, column_index_from_string("EJ")).value),
                "source_doc": clean(fr.cell(row, column_index_from_string("EK")).value), "is_current": 1,
            })

    grouped, grouped_formula = values["CBF&CCP"], formulas["CBF&CCP"]
    active_ref = ""
    for row in range(8, grouped.max_row + 1):
        label = clean(grouped.cell(row, 12).value).upper()
        if label:
            active_ref = candidate_ref("CBF&CCP", row, re.sub(r"\s+", "_", label))
        if active_ref not in refs:
            continue
        parameter, value = clean(grouped.cell(row, 8).value), grouped.cell(row, 10).value
        if not parameter or value is None or clean(value) == "":
            continue
        formula_present, formula_hash = cell_formula_metadata(grouped_formula, row, 10)
        output.append({
            "candidate_ref": active_ref, "source_workbook": UPT_WORKBOOK,
            "source_sheet": "CBF&CCP", "source_row": row, "source_column": "J",
            "source_header": f"SETTING > {parameter}", "source_formula_present": formula_present,
            "source_formula_hash": formula_hash, "source_hash": source_hash, "observed_at": observed_at,
            "setting_group": "SETTING", "parameter_name": parameter,
            "parameter_value": clean(value), "unit": "", "effective_date": "",
            "source_doc": "", "is_current": 1,
        })
    return output


def run(source_dir: Path, output_dir: Path, observed_at: str | None = None) -> dict[str, Any]:
    observed_at = observed_at or dt.date.today().isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    v2a_dir = output_dir / "profile"
    profiled = profile(source_dir, v2a_dir, observed_at=observed_at)
    candidates = profiled["candidates"] + special_candidates(source_dir, observed_at)
    for row in candidates:
        row["candidate_ref"] = candidate_ref(row["source_sheet"], row["source_row"], row["device_slot"])
    candidates.sort(key=lambda row: (row["source_sheet"], int(row["source_row"]), row["device_slot"]))
    settings = setting_rows(source_dir, candidates, observed_at)
    settings.extend(special_setting_rows(source_dir, candidates, observed_at))
    settings.sort(key=lambda row: (row["source_sheet"], int(row["source_row"]), row["source_column"]))

    reviews = [row for row in profiled["reviews"] if row["review_type"] != "SPECIAL_LAYOUT_PARSER"]
    existing_conflicts = {row["identity_key"] for row in reviews
                          if row["review_type"] == "IDENTITY_METADATA_CONFLICT"}
    base_refs = {row["candidate_ref"] for row in profiled["candidates"]}
    for row in candidates:
        if row["candidate_ref"] not in base_refs and row["identity_confidence"] == "LOW":
            reviews.append({
                "review_type": "LOW_IDENTITY_CONFIDENCE", "source_ref": row["candidate_ref"],
                "identity_key": row["identity_key"], "logical_source": row["logical_source"],
                "detail": "Special-layout candidate has incomplete exact identity attributes.",
                "recommended_action": "Keep separate unless an authoritative exact identifier is found.",
            })
    for overlap in overlap_rows(candidates):
        if overlap["metadata_conflict"] == "YES" and overlap["identity_key"] not in existing_conflicts:
            reviews.append({
                "review_type": "IDENTITY_METADATA_CONFLICT", "source_ref": overlap["source_refs"],
                "identity_key": overlap["identity_key"], "logical_source": "",
                "detail": overlap["conflict_detail"],
                "recommended_action": "Verify source rows; do not link until conflict is resolved.",
            })
    reviews.sort(key=lambda row: (row["review_type"], row["source_ref"], row["identity_key"]))

    candidate_fields = [
        "candidate_ref", "source_workbook", "source_sheet", "source_row", "source_hash", "observed_at",
        "logical_source", "device_slot", "function_type", "coordination_class", "asset_id", "ultg",
        "gi", "bay", "circuit", "ct_ratio", "pt_ratio", "relay_role", "manufacturer", "model",
        "serial_no", "relay_kind", "operation_year", "status", "identity_key", "identity_confidence",
        "identity_rule",
    ]
    write_csv(output_dir / "relay_candidates.csv", candidates, candidate_fields)
    write_csv(output_dir / "relay_settings.csv", settings, [
        "candidate_ref", "source_workbook", "source_sheet", "source_row", "source_column",
        "source_header", "source_formula_present", "source_formula_hash", "source_hash", "observed_at", "setting_group",
        "parameter_name", "parameter_value", "unit", "effective_date", "source_doc", "is_current",
    ])
    # Reuse already profiled, normalized official events; special-layout parser
    # reviews are replaced by concrete candidates/settings above.
    (output_dir / "official_events.csv").write_bytes((v2a_dir / "official_events.csv").read_bytes())
    write_csv(output_dir / "review_queue.csv", reviews, [
        "review_type", "source_ref", "identity_key", "logical_source", "detail", "recommended_action",
    ])

    with_settings = len({row["candidate_ref"] for row in settings})
    report = f"""# PLMS v2b — long-form extraction report

Generated read-only on `{observed_at}`. Database loading is a separate atomic step.

- Relay candidate source rows/device slots: **{len(candidates)}**
- Candidates with at least one parsed setting: **{with_settings}**
- Long-form setting values: **{len(settings)}**
- Candidate-local current values before cross-source identity merge: **{sum(int(row['is_current']) for row in settings)}**
- Official events retained: **{len(profiled['events'])}**
- Special layouts parsed: **FR_OCR wide form + CBF&CCP grouped rows**
- All setting values carry workbook, sheet, row, column, flattened header, source hash, and observation date.
"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return {**profiled, "settings": settings, "candidates": candidates}


def main(argv: list[str]) -> int:
    source_dir = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    output_dir = Path(argv[2]).resolve() if len(argv) > 2 else source_dir / "v2b_out"
    result = run(source_dir, output_dir)
    print(f"v2b extraction written to {output_dir}")
    print(f"{len(result['candidates'])} candidates; {len(result['settings'])} settings; "
          f"{len(result['events'])} official events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
