#!/usr/bin/env python3
"""
Engine koordinasi distance (v3a) -- PLMS_Rebuild_Prompt_v2.md bagian
"Management scope vs calculation context" dan roadmap v3a.

Rumus diverifikasi terhadap file Mathcad asli pemilik data (kalkulasi
setting ABB REL670 nyata untuk penghantar 150kV LSI-Millenium, lihat
laporan ekstraksi -- rumus & nilai referensi didokumentasikan di
test_distance_engine.py sebagai golden test case). TIDAK diderivasi
dari asumsi generik buku teks proteksi -- setiap konstanta (reach %,
faktor pengali RFPP/RFPE) berasal dari nilai yang benar-benar dipakai
di file itu.

Cakupan modul ini SAAT INI: Zone-1 saja (tanpa traversal cabang/infeed/
cap trafo -- itu kebutuhan Z2/Z3, menyusul terpisah). Z1 murni fungsi
dari data listrik penghantar yang diproteksi sendiri, tidak butuh
calculation_context/traversal graph sama sekali.

Modul murni (tanpa akses db) -- dipanggil oleh loader/CLI terpisah yang
menyediakan input dari baris line_electrical.
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass


# Z1 = 80% dari impedansi positive-sequence penghantar yang diproteksi
# (protected line). Dikonfirmasi dari file Mathcad: Z1P := 0.8*ZL11,
# hasil |Z1P|/|ZL11| = tepat 80% (pembagian bilangan kompleks, bukan
# magnitudo -- valid krn Z1P sefasa persis dgn ZL11 sejak dikalikan
# skalar real 0.8). Ground-fault reach (Z10P) pakai persentase yang
# SAMA (80%) tapi dari impedansi zero-sequence (ZL10 = R0+jX0), BUKAN
# dari ZL11 -- dua reach terpisah untuk 2 fault loop (phase-phase vs
# phase-earth).
Z1_REACH_FRACTION = 0.8

# RFPP (resistive reach phase-to-phase): batas relay maksimum = 3x X
# reach zona ybs, tapi nilai yang BENAR-BENAR dipakai = 70% dari batas
# maks itu (bukan 100%). Dikonfirmasi: RFPPZ1Pmax := 3*X1Z1P;
# RFPPZ1P := 0.7*RFPPZ1Pmax = 2.1*X1Z1P.
RFPP_MAX_MULTIPLIER = 3.0
RFPP_USED_FRACTION = 0.7

# RFPE (resistive reach phase-to-earth) Zone-1 TIDAK dihitung dari X
# reach Z1 sendiri -- digrading TURUN dari RFPE Zone-3, yang basisnya
# batas impedansi beban (RLdFw). Ini genuinely butuh Z2/Z3 utk hitung
# RFPEZ2P/RFPEZ3P dulu (grading top-down: Z3 -> Z2 -> Z1), jadi RFPE
# Z1 BELUM bisa dihitung sendirian tanpa Z2/Z3 -- lihat rfpe_z1_from_z2()
# di bawah, dipanggil terpisah begitu RFPEZ2P tersedia (menyusul saat
# Z2/Z3 diimplementasikan). Konstanta grading Z1<-Z2 dari file Mathcad:
# RFPEZ1P := 0.7 * RFPEZ2P.
RFPE_Z1_FROM_Z2_FRACTION = 0.7


@dataclass(frozen=True)
class LineImpedance:
    """Impedansi penghantar yang diproteksi, dalam ohm PRIMER (bukan
    ohm/km) -- persis field line_electrical.r1_ohm/x1_ohm/r0_ohm/x0_ohm.
    """
    r1_ohm: float
    x1_ohm: float
    r0_ohm: float
    x0_ohm: float

    @property
    def z1(self) -> complex:
        return complex(self.r1_ohm, self.x1_ohm)

    @property
    def z0(self) -> complex:
        return complex(self.r0_ohm, self.x0_ohm)


@dataclass(frozen=True)
class CtPtRatio:
    """Faktor konversi ohm primer -> ohm sekunder (sisi relay).
    n1 := (CT_primary/CT_secondary) / (PT_primary_kV*1000/PT_secondary_V)
    Dikonfirmasi dari file Mathcad: CT1=2000/1, PT1=150000/100 ->
    n1 = 1.333333 (bukan cuma rasio CT, harus dibagi rasio PT juga --
    n1 dipakai utk konversi impedansi primer->sekunder krn Z_sekunder
    = Z_primer * (CT_ratio/PT_ratio)).
    """
    ct_primary_a: float
    ct_secondary_a: float
    pt_primary_kv: float
    pt_secondary_v: float

    @property
    def n1(self) -> float:
        ct_ratio = self.ct_primary_a / self.ct_secondary_a
        pt_ratio = (self.pt_primary_kv * 1000) / self.pt_secondary_v
        return ct_ratio / pt_ratio


@dataclass(frozen=True)
class Zone1Result:
    zone: str
    # Reach phase-phase (positive-sequence), primer & sekunder.
    z_primary_ohm: complex
    z_secondary_ohm: complex
    # Reach ground fault (zero-sequence), primer & sekunder -- dipakai
    # relay utk loop phase-earth (bukan sekadar X1 * k0, ini reach
    # impedansi zero-sequence penuh, konsisten Mathcad: Z10P = 0.8*ZL10).
    z0_primary_ohm: complex
    z0_secondary_ohm: complex
    rfpp_primary_ohm: float
    rfpp_secondary_ohm: float
    reach_percent: float  # thd |ZL11| -- selalu 80.0 utk Z1, disimpan utk audit
    delay_s: float = 0.0  # Z1 selalu instan


def calculate_zone1(line: LineImpedance, ratio: CtPtRatio) -> Zone1Result:
    """Hitung reach Zone-1 (instan, tanpa traversal/infeed).

    Formula (dikonfirmasi persis dari Mathcad LSI-Millenium):
        Z1P  = 0.8 * ZL11              (ZL11 = R1+jX1 primer)
        Z1S  = Z1P * n1
        Z10P = 0.8 * ZL10              (ZL10 = R0+jX0 primer, ground fault)
        Z10S = Z10P * n1
        RFPPZ1Pmax = 3 * X1Z1P         (X1Z1P = bagian imajiner Z1P)
        RFPPZ1P    = 0.7 * RFPPZ1Pmax
        RFPPZ1S    = RFPPZ1P * n1
    """
    zl11 = line.z1
    zl10 = line.z0
    n1 = ratio.n1

    z1p = zl11 * Z1_REACH_FRACTION
    z1s = z1p * n1
    z10p = zl10 * Z1_REACH_FRACTION
    z10s = z10p * n1

    x1z1p = z1p.imag
    rfpp_max = RFPP_MAX_MULTIPLIER * x1z1p
    rfpp_p = RFPP_USED_FRACTION * rfpp_max
    rfpp_s = rfpp_p * n1

    reach_percent = (abs(z1p) / abs(zl11)) * 100 if abs(zl11) else 0.0

    return Zone1Result(
        zone="Z1",
        z_primary_ohm=z1p,
        z_secondary_ohm=z1s,
        z0_primary_ohm=z10p,
        z0_secondary_ohm=z10s,
        rfpp_primary_ohm=rfpp_p,
        rfpp_secondary_ohm=rfpp_s,
        reach_percent=reach_percent,
        delay_s=0.0,
    )


def rfpe_z1_from_z2(rfpe_z2_primary_ohm: float) -> float:
    """RFPE Zone-1 = 70% dari RFPE Zone-2 (grading TURUN, bukan dihitung
    independen dari X reach Z1 spt RFPP). Dipanggil terpisah setelah
    RFPEZ2P tersedia (butuh Z2/Z3 lebih dulu utk hitung basis RLdFw).
    Fungsi ini murni step terakhir kaskade grading; tidak menghitung
    RLdFw/RFPEZ3P/RFPEZ2P sendiri -- itu tanggung jawab modul Z2/Z3.
    """
    return RFPE_Z1_FROM_Z2_FRACTION * rfpe_z2_primary_ohm


# ---------------------------------------------------------------- Zone-2
#
# Z2min  := 1.2 * ZL11
# Z2mak1 := 0.8 * (ZL11 + 0.8*ZL_branch*K)   -- utk TIAP cabang di remote bus
# Z21mak := kandidat terbesar antara Z2min dan SEMUA Z2mak1 per-cabang
# ZTrf   := 0.8 * (ZL11 + 0.5*XT1*j)         -- cap arah trafo remote
# Z2P    := Z21mak, TAPI dibatasi tidak boleh melebihi |ZTrf|
#
# Di file Mathcad sumber hanya ada 1 "cabang" krn 4 sirkit sejajar
# (L1=L2=L3=L4) diperlakukan sbg satu ZL21 -- utk engine v3a yang
# general, traversal ini HARUS menerima SEMUA cabang nyata di remote
# bus (dari incident_lines() sisi pemanggil), bukan 1 next-line
# hardcoded (dilarang eksplisit di prompt v2). Faktor infeed K dari
# file sumber di-hardcode = 1 (dikonfirmasi bug/simplifikasi lama,
# BUKAN dihitung dari studi hubung singkat) -- parameter ini sengaja
# dibuka sbg argumen (infeed_factor) supaya pemanggil bisa menyediakan
# nilai yang benar nanti tanpa mengubah rumus intinya.
Z2_MIN_FRACTION = 1.2           # Z2min = 1.2 x ZL11
Z2_OWN_LINE_FRACTION = 0.8      # faktor luar: 0.8 x (...)
Z2_BRANCH_FRACTION = 0.8        # faktor infeed cabang: 0.8 x ZL_branch x K
Z2_TRANSFORMER_FRACTION = 0.8   # faktor luar utk cap trafo: 0.8 x (...)
Z2_TRANSFORMER_XT_FRACTION = 0.5  # porsi XT1 yg diperhitungkan: 0.5 x XT1


@dataclass(frozen=True)
class RemoteBranch:
    """Satu cabang yang terhubung ke remote bus (ujung protected line),
    SELAIN protected line itu sendiri -- hasil traversal graph nyata
    (mis. dari incident_lines() di load.py), bukan next-line tunggal
    yang di-hardcode. line_id disimpan utk audit/calculation_branch,
    bukan dipakai dlm rumus.
    """
    line_id: int
    impedance: LineImpedance


@dataclass(frozen=True)
class Zone2Result:
    zone: str
    z_primary_ohm: complex
    z_secondary_ohm: complex
    z0_primary_ohm: complex
    z0_secondary_ohm: complex
    rfpp_primary_ohm: float
    rfpp_secondary_ohm: float
    reach_percent: float
    delay_s: float
    # Transparansi keputusan traversal -- line_id cabang yang dipilih
    # (None bila hasil akhir dibatasi cap trafo, bukan cabang manapun),
    # dan apakah cap trafo yang menentukan hasil akhir.
    selected_branch_line_id: int | None
    capped_by_transformer: bool
    candidates_considered: int  # jumlah kandidat cabang yang dievaluasi


def calculate_zone2(
    line: LineImpedance,
    branches: list[RemoteBranch],
    transformer_reactance_x_ohm: float,
    ratio: CtPtRatio,
    infeed_factor: float = 1.0,
) -> Zone2Result:
    """Hitung reach Zone-2 dengan traversal SEMUA cabang di remote bus.

    branches: daftar SEMUA line lain yang terhubung ke remote bus
    (ujung protected line yang bukan local bus), didapat dari traversal
    graph topologi nyata -- BUKAN 1 next-line yang diasumsikan.
    Boleh kosong (remote bus tanpa cabang lain selain protected line
    itu sendiri) -- maka Z2P jatuh ke Z2min atau cap trafo saja.

    transformer_reactance_x_ohm: XT1, reaktansi trafo di arah remote
    (dipakai sbg cap atas reach Z2 -- "Dipilih Zone 2 terbesar tetapi
    tidak lebih besar dari zone 2 trafo", dikonfirmasi Mathcad).

    infeed_factor: K, faktor infeed per-cabang. Default 1.0 (nilai yg
    dipakai file Mathcad sumber, dikonfirmasi bug/simplifikasi lama --
    lihat komentar di atas), TAPI parameter ini sengaja dibuka supaya
    pemanggil bisa menyuplai K yang dihitung dari studi hubung singkat
    sungguhan begitu tersedia, tanpa mengubah rumus.
    """
    zl11 = line.z1
    zl10 = line.z0
    n1 = ratio.n1

    z2min = Z2_MIN_FRACTION * zl11
    ztrf = Z2_TRANSFORMER_FRACTION * (zl11 + complex(0, Z2_TRANSFORMER_XT_FRACTION * transformer_reactance_x_ohm))

    # Kandidat: Z2min selalu ada; tiap cabang remote menghasilkan 1
    # kandidat Z2mak. Pilih magnitudo TERBESAR di antara semuanya
    # (bukan pertama/terakhir -- urutan traversal tidak boleh
    # mempengaruhi hasil, sesuai transparansi keputusan yang diminta).
    best_candidate = z2min
    best_branch_line_id: int | None = None
    for branch in branches:
        z2mak = Z2_OWN_LINE_FRACTION * (zl11 + Z2_BRANCH_FRACTION * branch.impedance.z1 * infeed_factor)
        if abs(z2mak) > abs(best_candidate):
            best_candidate = z2mak
            best_branch_line_id = branch.line_id

    capped_by_transformer = abs(best_candidate) > abs(ztrf)
    z2p = ztrf if capped_by_transformer else best_candidate
    if capped_by_transformer:
        best_branch_line_id = None
    z2s = z2p * n1

    # Ground fault (zero-sequence): pola identik, pakai ZL10/ZL_branch.z0.
    z20min = Z2_MIN_FRACTION * zl10
    z20trf = Z2_TRANSFORMER_FRACTION * (zl10 + complex(0, Z2_TRANSFORMER_XT_FRACTION * transformer_reactance_x_ohm))
    best_candidate0 = z20min
    for branch in branches:
        z20mak = Z2_OWN_LINE_FRACTION * (zl10 + Z2_BRANCH_FRACTION * branch.impedance.z0 * infeed_factor)
        if abs(z20mak) > abs(best_candidate0):
            best_candidate0 = z20mak
    z20p = z20trf if abs(best_candidate0) > abs(z20trf) else best_candidate0
    z20s = z20p * n1

    x1z2p = z2p.imag
    rfpp_max = RFPP_MAX_MULTIPLIER * x1z2p
    rfpp_p = RFPP_USED_FRACTION * rfpp_max
    rfpp_s = rfpp_p * n1

    reach_percent = (abs(z2p) / abs(zl11)) * 100 if abs(zl11) else 0.0

    return Zone2Result(
        zone="Z2",
        z_primary_ohm=z2p,
        z_secondary_ohm=z2s,
        z0_primary_ohm=z20p,
        z0_secondary_ohm=z20s,
        rfpp_primary_ohm=rfpp_p,
        rfpp_secondary_ohm=rfpp_s,
        reach_percent=reach_percent,
        delay_s=0.0,  # diisi oleh zone2_delay() terpisah -- lihat di bawah
        selected_branch_line_id=best_branch_line_id,
        capped_by_transformer=capped_by_transformer,
        candidates_considered=len(branches),
    )


# Timer T2 kondisional -- Mathcad: X1sg := 0.8*XL_branch (reach 80% dari
# X cabang tetangga, dipakai sbg AMBANG KEPUTUSAN waktu, bukan utk
# menghitung reach Z2 itu sendiri). Jika overreach Z2 di luar protected
# line (|Z2P|-|ZL11|) masih di bawah ambang itu, T2 cepat (T2A); kalau
# tidak, T2 lambat (T2B). Nilai T2A/T2B dari file Mathcad: 0.4s / 0.8s.
#
# CATATAN: file sumber mendefinisikan variabel `q := |Z2P - ZL11|` yang
# TIDAK DIPAKAI dlm formula T2 aktual (T2 pakai |Z2P|-|ZL11|, selisih
# magnitudo, bukan magnitudo selisih kompleks `q`) -- dikonfirmasi
# subagent riset sbg kemungkinan sisa draft lama di file sumber. Engine
# ini mengikuti formula yg BENAR-BENAR dipakai (selisih magnitudo),
# bukan variabel vestigial itu.
ZONE2_DELAY_FAST_S = 0.4
ZONE2_DELAY_SLOW_S = 0.8


def zone2_delay(z2_primary_ohm: complex, zl11: complex, branch_x_threshold_ohm: float) -> float:
    """T2 = 0.4s bila overreach (|Z2P|-|ZL11|) < ambang cabang (0.8 x X
    cabang tetangga); else 0.8s. branch_x_threshold_ohm HARUS dihitung
    pemanggil sbg 0.8 x X (bagian imajiner impedansi) cabang yang
    relevan -- fungsi ini tidak mengasumsikan cabang mana yang dipakai
    sbg ambang (file Mathcad memakai cabang tetangga L2 scr spesifik,
    tapi utk engine general ini harus jadi keputusan eksplisit
    pemanggil, bukan asumsi tersembunyi di dalam fungsi ini).
    """
    overreach = abs(z2_primary_ohm) - abs(zl11)
    return ZONE2_DELAY_FAST_S if overreach < branch_x_threshold_ohm else ZONE2_DELAY_SLOW_S
