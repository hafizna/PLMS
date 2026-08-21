#!/usr/bin/env python3
"""Golden test case untuk distance_engine.py (v3a, Zone-1 saja).

Data & hasil referensi diekstrak dari file Mathcad milik pemilik data:
'MathCAD ABB REL670 Distance.xmcd' (C:\\Users\\hafizna.fadhli\\Downloads),
kalkulasi setting ABB REL670 nyata untuk LINE 150kV LSI-Millenium
(sirkit L1, 9.45 km). Ekstraksi dilakukan via analisis XML terstruktur
(bukan tebakan/derivasi dari buku teks) -- lihat commit message untuk
ringkasan temuan lengkap termasuk anomali yang dicatat (bukan
disembunyikan): trafo remote GI Pati/Kmjng/Millenium memakai XT1 yang
sama persis (dikonfirmasi sisa template lama, diabaikan sesuai
keputusan pemilik data), Ibase tidak konsisten antar fungsi (2000A
mayoritas vs 3000A SOTF vs 1600A BFP1 -- tidak relevan ke Zone-1).

Semua nilai di bawah adalah OUTPUT AKTUAL file Mathcad tsb untuk
kombinasi data saluran L1 + CT/PT ratio yang benar-benar dipakai relay
itu -- toleransi longgar (rel=1e-4) mengakomodasi pembulatan Mathcad
vs floating point Python, bukan ketidakpastian rumus.
"""
import cmath

import pytest

from distance_engine import (
    CtPtRatio,
    LineImpedance,
    Zone1Result,
    calculate_zone1,
    rfpe_z1_from_z2,
)


# Data saluran L1 (=L2=L3=L4, keempat sirkit identik di file Mathcad),
# 9.45 km, OHL-150kV-TACSR 2x410/67mm2 -- persis field line_electrical.
LSI_MILLENIUM_L1 = LineImpedance(
    r1_ohm=0.3591, x1_ohm=2.63655,
    r0_ohm=1.7766, x0_ohm=7.90965,
)

# CT 2000/1 A, PT 150000/100 V -- n1 = 1.333333...
LSI_MILLENIUM_RATIO = CtPtRatio(
    ct_primary_a=2000, ct_secondary_a=1,
    pt_primary_kv=150, pt_secondary_v=100,
)


@pytest.fixture(scope="module")
def zone1() -> Zone1Result:
    return calculate_zone1(LSI_MILLENIUM_L1, LSI_MILLENIUM_RATIO)


def test_ct_pt_ratio_n1():
    # n1 = (2000/1) / (150000/100) = 2000 / 1500 = 1.333333...
    assert LSI_MILLENIUM_RATIO.n1 == pytest.approx(1.333333333, rel=1e-6)


def test_zone1_reach_is_80_percent_of_line_impedance(zone1):
    zl11 = LSI_MILLENIUM_L1.z1
    assert abs(zone1.z_primary_ohm) / abs(zl11) * 100 == pytest.approx(80.0, rel=1e-4)
    assert zone1.reach_percent == pytest.approx(80.0, rel=1e-4)


def test_zone1_primary_impedance_matches_mathcad(zone1):
    # Z1P := 0.8 * ZL11 -> 0.28728 + j2.10924 Ohm (primer)
    assert zone1.z_primary_ohm.real == pytest.approx(0.28728, rel=1e-4)
    assert zone1.z_primary_ohm.imag == pytest.approx(2.10924, rel=1e-4)
    assert abs(zone1.z_primary_ohm) == pytest.approx(2.128713972, rel=1e-4)


def test_zone1_secondary_impedance_matches_mathcad(zone1):
    # Z1S := Z1P * n1 -> 0.38304 + j2.81232 Ohm (sekunder)
    assert zone1.z_secondary_ohm.real == pytest.approx(0.38304, rel=1e-4)
    assert zone1.z_secondary_ohm.imag == pytest.approx(2.81232, rel=1e-4)
    assert abs(zone1.z_secondary_ohm) == pytest.approx(2.838285296, rel=1e-4)


def test_zone1_ground_fault_reach_uses_zero_sequence_not_positive(zone1):
    # Z10P := 0.8 * ZL10 (ZL10 = R0+jX0, BUKAN ZL11) -> 1.42128 + j6.32772
    # Regresi yg wajib dicegah: mengalikan 0.8 ke ZL11 lagi utk ground
    # fault (salah -- itu loop phase-phase, bukan phase-earth).
    assert zone1.z0_primary_ohm.real == pytest.approx(1.42128, rel=1e-4)
    assert zone1.z0_primary_ohm.imag == pytest.approx(6.32772, rel=1e-4)
    assert zone1.z0_secondary_ohm.real == pytest.approx(1.89504, rel=1e-4)
    assert zone1.z0_secondary_ohm.imag == pytest.approx(8.43696, rel=1e-4)


def test_zone1_rfpp_is_70_percent_of_3x_reach_not_100_percent(zone1):
    # RFPPZ1Pmax := 3*X1Z1P = 3*2.10924 = 6.32772
    # RFPPZ1P    := 0.7*RFPPZ1Pmax = 4.429404  (BUKAN 6.32772 -- regresi
    # yg wajib dicegah: lupa faktor 0.7, langsung pakai batas maks).
    x1z1p = zone1.z_primary_ohm.imag
    rfpp_max = 3 * x1z1p
    assert rfpp_max == pytest.approx(6.32772, rel=1e-4)
    assert zone1.rfpp_primary_ohm == pytest.approx(4.429404, rel=1e-4)
    assert zone1.rfpp_primary_ohm == pytest.approx(0.7 * rfpp_max, rel=1e-9)
    assert zone1.rfpp_secondary_ohm == pytest.approx(5.905872, rel=1e-4)


def test_zone1_delay_is_instantaneous():
    # T1 = 0.0 s -- dikonfirmasi tabel "DATA SETTING" file Mathcad.
    result = calculate_zone1(LSI_MILLENIUM_L1, LSI_MILLENIUM_RATIO)
    assert result.delay_s == 0.0


def test_rfpe_zone1_grades_down_from_zone2_not_computed_independently():
    # RFPEZ1P := 0.7 * RFPEZ2P (grading top-down, BUKAN dari X reach Z1
    # spt RFPP). Nilai referensi Mathcad: RFPEZ2P=20.55288462 ->
    # RFPEZ1P=14.38701923.
    rfpe_z2p = 20.55288462
    assert rfpe_z1_from_z2(rfpe_z2p) == pytest.approx(14.38701923, rel=1e-4)


def test_zone1_zero_length_or_zero_impedance_line_does_not_crash():
    zero_line = LineImpedance(r1_ohm=0.0, x1_ohm=0.0, r0_ohm=0.0, x0_ohm=0.0)
    result = calculate_zone1(zero_line, LSI_MILLENIUM_RATIO)
    assert result.reach_percent == 0.0
    assert result.z_primary_ohm == 0j
