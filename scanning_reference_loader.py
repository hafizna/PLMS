#!/usr/bin/env python3
"""
v3a: sumber T1/T2/T3 per-line dari helper sheet "DISTANCE COORDINATION
SCANNING" (362 link Google Sheets per GI/bay di MASTER_PHT kolom
"HELPER SHEET SCANNING KOORDINASI PHT", ditarik lewat subagent terpisah
-- lihat scanning_reference/scanning_reference.csv, 187 baris dari 88
sheet unik, 0 gagal parse).

KENAPA ini perlu: file Mathcad (distance_engine.py test) cuma
mengonfirmasi T3=1.6s utk 1 kasus (LSI-Millenium). Data scraping ini
MEMBUKTIKAN T3 genuinely bervariasi per line (distribusi nyata: 1.6s
138x, 1.2s 19x, 0.6s 1x, 0s 4x) -- jadi TIDAK BOLEH di-hardcode
universal, harus diresolusi per-line dari sumber ini.

Resolusi GI+bay (teks scanning_reference.csv) -> line_id (plms.db)
pakai normalized_gi()/OPPONENT_ALIAS yang SAMA dgn load.py (bukan
logika alias baru) supaya konsisten dgn resolver topologi yang sudah
ada. Verified: 127/153 baris (GI+bay lengkap) berhasil dipetakan ke
line_id nyata; sisanya (~26) genuinely gap -- baik krn di luar 44 GI
seed scope (mis. GANDUL, KEBON SIRIH, sirkit 500kV yang belum masuk
topologi manual), ejaan yang belum dipetakan (mis. 'BUDI KEMULYAAN' vs
'BUDI KEMULIAAN' di DB), atau anotasi non-data dari proses scraping
('[dup of LINE1 - GI S same]', '(comparison)') -- TIDAK dipaksa cocok,
dibiarkan unresolved (caller memperlakukan spt line_electrical yang
hilang: tidak ada T3, bukan ditebak).
"""
from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from load import OPPONENT_ALIAS, normalized_gi

SCANNING_REFERENCE_CSV = Path(__file__).resolve().parent / "scanning_reference" / "scanning_reference.csv"

# Strip anotasi non-data dari proses scraping DULUAN (bracket '[...]',
# mis. '[dup of LINE1 - GI S same]') -- SEBELUM apapun lain. Regresi yg
# sempat terjadi: anotasi ini kadang mengandung teks '- GI ' scr
# kebetulan (mis. "...- GI S same]"), yang tercocok oleh regex strip
# kode-aset di normalized_gi() (load.py: '^.*?\s-\s(?=GI\b)') dan
# memotong SELURUH nama GI asli di depannya -- HARUS dibersihkan lebih
# dulu, bukan dibiarkan sampai ke normalized_gi(). Lalu strip suffix
# '#N', penanda teknologi '(OHL)'/'(UGC)', dan prefix bay 'PHT NNNkV '
# (normalized_gi() menangani prefix GI/GIS/GITET/GISTET, bukan PHT).
_BRACKET_ANNOTATION = re.compile(r"\s*\[[^\]]*\]\s*")
_SUFFIX_AND_ANNOTATION = re.compile(r"\s*#\d+.*$")
_TECH_MARKER = re.compile(r"\s*\((OHL|UGC)\)\s*", re.I)
_BAY_PHT_PREFIX = re.compile(r"^PHT\s+\d+\s*k?V\s+", re.I)


def _clean_scanning_name(raw: str) -> str:
    raw = _BRACKET_ANNOTATION.sub("", raw)
    raw = _SUFFIX_AND_ANNOTATION.sub("", raw)
    raw = _TECH_MARKER.sub("", raw)
    raw = _BAY_PHT_PREFIX.sub("", raw)
    normalized = normalized_gi(raw)[0] or ""
    return OPPONENT_ALIAS.get(normalized, normalized)


@dataclass(frozen=True)
class ScanningTimers:
    """T1/T2/T3 (detik) dari helper sheet scanning, per LINE (row CSV).
    None per field bila sheet asal tidak mengisi nilai itu (mis. relay
    line-differential murni dgn distance disabled) -- JANGAN ditebak
    jadi 0 atau nilai lain."""
    file_id: str
    line_label: str
    z1_time_s: float | None
    z2_time_s: float | None
    z3_time_s: float | None


def _parse_time(raw: str) -> float | None:
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None  # error Excel literal (#DIV/0!, #VALUE!, dst) -- bukan angka, jangan ditebak


def load_scanning_rows() -> list[dict]:
    """Baca scanning_reference.csv apa adanya (list of dict per baris)."""
    with SCANNING_REFERENCE_CSV.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_line_id_timer_map(conn: sqlite3.Connection) -> dict[int, ScanningTimers]:
    """Petakan line_id (plms.db) -> ScanningTimers, dari baris
    scanning_reference.csv yang GI_r+bay_r-nya berhasil dicocokkan ke
    site_name topologi nyata (via normalized_gi(), sama dgn resolver
    load.py). Baris yang tidak match dilewati -- TIDAK ADA fallback
    tebakan; line_id yang tidak ada di return dict berarti genuinely
    belum py sumber T1/T2/T3 dari scanning reference.

    Bila SATU line_id dipetakan dari >1 baris CSV yang tidak konsisten
    (kasus jarang), baris pertama yang match menang -- dicatat sbg
    keterbatasan, bukan dirata-rata/digabung diam-diam.
    """
    conn.row_factory = sqlite3.Row
    site_pairs = conn.execute(
        """SELECT l.line_id, sitef.site_name AS from_site, sitet.site_name AS to_site
           FROM line l
           JOIN substation sf ON l.ss_from = sf.ss_id JOIN site sitef ON sf.site_id = sitef.site_id
           JOIN substation st ON l.ss_to = st.ss_id JOIN site sitet ON st.site_id = sitet.site_id"""
    ).fetchall()
    # Pra-hitung nama ternormalisasi tiap line sekali saja (bukan per baris CSV).
    normalized_sites = [
        (row["line_id"], normalized_gi(row["from_site"])[0] or "", normalized_gi(row["to_site"])[0] or "")
        for row in site_pairs
    ]

    result: dict[int, ScanningTimers] = {}
    for row in load_scanning_rows():
        gi_r, bay_r = row.get("gi_r", ""), row.get("bay_r", "")
        if not gi_r or not bay_r:
            continue
        gi_norm = _clean_scanning_name(gi_r)
        bay_norm = _clean_scanning_name(bay_r)
        if not gi_norm or not bay_norm:
            continue
        matched_line_id = None
        for line_id, from_norm, to_norm in normalized_sites:
            if (from_norm == gi_norm or to_norm == gi_norm) and (from_norm == bay_norm or to_norm == bay_norm):
                matched_line_id = line_id
                break
        if matched_line_id is None or matched_line_id in result:
            continue  # tidak match, atau line_id ini sudah py timer dari baris CSV sebelumnya
        result[matched_line_id] = ScanningTimers(
            file_id=row["file_id"], line_label=row["line_label"],
            z1_time_s=_parse_time(row.get("z1_time", "")),
            z2_time_s=_parse_time(row.get("z2_time", "")),
            z3_time_s=_parse_time(row.get("z3_time", "")),
        )
    return result
