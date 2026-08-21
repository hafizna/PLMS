#!/usr/bin/env python3
"""Test scanning_reference_loader.py -- resolver GI+bay (teks helper
sheet scraping) -> line_id (plms.db), dan parsing timer T1/T2/T3."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scanning_reference_loader import (
    SCANNING_REFERENCE_CSV,
    _clean_scanning_name,
    _parse_time,
    build_line_id_timer_map,
    load_scanning_rows,
)

ROOT = Path(__file__).resolve().parent


# --------------------------------------------------------- name cleaning

def test_clean_scanning_name_strips_circuit_suffix_and_annotations():
    # '#N' dan apapun setelahnya (termasuk anotasi non-data dari proses
    # scraping spt '[dup of LINE1 - GI S same]') harus hilang sebelum
    # normalisasi -- kalau tidak, GI/bay yg sama akan gagal cocok krn
    # teks tambahan itu bukan bagian nama GI.
    assert _clean_scanning_name("KETAPANG #1") == _clean_scanning_name("KETAPANG")
    assert _clean_scanning_name("MUARAKARANG LAMA (OHL) [dup of LINE1 - GI S same]") == _clean_scanning_name("MUARAKARANG LAMA")


def test_clean_scanning_name_strips_technology_marker():
    # '(OHL)'/'(UGC)' adalah penanda jenis teknologi, bukan bagian nama GI.
    assert _clean_scanning_name("ANGKE (OHL)") == _clean_scanning_name("ANGKE")
    assert _clean_scanning_name("MUARAKARANG LAMA (UGC)") == _clean_scanning_name("MUARAKARANG LAMA")


def test_clean_scanning_name_strips_pht_bay_prefix():
    # Kolom bay_r kadang berisi nama bay lengkap 'PHT 150KV <lawan>',
    # bukan cuma nama GI polos -- prefix 'PHT NNNkV' harus hilang
    # (normalized_gi() dari load.py sudah tangani prefix GI/GIS/GITET/
    # GISTET, tapi BUKAN prefix bay 'PHT').
    assert _clean_scanning_name("PHT 150KV ALAM SUTERA") == _clean_scanning_name("ALAM SUTERA")


def test_clean_scanning_name_applies_opponent_alias():
    # 'KARET LAMA' -> 'KARET' via OPPONENT_ALIAS (load.py) -- resolver
    # ini HARUS pakai alias yang sama dgn resolver topologi, bukan
    # daftar alias terpisah/baru.
    assert _clean_scanning_name("KARET LAMA") == "KARET"


# ------------------------------------------------------------ time parsing

def test_parse_time_handles_plain_numbers():
    assert _parse_time("1.600") == pytest.approx(1.6)
    assert _parse_time("0.000") == 0.0


def test_parse_time_returns_none_for_excel_errors_and_empty():
    # Error Excel literal (#DIV/0!, #VALUE!, #REF!, #NAME?) dan sel
    # kosong HARUS jadi None, bukan 0 atau exception -- ini genuinely
    # "tidak diketahui", bukan nol detik.
    assert _parse_time("#DIV/0!") is None
    assert _parse_time("#VALUE!") is None
    assert _parse_time("") is None
    assert _parse_time(None) is None


# --------------------------------------------------------------- CSV data

def test_scanning_reference_csv_exists_and_has_expected_columns():
    assert SCANNING_REFERENCE_CSV.exists(), "scanning_reference.csv harus ada di repo (bukan cuma scratchpad)"
    rows = load_scanning_rows()
    assert len(rows) > 100, "hasil scraping 88 sheet harus menghasilkan >100 baris (referensi: 187)"
    expected_columns = {
        "file_id", "line_label", "gi_r", "bay_r", "gi_s",
        "z1_primary", "z1_secondary", "z1_time",
        "z2_primary", "z2_secondary", "z2_time",
        "z3_primary", "z3_secondary", "z3_time",
    }
    assert expected_columns <= set(rows[0].keys())


def test_scanning_reference_t3_is_not_constant_across_lines():
    # Bukti empiris KENAPA T3 tidak boleh di-hardcode universal: dari
    # data scraping nyata, T3 genuinely bervariasi (1.6s mayoritas, tapi
    # jg ada 1.2s/0.6s/0s) -- kalau suatu saat scraping ulang cuma
    # menghasilkan 1 nilai konstan, itu tanda regresi data/parsing.
    rows = load_scanning_rows()
    distinct_z3 = {r["z3_time"] for r in rows if r["z3_time"]}
    assert len(distinct_z3) > 1


# -------------------------------------------------- build_line_id_timer_map

@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript((ROOT / "schema.sql").read_text())
    yield connection
    connection.close()


def _insert_site_ss(conn, name):
    site_id = conn.execute("INSERT INTO site (site_name) VALUES (?)", (name,)).lastrowid
    return conn.execute(
        "INSERT INTO substation (site_id, voltage_kv, in_scope, hop_distance) VALUES (?, 150.0, 1, 0)",
        (site_id,),
    ).lastrowid


def _insert_line(conn, name, ss_from, ss_to):
    return conn.execute(
        "INSERT INTO line (line_name, ss_from, ss_to, voltage_kv, source) VALUES (?, ?, ?, 150.0, 'DIGSILENT')",
        (name, ss_from, ss_to),
    ).lastrowid


def test_build_line_id_timer_map_matches_known_line_from_real_scraping_data(conn):
    # ANGKE-ANCOL adalah baris pertama scanning_reference.csv (contoh
    # yang sudah diverifikasi manual sepanjang sesi ini): Z1=0.0,
    # Z2=0.4, Z3=1.6.
    ss_angke = _insert_site_ss(conn, "ANGKE")
    ss_ancol = _insert_site_ss(conn, "ANCOL")
    line_id = _insert_line(conn, "ANGKE-ANCOL", ss_angke, ss_ancol)

    timer_map = build_line_id_timer_map(conn)
    assert line_id in timer_map
    timers = timer_map[line_id]
    assert timers.z1_time_s == pytest.approx(0.0)
    assert timers.z2_time_s == pytest.approx(0.4)
    assert timers.z3_time_s == pytest.approx(1.6)


def test_build_line_id_timer_map_skips_lines_not_in_scanning_data(conn):
    ss_x = _insert_site_ss(conn, "GI TAK DIKENAL X")
    ss_y = _insert_site_ss(conn, "GI TAK DIKENAL Y")
    line_id = _insert_line(conn, "X-Y", ss_x, ss_y)

    timer_map = build_line_id_timer_map(conn)
    assert line_id not in timer_map
