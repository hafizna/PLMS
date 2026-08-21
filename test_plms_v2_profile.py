#!/usr/bin/env python3
"""Tests for the read-only v2a source profiler."""

from pathlib import Path

import pytest

from plms_v2_profile import (
    OFFICIAL_SHEETS,
    UPT_SHEETS,
    identity_for,
    norm_serial,
    overlap_rows,
    profile,
    protection_tokens,
)


ROOT = Path(__file__).resolve().parent


def test_all_physical_and_logical_upt_sources_are_explicitly_mapped():
    assert len(UPT_SHEETS) == 22
    assert {config.logical_source for config in UPT_SHEETS.values()} == {
        "LCD+DIST", "OCR", "OCR KOPEL", "DIFF Pilot", "DV", "BUSPRO", "AR",
        "CBF", "Synchro", "CCP", "SZP", "KAPASITOR", "FR_OCR", "CBF&CCP",
        "Rekap", "Rekap1", "Pivot Table 1",
    }
    assert len(OFFICIAL_SHEETS) == 7


def test_identity_does_not_include_function_type():
    base = {
        "gi": "GI Angke", "bay": "PHT Ancol #1", "manufacturer": "GE",
        "model": "MiCOM P545", "serial_no": "36039274/03/22", "relay_role": "MPU",
    }
    lcd = {**base, "function_type": "LCD"}
    dist = {**base, "function_type": "DIST"}
    assert identity_for(lcd) == identity_for(dist)


def test_serial_normalization_handles_excel_integral_float_only():
    assert norm_serial(3307182.0) == "3307182"
    assert norm_serial("3307182.0") == "3307182"
    assert norm_serial("36039274/03/22") == "36039274/03/22"


def test_missing_serial_uses_exact_non_fuzzy_fallback():
    key, confidence, rule = identity_for({
        "gi": "GI Angke", "bay": "PHT Ancol #1", "manufacturer": "GE",
        "circuit": "#1", "model": "MiCOM P545", "serial_no": "-", "relay_role": "MPU",
    })
    assert key == "ASSET|GI ANGKE|PHT ANCOL #1|#1|GE|MICOM P545|MPU"
    assert confidence == "MEDIUM"
    assert "exact" in rule


def test_official_protection_tokenization_is_transparent():
    assert protection_tokens("DIFF, REF / OCR & SBEF") == ["DIFF", "REF", "OCR", "SBEF"]


# ---------------------------------------------------------- overlap_rows
# Sheet CBF/SZP/CCP mencatat bay CBF sbg nama penghantar yang dilindungi
# ('PHT 500KV LENGKONG'), sheet CBF&CCP mencatat posisi fisik breaker
# ('CUT-OFF 1 DIAMETER 4', 'PMT 5B2') -- konvensi label beda utk breaker
# fisik yang SAMA, bukan konflik data. Terbukti thd workbook nyata: 30/40
# IDENTITY_METADATA_CONFLICT awal persis pola ini (serial cocok 1:1).
# CBF&CCP jg kadang menulis brand-family Siemens ('SIPROTEC 7VK61')
# sementara sheet lain cuma nomor model ('7VK61') -- model fisik sama.

def _candidate(sheet, slot, ftype, gi, bay, mfr, model, serial):
    return dict(identity_key=f"SERIAL|{serial}", identity_confidence="HIGH",
                source_sheet=sheet, device_slot=slot, source_row=1, function_type=ftype,
                gi=gi, bay=bay, manufacturer=mfr, model=model, serial_no=serial)


def test_overlap_rows_bay_diameter_labeling_is_not_a_conflict():
    group = [
        _candidate("CBF", "CBF", "CBF", "GITET 500KV BALARAJA", "PHT 500KV LENGKONG", "NR", "RCS-921", "X1"),
        _candidate("CBF&CCP", "CBF_1", "CBF", "GITET 500KV Balaraja", "CUT-OFF 1 DIAMETER 3", "NR", "RCS-921", "X1"),
    ]
    [row] = overlap_rows(group)
    assert row["metadata_conflict"] == "NO"
    assert row["review_action"] == "LINK_EXACT"


def test_overlap_rows_siprotec_model_prefix_is_not_a_conflict():
    group = [
        _candidate("CBF", "CBF", "CBF", "GITET 500KV BALARAJA", "IBT", "Siemens", "7VK61", "X2"),
        _candidate("CBF&CCP", "CBF_1", "CBF", "GITET 500KV Balaraja", "Diameter 5", "Siemens", "Siprotec 7VK61", "X2"),
    ]
    [row] = overlap_rows(group)
    assert row["metadata_conflict"] == "NO"


def test_overlap_rows_genuine_manufacturer_model_conflict_still_flagged():
    # Serial sama tapi manufacturer DAN model beneran beda (ALSTOM/P821 vs
    # AREVA/P841) -- bukan sekadar label bay, harus tetap masuk review,
    # tidak boleh ikut lolos hanya krn salah satu sheetnya CBF&CCP.
    group = [
        _candidate("SZP", "SZP", "SZP", "GITET 500KV BALARAJA", "IBT", "Areva", "MiCom P821", "X3"),
        _candidate("CBF&CCP", "CBF_1", "CBF", "GITET 500KV Balaraja", "Diameter 6", "Alstom", "MiCom P841", "X3"),
    ]
    [row] = overlap_rows(group)
    assert row["metadata_conflict"] == "YES"
    assert "manufacturer=ALSTOM <> AREVA" in row["conflict_detail"]
    assert "model=MICOM P821 <> MICOM P841" in row["conflict_detail"]


def test_overlap_rows_bay_conflict_outside_diameter_sheets_still_flagged():
    # Dua bay beda GI sama sekali (CIKUPA vs MAXIMANGANDO), sumbernya
    # DIST/AR (bukan CBF&CCP) -- pola diameter-labeling TIDAK berlaku di
    # sini, harus tetap masuk review (kemungkinan typo/copy-paste sumber).
    group = [
        _candidate("DIST", "DIST", "DIST", "GI 150kV JATAKE", "PHT 150KV CIKUPA#1", "Alstom", "MICOM P442", "X4"),
        _candidate("AR", "AR", "AR", "GI 150kV JATAKE", "PHT 150KV MAXIMANGANDO#1", "Alstom", "MiCom P442", "X4"),
    ]
    [row] = overlap_rows(group)
    assert row["metadata_conflict"] == "YES"
    assert "bay=" in row["conflict_detail"]


@pytest.fixture(scope="module")
def real_profile(tmp_path_factory):
    output = tmp_path_factory.mktemp("v2a")
    return profile(ROOT, output, observed_at="2026-08-21")


def test_real_workbooks_match_v2a_baseline(real_profile):
    assert len(real_profile["sheet_profiles"]) == 29
    assert len(real_profile["logical_sources"]) == 17
    assert len(real_profile["candidates"]) == 1504
    assert len(real_profile["events"]) == 292
    assert len(real_profile["overlaps"]) >= 199


def test_real_profile_keeps_review_items_explicit(real_profile):
    candidates = real_profile["candidates"]
    # 18->0: CAP_UNBALANCE/UVR_OVR (sheet KAPASITOR) diklasifikasi UNIT --
    # proteksi internal ke bank kapasitor sendiri (ANSI 51NC/60, 27/59),
    # bukan grading hulu/hilir antar-GI. Dikonfirmasi literatur (EEP, ABB
    # REV615, SEL-487V) + keputusan domain pemilik data. Lihat komentar
    # KAPASITOR SheetConfig di plms_v2_profile.py.
    assert sum(row["coordination_class"] == "REVIEW" for row in candidates) == 0
    assert all(row["source_hash"] and row["source_row"] for row in candidates)
    conflicts = [row for row in real_profile["overlaps"] if row["metadata_conflict"] == "YES"]
    assert len(conflicts) >= 3
    assert all(row["review_action"] == "REVIEW" for row in conflicts)
    assert all(row["source_refs"] for row in conflicts)
    review_types = {row["review_type"] for row in real_profile["reviews"]}
    # COORDINATION_CLASS_REVIEW tidak lagi muncul: CAP_UNBALANCE/UVR_OVR
    # sudah diklasifikasi UNIT (lihat komentar di atas), bukan REVIEW lagi.
    assert review_types == {
        "IDENTITY_METADATA_CONFLICT", "LOW_IDENTITY_CONFIDENCE",
        "SPECIAL_LAYOUT_PARSER",
    }
