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
    RemoteBranch,
    TwoHopBranch,
    Zone1Result,
    Zone2Result,
    Zone3Result,
    calculate_zone1,
    calculate_zone2,
    calculate_zone3,
    load_impedance_forward,
    rfpe_cascade,
    rfpe_z1_from_z2,
    zone2_delay,
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


# ------------------------------------------------------------------ Zone-2
# Di file Mathcad sumber, L1=L2=L3=L4 (4 sirkit paralel identik) --
# "cabang di remote bus" utk kasus referensi ini SECARA KEBETULAN py
# impedansi yang sama dgn protected line itu sendiri. Ini bukan
# kelemahan test: rumus & traversal logic yang diuji tetap sama
# terlepas dari berapa banyak/macam cabang -- dibuktikan terpisah oleh
# test edge-case (0 cabang, cabang dgn impedansi beda, cap trafo aktif)
# yang TIDAK bergantung pada kebetulan L1=L2 itu.
XT1_GI_MILLENIUM = 5.85  # min(IBT 500/150kV 13% -> 5.85, Trafo2 12.5% -> 46.875)


@pytest.fixture(scope="module")
def zone2() -> Zone2Result:
    branch = RemoteBranch(line_id=1, impedance=LSI_MILLENIUM_L1)  # ZL21 = ZL11 (L1=L2 di sumber)
    return calculate_zone2(LSI_MILLENIUM_L1, [branch], XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO)


def test_zone2_primary_impedance_matches_mathcad(zone2):
    # Z2P -> 0.517104 + j3.796632 Ohm (primer); |Z2P| = 3.83168515
    assert zone2.z_primary_ohm.real == pytest.approx(0.517104, rel=1e-4)
    assert zone2.z_primary_ohm.imag == pytest.approx(3.796632, rel=1e-4)
    assert abs(zone2.z_primary_ohm) == pytest.approx(3.83168515, rel=1e-4)


def test_zone2_secondary_impedance_matches_mathcad(zone2):
    # Z2S -> 0.689472 + j5.062176 Ohm (sekunder); |Z2S| = 5.108913534
    assert zone2.z_secondary_ohm.real == pytest.approx(0.689472, rel=1e-4)
    assert zone2.z_secondary_ohm.imag == pytest.approx(5.062176, rel=1e-4)
    assert abs(zone2.z_secondary_ohm) == pytest.approx(5.108913534, rel=1e-4)


def test_zone2_ground_fault_reach_matches_mathcad(zone2):
    # Z20P -> 1.42128 + j8.66772 Ohm (primer)
    assert zone2.z0_primary_ohm.real == pytest.approx(1.42128, rel=1e-4)
    assert zone2.z0_primary_ohm.imag == pytest.approx(8.66772, rel=1e-4)


def test_zone2_rfpp_matches_mathcad(zone2):
    assert zone2.rfpp_primary_ohm == pytest.approx(7.972927, rel=1e-4)
    assert zone2.rfpp_secondary_ohm == pytest.approx(10.630570, rel=1e-4)


def test_zone2_reach_percent_matches_mathcad(zone2):
    # Z2% := (|Z2P|/|ZL11|)*100 -> 144.0% (magnitudo, BUKA pembagian
    # kompleks spt Z1% -- regresi yg wajib dicegah: memakai rumus Z1
    # utk Z2, hasilnya akan beda krn Z2P tidak sefasa dgn ZL11).
    assert zone2.reach_percent == pytest.approx(144.0, rel=1e-4)


def test_zone2_not_capped_when_transformer_reach_is_larger(zone2):
    # |ZTrf| = 4.45850 Ohm > |Z21mak| = 3.83169 Ohm -> Z2P = Z21mak,
    # BUKAN ZTrf. Regresi yg wajib dicegah: cap selalu diterapkan tanpa
    # cek magnitudo, akan salah pilih ZTrf padahal seharusnya tidak.
    assert zone2.capped_by_transformer is False
    assert zone2.selected_branch_line_id == 1


def test_zone2_delay_matches_mathcad(zone2):
    # T2 = 0.4s krn overreach (|Z2P|-|ZL11|) < X1sg (0.8 x X cabang).
    x1sg = 0.8 * LSI_MILLENIUM_L1.x1_ohm
    delay = zone2_delay(zone2.z_primary_ohm, LSI_MILLENIUM_L1.z1, x1sg)
    assert delay == pytest.approx(0.4, rel=1e-9)


def test_zone2_falls_back_to_1_2x_line_when_no_branches_at_remote_bus():
    # Remote bus tanpa cabang lain (mis. GI ujung/radial) -> Z2P harus
    # jatuh ke Z2min = 1.2*ZL11, BUKAN error atau 0.
    result = calculate_zone2(LSI_MILLENIUM_L1, [], XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO)
    assert result.z_primary_ohm == pytest.approx(1.2 * LSI_MILLENIUM_L1.z1, rel=1e-9)
    assert result.selected_branch_line_id is None
    assert result.candidates_considered == 0


def test_zone2_is_capped_by_transformer_when_transformer_reach_is_smaller():
    # Trafo remote sangat kecil (XT1 kecil) -> ZTrf harus jadi batas
    # atas, Z2P TIDAK boleh melebihi |ZTrf| walau kandidat cabang lebih
    # besar. selected_branch_line_id harus None krn hasil akhir bukan
    # cabang manapun, melainkan cap trafo.
    tiny_xt1 = 0.1
    branch = RemoteBranch(line_id=42, impedance=LSI_MILLENIUM_L1)
    result = calculate_zone2(LSI_MILLENIUM_L1, [branch], tiny_xt1, LSI_MILLENIUM_RATIO)
    assert result.capped_by_transformer is True
    assert result.selected_branch_line_id is None
    ztrf = 0.8 * (LSI_MILLENIUM_L1.z1 + complex(0, 0.5 * tiny_xt1))
    assert result.z_primary_ohm == pytest.approx(ztrf, rel=1e-9)


def test_zone2_picks_largest_candidate_among_multiple_branches_regardless_of_order():
    # Traversal HARUS memilih magnitudo terbesar di antara semua cabang,
    # bukan cabang pertama/terakhir yang ditemukan -- urutan traversal
    # tidak boleh mempengaruhi hasil (dilarang next-line hardcoded).
    small_branch_line = LineImpedance(r1_ohm=0.05, x1_ohm=0.3, r0_ohm=0.2, x0_ohm=0.9)
    big_branch_line = LSI_MILLENIUM_L1  # jauh lebih besar impedansinya
    branches_order_a = [
        RemoteBranch(line_id=1, impedance=small_branch_line),
        RemoteBranch(line_id=2, impedance=big_branch_line),
    ]
    branches_order_b = [
        RemoteBranch(line_id=2, impedance=big_branch_line),
        RemoteBranch(line_id=1, impedance=small_branch_line),
    ]
    result_a = calculate_zone2(LSI_MILLENIUM_L1, branches_order_a, XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO)
    result_b = calculate_zone2(LSI_MILLENIUM_L1, branches_order_b, XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO)
    assert result_a.selected_branch_line_id == 2
    assert result_b.selected_branch_line_id == 2
    assert result_a.z_primary_ohm == result_b.z_primary_ohm


# ------------------------------------------------------------------ Zone-3
# Golden case Mathcad: 1-hop via ZL31 (=ZL11, sirkit paralel identik),
# 2-hop via ZL21+0.8*ZL41 (=ZL11 jg, krn L1=L2=L3=L4). Test edge-case
# terpisah (first_hop != second_hop) membuktikan TwoHopBranch memakai
# KEDUA impedansi hop scr benar -- bukan cuma second_hop_impedance
# (bug yang sempat ada & diperbaiki sebelum commit: rumus Mathcad
# Z3mak2 = 0.8*(ZL11 + 0.8*(ZL_first_hop + 0.8*ZL_second_hop)*K) py
# ZL_first_hop TANPA faktor 0.8 di posisi itu, ZL_second_hop DENGAN
# faktor 0.8 -- keduanya WAJIB beda kontribusi ke hasil).

@pytest.fixture(scope="module")
def zone3() -> Zone3Result:
    one_hop = [RemoteBranch(line_id=3, impedance=LSI_MILLENIUM_L1)]  # ZL31 = ZL11
    two_hop = [TwoHopBranch(
        first_hop_line_id=2, first_hop_impedance=LSI_MILLENIUM_L1,   # ZL21 = ZL11
        second_hop_line_id=4, second_hop_impedance=LSI_MILLENIUM_L1,  # ZL41 = ZL11
    )]
    return calculate_zone3(LSI_MILLENIUM_L1, one_hop, two_hop, XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO, delay_s=1.6)


def test_zone3_primary_impedance_matches_mathcad(zone3):
    # Z3P -> 0.28728 + j5.85324 Ohm (primer); |Z3P| = 5.860285684
    assert zone3.z_primary_ohm.real == pytest.approx(0.28728, rel=1e-4)
    assert zone3.z_primary_ohm.imag == pytest.approx(5.85324, rel=1e-4)
    assert abs(zone3.z_primary_ohm) == pytest.approx(5.860285684, rel=1e-4)


def test_zone3_secondary_impedance_matches_mathcad(zone3):
    # Z3S -> 0.38304 + j7.80432 Ohm (sekunder); |Z3S| = 7.813714245
    assert zone3.z_secondary_ohm.real == pytest.approx(0.38304, rel=1e-4)
    assert zone3.z_secondary_ohm.imag == pytest.approx(7.80432, rel=1e-4)
    assert abs(zone3.z_secondary_ohm) == pytest.approx(7.813714245, rel=1e-4)


def test_zone3_ground_fault_reach_matches_mathcad(zone3):
    # Z30P -> 1.42128 + j10.07172 Ohm (primer)
    assert zone3.z0_primary_ohm.real == pytest.approx(1.42128, rel=1e-4)
    assert zone3.z0_primary_ohm.imag == pytest.approx(10.07172, rel=1e-4)


def test_zone3_rfpp_matches_mathcad(zone3):
    assert zone3.rfpp_primary_ohm == pytest.approx(12.291804, rel=1e-4)
    assert zone3.rfpp_secondary_ohm == pytest.approx(16.389072, rel=1e-4)


def test_zone3_reach_percent_matches_mathcad(zone3):
    # Z3% := (|Z3P|/|ZL11|)*100 -> 220.238% (overreach besar krn
    # mencakup 1-2 saluran remote, normal utk Zone-3 backup).
    assert zone3.reach_percent == pytest.approx(220.238, rel=1e-3)


def test_zone3_delay_is_fixed_not_computed():
    # T3 = 1.6s -- konstanta TETAP dari Mathcad ("Setting waktu tunda
    # untuk Zone-3 ditentukan 1.6 detik"), BUKAN hasil kalkulasi
    # grading otomatis spt T2. Fungsi wajib menerima delay_s eksplisit
    # dari pemanggil, tidak boleh py default hardcoded 1.6s universal
    # (itu spesifik 1 kasus, bukan konstanta rumus).
    one_hop = [RemoteBranch(line_id=3, impedance=LSI_MILLENIUM_L1)]
    result = calculate_zone3(LSI_MILLENIUM_L1, one_hop, [], XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO, delay_s=1.6)
    assert result.delay_s == 1.6
    result2 = calculate_zone3(LSI_MILLENIUM_L1, one_hop, [], XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO, delay_s=2.0)
    assert result2.delay_s == 2.0


def test_zone3_two_hop_uses_first_hop_impedance_not_just_second_hop():
    # Regresi kritis: Z3mak2 = 0.8*(ZL11 + 0.8*(ZL_first + 0.8*ZL_second)*K)
    # -- ZL_first TANPA faktor 0.8 tambahan di posisi itu (cuma dijumlah
    # langsung), ZL_second DENGAN faktor 0.8. Menukar first_hop_impedance
    # dgn impedansi lain (second_hop tetap sama) HARUS mengubah hasil --
    # kalau tidak berubah, berarti first_hop_impedance diam-diam
    # diabaikan (bug yg sempat terjadi: TwoHopBranch awal cuma
    # menyimpan second_hop_impedance).
    big_line = LSI_MILLENIUM_L1
    tiny_line = LineImpedance(r1_ohm=0.001, x1_ohm=0.001, r0_ohm=0.001, x0_ohm=0.001)
    huge_xt1 = 1000.0  # trafo besar spy tdk ada cap yg menutupi efeknya

    two_hop_big_first = [TwoHopBranch(
        first_hop_line_id=2, first_hop_impedance=big_line,
        second_hop_line_id=4, second_hop_impedance=tiny_line,
    )]
    two_hop_tiny_first = [TwoHopBranch(
        first_hop_line_id=2, first_hop_impedance=tiny_line,
        second_hop_line_id=4, second_hop_impedance=big_line,
    )]
    result_big_first = calculate_zone3(LSI_MILLENIUM_L1, [], two_hop_big_first, huge_xt1, LSI_MILLENIUM_RATIO, delay_s=1.6)
    result_tiny_first = calculate_zone3(LSI_MILLENIUM_L1, [], two_hop_tiny_first, huge_xt1, LSI_MILLENIUM_RATIO, delay_s=1.6)
    assert result_big_first.z_primary_ohm != result_tiny_first.z_primary_ohm


def test_zone3_falls_back_to_transformer_cap_when_no_branches_at_all():
    result = calculate_zone3(LSI_MILLENIUM_L1, [], [], XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO, delay_s=1.6)
    assert result.capped_by_transformer is True
    assert result.selected_branch_line_id is None
    ztrf = 0.8 * (LSI_MILLENIUM_L1.z1 + complex(0, 0.8 * XT1_GI_MILLENIUM))
    assert result.z_primary_ohm == pytest.approx(ztrf, rel=1e-9)


def test_zone3_picks_two_hop_when_it_exceeds_one_hop_candidates():
    # Kandidat 2-hop harus bisa MENANG dibanding 1-hop bila magnitudonya
    # lebih besar -- traversal tidak boleh berhenti di 1-hop begitu ada
    # kandidat (harus bandingkan semua, sesuai larangan next-line
    # hardcoded).
    small_branch = LineImpedance(r1_ohm=0.01, x1_ohm=0.05, r0_ohm=0.05, x0_ohm=0.2)
    one_hop = [RemoteBranch(line_id=3, impedance=small_branch)]
    two_hop = [TwoHopBranch(
        first_hop_line_id=2, first_hop_impedance=LSI_MILLENIUM_L1,
        second_hop_line_id=4, second_hop_impedance=LSI_MILLENIUM_L1,
    )]
    result = calculate_zone3(LSI_MILLENIUM_L1, one_hop, two_hop, XT1_GI_MILLENIUM, LSI_MILLENIUM_RATIO, delay_s=1.6)
    assert result.selected_is_two_hop is True
    assert result.selected_branch_line_id == 4


# ------------------------------------------------------------ RFPE cascade

def test_load_impedance_forward_matches_mathcad():
    # Vn=150000V, CCC=2730A, pf=0.8, margin=0.95 -> RLdFw=32.623626374 Ohm
    rldfw = load_impedance_forward(
        nominal_voltage_v=150000, conductor_rated_current_a=2730,
        load_power_factor=0.8, voltage_margin_fraction=0.95,
    )
    assert rldfw == pytest.approx(32.623626374, rel=1e-4)


def test_rfpe_cascade_grades_top_down_from_load_impedance():
    # RFPEZ3P := 0.9*RLdFw; RFPEZ2P := 0.7*RFPEZ3P; RFPEZ1P := 0.7*RFPEZ2P
    # Referensi Mathcad: RLdFw=32.623626374 -> Z3=29.361264, Z2=20.55288462,
    # Z1=14.38701923.
    rldfw = 32.623626374
    rfpe_z3p, rfpe_z2p, rfpe_z1p = rfpe_cascade(rldfw)
    assert rfpe_z3p == pytest.approx(29.361264, rel=1e-4)
    assert rfpe_z2p == pytest.approx(20.55288462, rel=1e-4)
    assert rfpe_z1p == pytest.approx(14.38701923, rel=1e-4)
    # Konsisten dgn rfpe_z1_from_z2() yg dipakai terpisah di modul Z1.
    assert rfpe_z1p == pytest.approx(rfpe_z1_from_z2(rfpe_z2p), rel=1e-9)
