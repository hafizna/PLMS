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
