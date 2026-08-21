#!/usr/bin/env python3
"""Tests for the read-only v2a source profiler."""

from pathlib import Path

import pytest

from plms_v2_profile import (
    OFFICIAL_SHEETS,
    UPT_SHEETS,
    identity_for,
    norm_serial,
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
    assert sum(row["coordination_class"] == "REVIEW" for row in candidates) == 18
    assert all(row["source_hash"] and row["source_row"] for row in candidates)
    conflicts = [row for row in real_profile["overlaps"] if row["metadata_conflict"] == "YES"]
    assert len(conflicts) >= 3
    assert all(row["review_action"] == "REVIEW" for row in conflicts)
    assert all(row["source_refs"] for row in conflicts)
    review_types = {row["review_type"] for row in real_profile["reviews"]}
    assert review_types == {
        "IDENTITY_METADATA_CONFLICT", "LOW_IDENTITY_CONFIDENCE",
        "COORDINATION_CLASS_REVIEW", "SPECIAL_LAYOUT_PARSER",
    }
