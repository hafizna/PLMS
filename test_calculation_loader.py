#!/usr/bin/env python3
"""Test calculation_loader.py dgn fixture SQLite in-memory kecil (schema
asli dari schema.sql, data minimal buatan) -- lebih cepat & terisolasi
drpd bergantung workbook Excel nyata spt test_plms_integration.py."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import calculation_loader
from calculation_loader import (
    STATUS_AMBIGUOUS_BRANCH,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE_EXTERNAL,
    STATUS_INCOMPLETE_TOPOLOGY,
    _parse_ratio_pair,
    _resolve_ct_pt_ratio,
    build_remote_branches,
    build_two_hop_branches,
    compute_relay_function_zones,
    persist_calculation_context,
    remote_endpoint,
    resolve_line_impedance,
)
from scanning_reference_loader import ScanningTimers

ROOT = Path(__file__).resolve().parent


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript((ROOT / "schema.sql").read_text())
    yield connection
    connection.close()


def _insert_site_ss(conn, name, voltage_kv=150.0):
    site_id = conn.execute("INSERT INTO site (site_name) VALUES (?)", (name,)).lastrowid
    ss_id = conn.execute(
        "INSERT INTO substation (site_id, voltage_kv, in_scope, hop_distance) VALUES (?, ?, 1, 0)",
        (site_id, voltage_kv),
    ).lastrowid
    return ss_id


def _insert_line(conn, name, ss_from, ss_to, r1=0.3591, x1=2.63655, r0=1.7766, x0=7.90965, length_km=9.45):
    line_id = conn.execute(
        """INSERT INTO line (line_name, ss_from, ss_to, voltage_kv, source)
           VALUES (?, ?, ?, 150.0, 'DIGSILENT')""",
        (name, ss_from, ss_to),
    ).lastrowid
    conn.execute(
        """INSERT INTO line_electrical (line_id, length_km, r1_ohm, x1_ohm, r0_ohm, x0_ohm)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (line_id, length_km, r1, x1, r0, x0),
    )
    return line_id


def _insert_dist_relay(conn, ss_id, line_id, ct_ratio="2000/1", pt_ratio="150 kV/100 V"):
    relay_id = conn.execute(
        """INSERT INTO relay (ss_id, line_id, ct_ratio, pt_ratio, identity_key,
                              identity_confidence, identity_status)
           VALUES (?, ?, ?, ?, ?, 'HIGH', 'EXACT')""",
        (ss_id, line_id, ct_ratio, pt_ratio, f"TEST|{ss_id}|{line_id}"),
    ).lastrowid
    rf_id = conn.execute(
        """INSERT INTO relay_function (relay_id, function_type, coordination_class, source_logical)
           VALUES (?, 'DIST', 'GRADED', 'LCD+DIST')""",
        (relay_id,),
    ).lastrowid
    return rf_id


# ------------------------------------------------------- ratio parsing

def test_parse_ratio_pair_handles_plain_ct_format():
    assert _parse_ratio_pair("2000/1") == (2000.0, 1.0)
    assert _parse_ratio_pair("1000 / 5") == (1000.0, 5.0)
    assert _parse_ratio_pair("4000.0/5.0") == (4000.0, 5.0)


def test_parse_ratio_pair_handles_pt_format_with_units():
    # '150 kV/100 V' -- satuan literal, bukan cuma spasi.
    assert _parse_ratio_pair("150 kV/100 V") == (150.0, 100.0)
    assert _parse_ratio_pair("500 kV/100 V") == (500.0, 100.0)


def test_parse_ratio_pair_returns_none_for_unrecognized_format():
    assert _parse_ratio_pair(None) is None
    assert _parse_ratio_pair("") is None
    assert _parse_ratio_pair("garbage") is None
    assert _parse_ratio_pair("1/2/3") is None


def test_resolve_ct_pt_ratio_n1_matches_mathcad_reference():
    # Regresi kritis yg sempat terjadi: pt_primary_kv dibagi 1000 lagi
    # di _resolve_ct_pt_ratio() PADAHAL CtPtRatio.n1 sudah mengalikan
    # *1000 sendiri -- dobel konversi bikin n1 salah 1.000.000x lipat.
    # '150 kV/100 V' parse jadi (150.0, 100.0) -- 150 SUDAH dlm satuan
    # kV (bukan raw volt), harus diteruskan apa adanya ke pt_primary_kv.
    ratio = _resolve_ct_pt_ratio("2000/1", "150 kV/100 V")
    assert ratio is not None
    assert ratio.n1 == pytest.approx(1.333333333, rel=1e-6)


def test_resolve_ct_pt_ratio_none_when_either_side_unparseable():
    assert _resolve_ct_pt_ratio(None, "150 kV/100 V") is None
    assert _resolve_ct_pt_ratio("2000/1", None) is None
    assert _resolve_ct_pt_ratio("garbage", "150 kV/100 V") is None


# ------------------------------------------------------- line impedance

def test_resolve_line_impedance_returns_none_when_missing(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    # Line tanpa line_electrical (spt UPT_MANUAL) -- INI adalah titik
    # incomplete_topology, bukan bug.
    line_id = conn.execute(
        "INSERT INTO line (line_name, ss_from, ss_to, source) VALUES ('A-B', ?, ?, 'UPT_MANUAL')",
        (ss_a, ss_b),
    ).lastrowid
    assert resolve_line_impedance(conn, line_id) is None


def test_resolve_line_impedance_returns_value_when_present(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    line_id = _insert_line(conn, "A-B", ss_a, ss_b)
    impedance = resolve_line_impedance(conn, line_id)
    assert impedance is not None
    assert impedance.r1_ohm == pytest.approx(0.3591)
    assert impedance.x1_ohm == pytest.approx(2.63655)


# ------------------------------------------------------------ traversal

def test_remote_endpoint_returns_the_other_side(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    line_id = _insert_line(conn, "A-B", ss_a, ss_b)
    assert remote_endpoint(conn, line_id, ss_a) == ss_b
    assert remote_endpoint(conn, line_id, ss_b) == ss_a


def test_build_remote_branches_excludes_protected_line_and_missing_electrical(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")  # remote bus
    ss_c = _insert_site_ss(conn, "C")
    ss_d = _insert_site_ss(conn, "D")
    protected = _insert_line(conn, "A-B", ss_a, ss_b)
    branch_ok = _insert_line(conn, "B-C", ss_b, ss_c)
    # B-D tanpa line_electrical -- harus DILEWATI, bukan dipaksa masuk.
    conn.execute(
        "INSERT INTO line (line_name, ss_from, ss_to, source) VALUES ('B-D', ?, ?, 'UPT_MANUAL')",
        (ss_b, ss_d),
    )

    branches = build_remote_branches(conn, ss_b, exclude_line_id=protected)
    assert len(branches) == 1
    assert branches[0].line_id == branch_ok


def test_build_two_hop_branches_excludes_lines_looping_back_to_remote_bus(conn):
    # Topologi: A-B (protected) -> B-C (1-hop) -> C-D (2-hop genuine)
    #                                          -> C-B-2 (loop balik ke
    #                                             remote bus, HARUS
    #                                             dikecualikan dari
    #                                             kandidat 2-hop).
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")  # remote bus
    ss_c = _insert_site_ss(conn, "C")  # ujung jauh 1-hop
    ss_d = _insert_site_ss(conn, "D")  # ujung jauh 2-hop genuinely baru
    protected = _insert_line(conn, "A-B", ss_a, ss_b)
    first_hop = _insert_line(conn, "B-C", ss_b, ss_c)
    two_hop_line = _insert_line(conn, "C-D", ss_c, ss_d)
    cyclic_line = _insert_line(conn, "C-B-2", ss_c, ss_b)

    one_hop = build_remote_branches(conn, ss_b, exclude_line_id=protected)
    # Baik B-C maupun C-B-2 sama-sama nempel remote bus -- keduanya sah
    # jadi kandidat 1-hop TERSENDIRI (perspektif 1-hop tidak peduli arah
    # penulisan ss_from/ss_to).
    assert {b.line_id for b in one_hop} == {first_hop, cyclic_line}

    two_hop = build_two_hop_branches(conn, ss_b, exclude_line_id=protected, one_hop_branches=one_hop)
    # Dari KEDUA 1-hop tsb, ujung jauhnya (dilihat dari remote_ss_id=ss_b)
    # adalah ss_c yang sama -- kandidat 2-hop yg valid dari ss_c cuma
    # C-D. C-B-2 (baik sbg 1-hop MAUPUN sbg kandidat 2-hop dari 1-hop
    # lain) tidak boleh muncul sbg second_hop_line_id krn itu artinya
    # traversal balik ke remote bus (siklus 2-line).
    assert len(two_hop) == 2  # satu kandidat 2-hop per 1-hop, keduanya ke C-D
    assert {b.first_hop_line_id for b in two_hop} == {first_hop, cyclic_line}
    assert all(b.second_hop_line_id == two_hop_line for b in two_hop)
    assert all(b.second_hop_line_id != cyclic_line for b in two_hop)


# --------------------------------------------------- compute_relay_function_zones

def test_compute_zones_z1_complete_when_topology_and_ratio_available(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    line_id = _insert_line(conn, "A-B", ss_a, ss_b)
    rf_id = _insert_dist_relay(conn, ss_a, line_id)

    results = compute_relay_function_zones(conn, rf_id)
    z1 = next(r for r in results if r.zone == "Z1")
    assert z1.status == STATUS_COMPLETE
    assert z1.result is not None
    assert z1.result.reach_percent == pytest.approx(80.0, rel=1e-4)


def test_compute_zones_incomplete_topology_when_no_line_electrical(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    line_id = conn.execute(
        "INSERT INTO line (line_name, ss_from, ss_to, source) VALUES ('A-B', ?, ?, 'UPT_MANUAL')",
        (ss_a, ss_b),
    ).lastrowid
    rf_id = _insert_dist_relay(conn, ss_a, line_id)

    results = compute_relay_function_zones(conn, rf_id)
    assert all(r.status == STATUS_INCOMPLETE_TOPOLOGY for r in results)
    assert all(r.result is None for r in results)


def test_compute_zones_incomplete_topology_when_ratio_unparseable(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    line_id = _insert_line(conn, "A-B", ss_a, ss_b)
    rf_id = _insert_dist_relay(conn, ss_a, line_id, ct_ratio="garbage", pt_ratio="garbage")

    results = compute_relay_function_zones(conn, rf_id)
    assert all(r.status == STATUS_INCOMPLETE_TOPOLOGY for r in results)


def test_compute_zones_incomplete_external_when_remote_bus_is_boundary(conn):
    # Line dgn ss_to NULL (topology_source hilang di ujung remote) --
    # graph berhenti secara desain, beda status dari topologi hilang.
    ss_a = _insert_site_ss(conn, "A")
    line_id = conn.execute(
        """INSERT INTO line (line_name, ss_from, ss_to, voltage_kv, source, is_boundary)
           VALUES ('A-boundary', ?, NULL, 150.0, 'DIGSILENT', 1)""",
        (ss_a,),
    ).lastrowid
    conn.execute(
        "INSERT INTO line_electrical (line_id, r1_ohm, x1_ohm, r0_ohm, x0_ohm) VALUES (?, 0.36, 2.64, 1.78, 7.91)",
        (line_id,),
    )
    rf_id = _insert_dist_relay(conn, ss_a, line_id)

    results = compute_relay_function_zones(conn, rf_id)
    z1 = next(r for r in results if r.zone == "Z1")
    z2 = next(r for r in results if r.zone == "Z2")
    z3 = next(r for r in results if r.zone == "Z3")
    assert z1.status == STATUS_COMPLETE  # Z1 tidak butuh remote bus sama sekali
    assert z2.status == STATUS_INCOMPLETE_EXTERNAL
    assert z3.status == STATUS_INCOMPLETE_EXTERNAL


def test_compute_zones_z2_z3_incomplete_topology_without_transformer_data(conn):
    # Keputusan pemilik data: tanpa XT1 (data trafo, TIDAK ADA di
    # plms.db sama sekali saat ini), Z2/Z3 TIDAK dihitung tanpa cap --
    # harus incomplete_topology, BUKAN dihitung dgn asumsi tanpa cap.
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    ss_c = _insert_site_ss(conn, "C")
    protected = _insert_line(conn, "A-B", ss_a, ss_b)
    _insert_line(conn, "B-C", ss_b, ss_c)  # ada cabang 1-hop, tapi trafo tetap tidak ada
    rf_id = _insert_dist_relay(conn, ss_a, protected)

    results = compute_relay_function_zones(conn, rf_id)
    z2 = next(r for r in results if r.zone == "Z2")
    z3 = next(r for r in results if r.zone == "Z3")
    assert z2.status == STATUS_INCOMPLETE_TOPOLOGY
    assert z3.status == STATUS_INCOMPLETE_TOPOLOGY
    assert z2.result is None
    assert z3.result is None


def test_compute_zones_missing_relay_function_returns_incomplete_topology(conn):
    results = compute_relay_function_zones(conn, relay_function_id=999999)
    assert all(r.status == STATUS_INCOMPLETE_TOPOLOGY for r in results)
    assert all(r.result is None for r in results)


# ------------------------------------------ integrasi T3 (scanning_reference)
# Z2/Z3 saat ini SELALU incomplete_topology krn data trafo (XT1) TIDAK
# ADA sama sekali (keputusan pemilik data: jangan hitung tanpa cap).
# Test di sini monkeypatch resolve_transformer_reactance() SUPAYA jalur
# Z3 tereksekusi -- membuktikan wiring scanning_timers->delay_s benar,
# TERPISAH dari keputusan "no XT1 = incomplete_topology" (yang sudah
# diuji test_compute_zones_z2_z3_incomplete_topology_without_transformer_
# data di atas, dan TIDAK diubah oleh integrasi T3 ini).

def test_compute_zones_z3_uses_scanning_timer_when_transformer_data_available(conn, monkeypatch):
    monkeypatch.setattr(calculation_loader, "resolve_transformer_reactance", lambda conn, ss_id: 5.85)

    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    protected = _insert_line(conn, "A-B", ss_a, ss_b)
    rf_id = _insert_dist_relay(conn, ss_a, protected)

    scanning_timers = {protected: ScanningTimers(
        file_id="fake", line_label="LINE 1", z1_time_s=0.0, z2_time_s=0.4, z3_time_s=1.6,
    )}
    results = compute_relay_function_zones(conn, rf_id, scanning_timers=scanning_timers)
    z3 = next(r for r in results if r.zone == "Z3")
    assert z3.status == STATUS_COMPLETE
    assert z3.result.delay_s == 1.6


def test_compute_zones_z3_stays_ambiguous_when_line_not_in_scanning_timers(conn, monkeypatch):
    monkeypatch.setattr(calculation_loader, "resolve_transformer_reactance", lambda conn, ss_id: 5.85)

    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    protected = _insert_line(conn, "A-B", ss_a, ss_b)
    rf_id = _insert_dist_relay(conn, ss_a, protected)

    # scanning_timers TIDAK py entry utk protected line_id ini -- reach
    # tetap valid dihitung, T3 genuinely tidak tersedia (bukan ditebak).
    results = compute_relay_function_zones(conn, rf_id, scanning_timers={})
    z3 = next(r for r in results if r.zone == "Z3")
    assert z3.status == STATUS_AMBIGUOUS_BRANCH
    assert z3.result is not None  # reach tetap dihitung
    assert z3.result.delay_s is None


def test_compute_zones_z3_without_scanning_timers_argument_defaults_to_ambiguous(conn, monkeypatch):
    # scanning_timers=None (default parameter) harus berperilaku sama
    # persis dgn dict kosong -- tidak boleh crash krn None.
    monkeypatch.setattr(calculation_loader, "resolve_transformer_reactance", lambda conn, ss_id: 5.85)
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    protected = _insert_line(conn, "A-B", ss_a, ss_b)
    rf_id = _insert_dist_relay(conn, ss_a, protected)

    results = compute_relay_function_zones(conn, rf_id)
    z3 = next(r for r in results if r.zone == "Z3")
    assert z3.status == STATUS_AMBIGUOUS_BRANCH
    assert z3.result.delay_s is None


# ------------------------------------------------------ persist_calculation_context

def test_z3_trace_keeps_two_hops_when_first_impedance_and_transformer_are_missing(conn):
    a, b, c, d = [_insert_site_ss(conn, name) for name in "ABCD"]
    protected = _insert_line(conn, "A-B", a, b)
    first = _insert_line(conn, "B-C", b, c)
    second = _insert_line(conn, "C-D", c, d)
    conn.execute("DELETE FROM line_electrical WHERE line_id=?", (first,))
    rf = _insert_dist_relay(conn, a, protected)
    zones = {r.zone: r for r in compute_relay_function_zones(conn, rf)}
    assert {t[0] for t in zones["Z2"].branch_trace} == {first}
    assert {t[0] for t in zones["Z3"].branch_trace} == {first, second}
    assert all("line_electrical" in t[2] for t in zones["Z3"].branch_trace)
    assert f"path={first}>{second}" in zones["Z3"].branch_trace[-1][2]
    assert zones["Z3"].result is None


def test_missing_remote_impedance_blocks_reach_even_when_xt1_available(conn, monkeypatch):
    monkeypatch.setattr(calculation_loader, "resolve_transformer_reactance", lambda *args: 5.85)
    a, b, c = [_insert_site_ss(conn, name) for name in "ABC"]
    protected = _insert_line(conn, "A-B", a, b)
    missing = _insert_line(conn, "B-C", b, c)
    conn.execute("DELETE FROM line_electrical WHERE line_id=?", (missing,))
    rf = _insert_dist_relay(conn, a, protected)
    zones = {r.zone: r for r in compute_relay_function_zones(conn, rf)}
    assert zones["Z1"].status == STATUS_COMPLETE
    assert all(zones[z].result is None for z in ("Z2", "Z3"))


def test_two_hop_gap_blocks_only_z3(conn, monkeypatch):
    monkeypatch.setattr(calculation_loader, "resolve_transformer_reactance", lambda *args: 5.85)
    a, b, c, d = [_insert_site_ss(conn, name) for name in "ABCD"]
    protected = _insert_line(conn, "A-B", a, b)
    _insert_line(conn, "B-C", b, c)
    missing = _insert_line(conn, "C-D", c, d)
    conn.execute("DELETE FROM line_electrical WHERE line_id=?", (missing,))
    rf = _insert_dist_relay(conn, a, protected)
    zones = {r.zone: r for r in compute_relay_function_zones(conn, rf)}
    assert zones["Z2"].status == STATUS_COMPLETE
    assert zones["Z3"].status == STATUS_INCOMPLETE_TOPOLOGY
    assert zones["Z3"].result is None


def test_forward_paths_exclude_return_to_local_and_out_of_service(conn):
    a, b, c, d = [_insert_site_ss(conn, name) for name in "ABCD"]
    protected = _insert_line(conn, "A-B", a, b)
    _insert_line(conn, "A-B 2", a, b)
    forward = _insert_line(conn, "B-C", b, c)
    _insert_line(conn, "C-A", c, a)
    off = _insert_line(conn, "B-D", b, d)
    conn.execute("UPDATE line SET out_of_service=1 WHERE line_id=?", (off,))
    one = build_remote_branches(conn, b, protected)
    assert [p.line_id for p in one] == [forward]
    assert build_two_hop_branches(conn, b, protected, one) == []
    assert [p["line_id"] for p in calculation_loader.topology_branch_paths(conn, b, protected)] == [forward]

def test_persist_writes_one_row_per_zone_with_expected_fields(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    line_id = _insert_line(conn, "A-B", ss_a, ss_b)
    rf_id = _insert_dist_relay(conn, ss_a, line_id)

    results = compute_relay_function_zones(conn, rf_id)
    written = persist_calculation_context(conn, rf_id, line_id, results)
    assert written == 3

    rows = {r["zone"]: r for r in conn.execute(
        "SELECT * FROM calculation_context WHERE relay_function_id = ?", (rf_id,)
    ).fetchall()}
    assert set(rows) == {"Z1", "Z2", "Z3"}
    z1 = rows["Z1"]
    assert z1["status"] == STATUS_COMPLETE
    assert z1["reach_percent"] == pytest.approx(80.0, rel=1e-4)
    assert z1["cumulative_r_ohm"] == pytest.approx(0.28728, rel=1e-4)
    assert z1["cumulative_x_ohm"] == pytest.approx(2.10924, rel=1e-4)
    assert z1["delay_s"] == 0.0
    # Z2/Z3 tanpa data trafo -- semua field numerik NULL, bukan 0/tebakan.
    assert rows["Z2"]["status"] == STATUS_INCOMPLETE_TOPOLOGY
    assert rows["Z2"]["cumulative_r_ohm"] is None
    assert rows["Z3"]["status"] == STATUS_INCOMPLETE_TOPOLOGY
    assert rows["Z3"]["cumulative_r_ohm"] is None


def test_persist_writes_branch_trace_with_selection_flag(conn, monkeypatch):
    monkeypatch.setattr(calculation_loader, "resolve_transformer_reactance", lambda conn, ss_id: 5.85)

    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    ss_c = _insert_site_ss(conn, "C")
    protected = _insert_line(conn, "A-B", ss_a, ss_b)
    branch = _insert_line(conn, "B-C", ss_b, ss_c)
    rf_id = _insert_dist_relay(conn, ss_a, protected)

    results = compute_relay_function_zones(conn, rf_id)
    persist_calculation_context(conn, rf_id, protected, results)

    z2_context = conn.execute(
        "SELECT context_id, selected_branch_line_id FROM calculation_context WHERE relay_function_id=? AND zone='Z2'",
        (rf_id,),
    ).fetchone()
    assert z2_context["selected_branch_line_id"] == branch

    branches = conn.execute(
        "SELECT line_id, is_selected, branch_status FROM calculation_branch WHERE context_id=?",
        (z2_context["context_id"],),
    ).fetchall()
    assert len(branches) == 1
    assert branches[0]["line_id"] == branch
    assert branches[0]["is_selected"] == 1
    assert branches[0]["branch_status"] == STATUS_COMPLETE


def test_persist_is_idempotent_on_rerun(conn):
    ss_a = _insert_site_ss(conn, "A")
    ss_b = _insert_site_ss(conn, "B")
    line_id = _insert_line(conn, "A-B", ss_a, ss_b)
    rf_id = _insert_dist_relay(conn, ss_a, line_id)

    results = compute_relay_function_zones(conn, rf_id)
    persist_calculation_context(conn, rf_id, line_id, results)
    persist_calculation_context(conn, rf_id, line_id, results)
    persist_calculation_context(conn, rf_id, line_id, results)

    count = conn.execute(
        "SELECT COUNT(*) FROM calculation_context WHERE relay_function_id = ?", (rf_id,)
    ).fetchone()[0]
    assert count == 3, "re-run tidak boleh menduplikasi baris"
