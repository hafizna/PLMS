#!/usr/bin/env python3
"""
v3a: menyambungkan distance_engine.py ke topologi nyata (plms.db) --
mengisi calculation_context/calculation_branch per rele DIST.

Traversal graph: utk tiap rele coordination_class=GRADED function_type=
DIST, protected line-nya sudah py line_id (v2). Remote bus = ujung line
itu yang BUKAN sisi rele terpasang. 1-hop = semua line lain yang
nempel di remote bus (incident_lines(), load.py). 2-hop = semua line
lain yang nempel di ujung JAUH tiap 1-hop tsb (kecuali balik lagi ke
line asal/remote bus -- jangan siklus).

Data trafo (XT1/reaktansi remote) TIDAK ADA di plms.db sama sekali
(dikonfirmasi: tidak ada function_type trafo, tidak ada tabel
transformer, cuma ada di 1 file Mathcad utk 1 kasus GI Millenium).
Keputusan pemilik data (semula): kalau XT1 tidak tersedia, JANGAN hitung
Z2/Z3 tanpa cap (bisa overreach salah) -- tandai status
incomplete_topology persis di titik itu, sesuai prinsip "jangan
mengestimasi line/impedansi yang hilang" di prompt v2.

Revisi 2026-09-29: asumsi template workbook 12,5% dipakai hanya untuk
identitas GI dan tegangan yang nameplate per unitnya sudah ditelusuri ke
SLD. XT1 = 0,125 x V_ref^2 / MVA_unit, R diabaikan sesuai workbook.
Ini bukan impedansi terukur atau standar universal PLN. Resolver membaca
identitas dari database, bukan mengandalkan nomor ss_id snapshot.
Caller menandai hasil STATUS_COMPLETE_ASSUMED_TRANSFORMER.

Fungsi build_*()/compute_relay_function_zones() murni baca (read-only).
persist_calculation_context() (di bawah) yang menulis ke
calculation_context/calculation_branch -- idempoten: DELETE baris lama
utk relay_function_id yg sama sebelum INSERT baru, jadi aman dipanggil
ulang (re-run) tanpa duplikasi/sisa data basi.
"""
from __future__ import annotations

import datetime
import re
import sqlite3
from dataclasses import dataclass, replace

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
    rfpe_z1_from_z2,
    zone2_delay,
)
from scanning_reference_loader import ScanningTimers, build_line_id_timer_map


STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE_TOPOLOGY = "incomplete_topology"
STATUS_INCOMPLETE_EXTERNAL = "incomplete_external"
STATUS_AMBIGUOUS_BRANCH = "ambiguous_branch"
# Reach dihitung sukses, TAPI salah satu input (XT1) berasal dari asumsi
# 12,5% x MVA nameplate (bukan Z% terukur) -- lihat resolve_transformer_
# reactance(). Dipisah dari STATUS_COMPLETE supaya tidak tercampur diam-
# diam dgn hasil yang seluruh inputnya data terukur/DIgSILENT.
STATUS_COMPLETE_ASSUMED_TRANSFORMER = "complete_assumed_transformer"

SAFETY_CAP_HOPS = 3

# Asumsi template workbook DIgSILENT, ditemukan identik di 7
# sheet lintas 2 kelas tegangan/ukuran trafo (500MVA@500kV & 60MVA@150kV)
# (lihat docs/VALIDASI_GANDUL_KEMBANGAN_DURIKOSAMBI.md addendum):
# XT1 = Z_PERCENT x V_ref^2 / MVA_nameplate, resistansi trafo diabaikan
# (XT1 murni reaktansi imajiner di sumber juga).
ASSUMED_TRANSFORMER_Z_PERCENT = 0.125

# Reviewed identity + voltage, never snapshot-specific SQLite IDs.
# MVA is per unit; this is a workbook assumption, not measured impedance.
_GRLBR_SOURCE = (
    "SLD GRLBR Ver 8 2022, 2x60MVA 150/22kV, hash "
    "a20c0d9172bf9185230096f2c07751690ea6cb982a3fa266e1e293fde633bf88"
)
_ASSUMED_TRANSFORMER_NAMEPLATE: dict[tuple[str, float], tuple[float, float, str]] = {
    ("GROGOL BARU", 150.0): (60.0, 150.0, _GRLBR_SOURCE),  # GROGOL BARU (data manual)
    ("GROGOL II", 150.0): (60.0, 150.0, _GRLBR_SOURCE),  # GROGOL II (DIgSILENT) = GROGOL BARU, substation fisik sama
    ("GROGOL", 150.0): (60.0, 150.0,
          "SLD GRGOL Ver 8 2022, 3x60MVA 150/20-22kV, hash "
          "077aa70682f8308302b8415e7ace7bd55caf5e3396f2ed25d632a5ac7c91f287"),  # GROGOL, substation lain
}


@dataclass(frozen=True)
class TransformerReactance:
    """Hasil resolve_transformer_reactance(). assumed=True berarti x_ohm
    dari asumsi 12,5% x MVA nameplate (ASSUMED_TRANSFORMER_Z_PERCENT),
    BUKAN Z% terukur -- caller wajib mempropagasi ini ke status zona."""
    x_ohm: float
    assumed: bool
    note: str


def resolve_line_impedance(conn: sqlite3.Connection, line_id: int) -> LineImpedance | None:
    """None bila line_electrical tidak ada (mis. UPT_MANUAL tanpa data
    DIgSILENT) -- INI ADALAH titik incomplete_topology, jangan ditebak."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT r1_ohm, x1_ohm, r0_ohm, x0_ohm FROM line_electrical WHERE line_id = ?",
        (line_id,),
    ).fetchone()
    if row is None or row["r1_ohm"] is None or row["x1_ohm"] is None:
        return None
    if row["r0_ohm"] is None or row["x0_ohm"] is None:
        return None
    return LineImpedance(
        r1_ohm=row["r1_ohm"], x1_ohm=row["x1_ohm"],
        r0_ohm=row["r0_ohm"], x0_ohm=row["x0_ohm"],
    )


def resolve_transformer_reactance(conn: sqlite3.Connection, ss_id: int) -> TransformerReactance | None:
    """Resolve reviewed GI identity and voltage to a traced workbook assumption.

    Missing, ambiguous, or unreviewed identities return None. Nameplate MVA
    is per unit, not summed bank capacity; impedance is not measured.
    """
    row = conn.execute(
        "SELECT t.site_name,s.voltage_kv FROM substation s JOIN site t USING(site_id) WHERE s.ss_id=?",
        (ss_id,),
    ).fetchone()
    if row is None:
        return None
    identity = (row[0].strip().upper(), row[1])
    matches = conn.execute(
        "SELECT count(*) FROM substation s JOIN site t USING(site_id) "
        "WHERE upper(trim(t.site_name))=? AND s.voltage_kv=?", identity,
    ).fetchone()[0]
    if matches != 1:
        return None
    entry = _ASSUMED_TRANSFORMER_NAMEPLATE.get(identity)
    if entry is None:
        return None
    mva, v_ref_kv, source = entry
    x_ohm = ASSUMED_TRANSFORMER_Z_PERCENT * (v_ref_kv ** 2) / mva
    return TransformerReactance(
        x_ohm=x_ohm, assumed=True,
        note=f"XT1 asumsi workbook {ASSUMED_TRANSFORMER_Z_PERCENT * 100:g}%, {mva:g}MVA/unit "
             f"@ {v_ref_kv:g}kV = {x_ohm:.3f} ohm ({source})",
    )


def resolve_pilot_t3(conn, relay_function_id):
    """Owner judgement 2026-09-30; only reviewed 150 kV circuit-2 directions.
    Pending individual maintenance reports. Never override a sourced timer.
    """
    row = conn.execute("""SELECT a.site_name,b.site_name,r.bay,s.voltage_kv,t.voltage_kv
        FROM relay_function f JOIN relay r USING(relay_id)
        JOIN substation s ON s.ss_id=r.ss_id JOIN site a ON a.site_id=s.site_id
        JOIN line l ON l.line_id=r.line_id
        JOIN substation t ON t.ss_id=CASE WHEN l.ss_from=r.ss_id THEN l.ss_to WHEN l.ss_to=r.ss_id THEN l.ss_from END
        JOIN site b ON b.site_id=t.site_id WHERE f.relay_function_id=? AND f.function_type='DIST'""", (relay_function_id,)).fetchone()
    allowed = {('DURIKOSAMBI','GROGOL BARU'),('GROGOL BARU','GROGOL'),('GROGOL','GROGOL BARU')}
    if row and tuple(row[:2]) in allowed and row[3] == row[4] == 150 and re.search(r'#2\s*$', row[2] or ''):
        return 1.6
    return None


def remote_endpoint(conn: sqlite3.Connection, line_id: int, local_ss_id: int) -> int | None:
    """ss_id ujung LAIN dari protected line (bukan sisi rele terpasang).
    None bila line tidak py salah satu ujung = local_ss_id (data rusak,
    seharusnya tidak terjadi krn line_id berasal dari relay.line_id yg
    sudah terverifikasi) atau ujung lain NULL (boundary line, ujung di
    luar scope -- lihat is_boundary di skema)."""
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT ss_from, ss_to FROM line WHERE line_id = ?", (line_id,)).fetchone()
    if row is None:
        return None
    if row["ss_from"] == local_ss_id:
        return row["ss_to"]
    if row["ss_to"] == local_ss_id:
        return row["ss_from"]
    return None


def incident_lines(conn: sqlite3.Connection, ss_id: int) -> list[sqlite3.Row]:
    """Semua line yang nempel di satu substation -- sama persis
    incident_lines() load.py, didefinisikan ulang di sini supaya modul
    ini tidak bergantung impor silang ke load.py (load.py mengimpor dari
    plms_etl, bukan sebaliknya -- jaga arah dependency tetap satu arah)."""
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """SELECT * FROM line WHERE (ss_from = ? OR ss_to = ?)
           AND COALESCE(out_of_service, 0) = 0 ORDER BY line_id""", (ss_id, ss_id),
    ).fetchall()


def build_remote_branches(conn: sqlite3.Connection, remote_ss_id: int, exclude_line_id: int) -> list[RemoteBranch]:
    """Semua line 1-hop dari remote bus, KECUALI protected line itu
    sendiri. Hanya kandidat numerik berimpedansi yang dikembalikan.
    topology_branch_paths() mencatat SEMUA cabang dan caller menahan
    perhitungan bila ada impedansi/ujung yang belum tersedia."""
    branches = []
    local_ss_id = remote_endpoint(conn, exclude_line_id, remote_ss_id)
    for line in incident_lines(conn, remote_ss_id):
        if line["line_id"] == exclude_line_id:
            continue
        if local_ss_id is not None and remote_endpoint(conn, line["line_id"], remote_ss_id) == local_ss_id:
            continue  # a parallel return to the local bus is not a forward path
        impedance = resolve_line_impedance(conn, line["line_id"])
        if impedance is None:
            continue
        branches.append(RemoteBranch(line_id=line["line_id"], impedance=impedance))
    return branches


def build_two_hop_branches(
    conn: sqlite3.Connection, remote_ss_id: int, exclude_line_id: int,
    one_hop_branches: list[RemoteBranch],
) -> list[TwoHopBranch]:
    """Utk tiap 1-hop, telusuri ujung jauhnya dan ambil SEMUA line lain
    di sana sbg kandidat 2-hop -- kecuali balik lagi ke remote_ss_id
    (siklus 2-line loop) atau ke protected line asal. Safety cap 3 hop
    dipatuhi krn fungsi ini TIDAK menelusuri lebih jauh dari ujung
    2-hop (tidak ada rekursi ke hop ke-3)."""
    two_hop: list[TwoHopBranch] = []
    local_ss_id = remote_endpoint(conn, exclude_line_id, remote_ss_id)
    for first in one_hop_branches:
        far_end_ss_id = remote_endpoint(conn, first.line_id, remote_ss_id)
        if far_end_ss_id is None:
            continue
        for second_line in incident_lines(conn, far_end_ss_id):
            if second_line["line_id"] in (exclude_line_id, first.line_id):
                continue
            # Cegah siklus: line kedua tidak boleh balik ke remote_ss_id
            # (loop 2-line antara remote bus & ujung jauh first-hop).
            if second_line["ss_from"] == remote_ss_id or second_line["ss_to"] == remote_ss_id:
                continue
            if local_ss_id is not None and remote_endpoint(conn, second_line["line_id"], far_end_ss_id) == local_ss_id:
                continue
            second_impedance = resolve_line_impedance(conn, second_line["line_id"])
            if second_impedance is None:
                continue
            two_hop.append(TwoHopBranch(
                first_hop_line_id=first.line_id, first_hop_impedance=first.impedance,
                second_hop_line_id=second_line["line_id"], second_hop_impedance=second_impedance,
            ))
    return two_hop


def topology_branch_paths(conn, remote_ss_id, protected_line_id):
    """Topological paths independent of impedance and transformer availability.

    Record the two-hop path even when its first segment has no impedance.
    Each path carries its ordered line IDs so branches sharing an endpoint
    remain distinguishable in calculation_branch.note.
    """
    local = remote_endpoint(conn, protected_line_id, remote_ss_id)
    paths = []

    def visit(bus, visited, path, gaps):
        for line in incident_lines(conn, bus):
            lid = line["line_id"]
            if lid == protected_line_id:
                continue
            other = remote_endpoint(conn, lid, bus)
            if other is not None and other in visited:
                continue
            missing = list(gaps)
            if resolve_line_impedance(conn, lid) is None:
                missing.append(f"line {lid}: line_electrical tidak lengkap")
            if other is None:
                missing.append(f"line {lid}: ujung remote tidak diketahui")
            ordered = path + [lid]
            paths.append({"line_id": lid, "path": ordered, "gaps": missing})
            if other is not None and len(ordered) < 2:
                visit(other, visited | {other}, ordered, missing)

    visit(remote_ss_id, {local, remote_ss_id}, [], [])
    return paths


def _path_trace(paths, extra_note="", selected_id=None, selected_two_hop=False):
    return [(p["line_id"], p["line_id"] == selected_id and (len(p["path"]) == 2) == selected_two_hop,
             "; ".join(filter(None, ["path=" + ">".join(map(str, p["path"])), *p["gaps"], extra_note])))
            for p in paths]


@dataclass(frozen=True)
class ZoneComputation:
    """Hasil 1 zona siap-simpan ke calculation_context/calculation_branch.
    result None bila status bukan complete (tidak ada Zone1Result/dst
    utk dipetakan -- caller cukup simpan status & branch_trace)."""
    zone: str
    status: str
    result: Zone1Result | Zone2Result | Zone3Result | None
    # Trace tiap kandidat yang DICOBA (bukan cuma yg dipakai) --
    # (line_id, is_selected, note) -- utk diisi ke calculation_branch.
    branch_trace: list[tuple[int, bool, str]]


def compute_relay_function_zones(
    conn: sqlite3.Connection, relay_function_id: int,
    scanning_timers: dict[int, ScanningTimers] | None = None,
) -> list[ZoneComputation]:
    """Hitung Z1/Z2/Z3 utk satu relay_function DIST. Mengembalikan list
    ZoneComputation (1 per zona) -- TIDAK menulis ke db, murni baca +
    hitung. Caller (belum ditulis -- bagian loader/CLI terpisah)
    bertanggung jawab INSERT ke calculation_context/calculation_branch.

    scanning_timers: hasil build_line_id_timer_map() (scanning_reference_
    loader.py), di-build SEKALI oleh caller lalu dipakai berulang --
    JANGAN dibangun ulang di sini per pemanggilan (184 rele DIST x scan
    penuh site pairs + CSV akan sangat lambat). None berarti caller
    belum menyediakan sumber T3 sama sekali (mis. pemanggilan test
    unit) -- fungsi tetap jalan normal, T3 genuinely tidak tersedia.
    """
    conn.row_factory = sqlite3.Row
    relay_row = conn.execute(
        """SELECT r.ss_id, r.line_id, r.ct_ratio, r.pt_ratio
           FROM relay_function rf JOIN relay r ON rf.relay_id = r.relay_id
           WHERE rf.relay_function_id = ?""",
        (relay_function_id,),
    ).fetchone()
    if relay_row is None or relay_row["line_id"] is None:
        return [ZoneComputation(zone=z, status=STATUS_INCOMPLETE_TOPOLOGY, result=None, branch_trace=[])
                for z in ("Z1", "Z2", "Z3")]

    local_ss_id = relay_row["ss_id"]
    line_id = relay_row["line_id"]
    line_impedance = resolve_line_impedance(conn, line_id)
    if line_impedance is None:
        return [ZoneComputation(zone=z, status=STATUS_INCOMPLETE_TOPOLOGY, result=None, branch_trace=[])
                for z in ("Z1", "Z2", "Z3")]

    ratio = _resolve_ct_pt_ratio(relay_row["ct_ratio"], relay_row["pt_ratio"])
    if ratio is None:
        return [ZoneComputation(zone=z, status=STATUS_INCOMPLETE_TOPOLOGY, result=None, branch_trace=[])
                for z in ("Z1", "Z2", "Z3")]

    results: list[ZoneComputation] = []

    z1 = calculate_zone1(line_impedance, ratio)
    results.append(ZoneComputation(zone="Z1", status=STATUS_COMPLETE, result=z1, branch_trace=[]))

    remote_ss_id = remote_endpoint(conn, line_id, local_ss_id)
    if remote_ss_id is None:
        # Boundary line (ujung remote di luar scope/topology_source NULL)
        # -- tidak bisa traversal cabang, tapi ini status berbeda dari
        # "topologi hilang": memang secara desain graph berhenti di sini.
        results.append(ZoneComputation(zone="Z2", status=STATUS_INCOMPLETE_EXTERNAL, result=None, branch_trace=[]))
        results.append(ZoneComputation(zone="Z3", status=STATUS_INCOMPLETE_EXTERNAL, result=None, branch_trace=[]))
        return results

    transformer = resolve_transformer_reactance(conn, remote_ss_id)
    transformer_x = transformer.x_ohm if transformer is not None else None
    transformer_note = transformer.note if transformer is not None and transformer.assumed else ""
    paths = topology_branch_paths(conn, remote_ss_id, line_id)
    paths_z2 = [p for p in paths if len(p["path"]) == 1]
    one_hop = build_remote_branches(conn, remote_ss_id, exclude_line_id=line_id)

    if transformer_x is None or any(p["gaps"] for p in paths_z2):
        # Keputusan pemilik data: tanpa XT1 (terukur ATAU asumsi
        # tertelusur), JANGAN hitung Z2/Z3 tanpa cap -- bisa overreach
        # salah. Tandai gap eksplisit.
        note = "XT1 (reaktansi trafo remote) tidak tersedia di plms.db" if transformer_x is None else "cabang remote belum lengkap"
        results.append(ZoneComputation(zone="Z2", status=STATUS_INCOMPLETE_TOPOLOGY, result=None, branch_trace=_path_trace(paths_z2, note)))
        results.append(ZoneComputation(zone="Z3", status=STATUS_INCOMPLETE_TOPOLOGY, result=None, branch_trace=_path_trace(paths, note)))
        return results

    z2_status = STATUS_COMPLETE_ASSUMED_TRANSFORMER if transformer.assumed else STATUS_COMPLETE
    z2 = calculate_zone2(line_impedance, one_hop, transformer_x, ratio)
    # Ambang T2: dari cabang yang DIPILIH sbg reach (konsisten Mathcad,
    # yg pakai X cabang tetangga yg sama dgn yg membentuk Z2mak menang).
    # Bila tidak ada cabang terpilih (fallback Z2min/cap trafo), pakai
    # ambang 0 -- overreach vs 0 selalu >=0, jatuh ke T2 lambat (aman:
    # tanpa info cabang spesifik, tidak ada dasar utk percepat timer).
    selected_x1sg = next(
        (0.8 * b.impedance.x1_ohm for b in one_hop if b.line_id == z2.selected_branch_line_id), 0.0,
    )
    z2_delay = zone2_delay(z2.z_primary_ohm, line_impedance.z1, selected_x1sg)
    z2 = replace(z2, delay_s=z2_delay)
    z2_trace = _path_trace(paths_z2, extra_note=transformer_note, selected_id=z2.selected_branch_line_id)
    results.append(ZoneComputation(zone="Z2", status=z2_status, result=z2, branch_trace=z2_trace))

    if any(p["gaps"] for p in paths):
        results.append(ZoneComputation(zone="Z3", status=STATUS_INCOMPLETE_TOPOLOGY, result=None,
                                       branch_trace=_path_trace(paths, "cabang 2-hop belum lengkap")))
        return results

    two_hop = build_two_hop_branches(conn, remote_ss_id, exclude_line_id=line_id, one_hop_branches=one_hop)
    # T3 TIDAK dihitung dari grading otomatis (dikonfirmasi Mathcad: 1.6s
    # itu konstanta tetap spesifik 1 kasus [LSI-Millenium], BUKAN rumus
    # universal -- data scraping scanning_reference.csv MEMBUKTIKAN T3
    # genuinely bervariasi per line: 1.6s/1.2s/0.6s/0s). Sumber T3
    # per-line yang benar ada di scanning_timers (dari
    # build_line_id_timer_map(), lihat scanning_reference_loader.py) --
    # cocokkan by protected line_id. Bila tidak ada entry utk line_id
    # ini (~83% baris CSV berhasil dipetakan, sisanya genuine gap --
    # lihat docstring scanning_reference_loader.py), delay_s tetap None
    # dan status ambiguous_branch (bukan complete): reach (impedansi)
    # tetap valid dihitung terlepas dari T3 diketahui atau tidak.
    z3_timer = (scanning_timers or {}).get(line_id)
    z3_delay = z3_timer.z3_time_s if z3_timer is not None else None
    assumed_t3 = False
    if z3_delay is None:
        z3_delay = resolve_pilot_t3(conn, relay_function_id)
        assumed_t3 = z3_delay is not None
    if assumed_t3:
        transformer_note += "; T3 ASUMSI 1.6 s: expert judgement pemilik data 2026-09-30, sirkit 2 pilot; menunggu laporan pengujian individu"
    z3 = calculate_zone3(line_impedance, one_hop, two_hop, transformer_x, ratio, delay_s=z3_delay)
    if z3_delay is None:
        z3_status = STATUS_AMBIGUOUS_BRANCH  # T3 genuinely tidak tersedia, prioritas di atas assumed-XT1
    else:
        z3_status = STATUS_COMPLETE_ASSUMED_TRANSFORMER if transformer.assumed else STATUS_COMPLETE
    if assumed_t3:
        z3_status = "complete_assumed_inputs"
    z3_trace = _path_trace(paths, extra_note=transformer_note, selected_id=z3.selected_branch_line_id, selected_two_hop=z3.selected_is_two_hop)
    results.append(ZoneComputation(zone="Z3", status=z3_status, result=z3, branch_trace=z3_trace))

    return results


def _resolve_ct_pt_ratio(ct_ratio_raw: str | None, pt_ratio_raw: str | None) -> CtPtRatio | None:
    """Parse string CT/PT ratio spt '2000/1' dan '150000/100' dari
    relay.ct_ratio/pt_ratio. None bila format tidak dikenali -- JANGAN
    menebak rasio, ini krusial utk konversi primer->sekunder."""
    ct = _parse_ratio_pair(ct_ratio_raw)
    pt = _parse_ratio_pair(pt_ratio_raw)
    if ct is None or pt is None:
        return None
    ct_primary, ct_secondary = ct
    # pt_ratio raw spt '150 kV/100 V' -- sisi kiri SUDAH dlm satuan kV
    # (angka literalnya = 150, bukan 150000), sisi kanan dlm V. CtPtRatio.
    # pt_primary_kv mengharap nilai kV langsung (properti n1 yang
    # mengalikan *1000 utk konversi ke V internal) -- regresi yg wajib
    # dicegah: membagi lagi dgn 1000 di sini akan salah 1.000.000x lipat
    # krn dobel konversi (sekali di sini, sekali lagi di dalam n1).
    pt_primary_kv, pt_secondary_v = pt
    return CtPtRatio(
        ct_primary_a=ct_primary, ct_secondary_a=ct_secondary,
        pt_primary_kv=pt_primary_kv, pt_secondary_v=pt_secondary_v,
    )


# Pola CT: '4000/5', '1000 / 1', '4000.0/1.0'. Pola PT: '150 kV/100 V'
# (dgn satuan literal, bukan cuma spasi) -- dikonfirmasi dari sample
# nyata relay.ct_ratio/pt_ratio, cuma 2 varian PT ('150 kV/100 V',
# '500 kV/100 V'). Regex ekstrak angka pertama tiap sisi '/', abaikan
# satuan apapun yang menyertainya -- TIDAK mengasumsikan satuan (kV/V)
# scr eksplisit dlm konversi, itu tanggung jawab _resolve_ct_pt_ratio()
# yang membagi hasil sisi primer dgn 1000 utk PT (krn CtPtRatio.
# pt_primary_kv butuh satuan kV, sementara raw sisi primer PT selalu
# dlm V spt '150 kV' -> 150000, makanya dibagi 1000 lagi di caller).
_RATIO_NUMBER = re.compile(r"[-+]?\d*\.?\d+")


def _parse_ratio_pair(raw: str | None) -> tuple[float, float] | None:
    if not raw or not isinstance(raw, str):
        return None
    sides = raw.split("/")
    if len(sides) != 2:
        return None
    numbers = []
    for side in sides:
        match = _RATIO_NUMBER.search(side)
        if match is None:
            return None
        numbers.append(float(match.group()))
    return numbers[0], numbers[1]


# ---------------------------------------------------------------- persist

def persist_calculation_context(
    conn: sqlite3.Connection, relay_function_id: int, line_id: int,
    computations: list[ZoneComputation], model_version: str | None = None,
) -> int:
    """Tulis hasil compute_relay_function_zones() ke calculation_context/
    calculation_branch. Idempoten: DELETE dulu baris lama utk
    relay_function_id ini (via calculation_context, cascade manual krn
    SQLite FK tidak auto-cascade tanpa PRAGMA) sebelum INSERT baru --
    aman dipanggil ulang tanpa duplikasi.

    line_id: protected line rele ini (sama utk semua zona 1 rele).
    model_version: diteruskan apa adanya ke tiap baris -- None berarti
    caller belum py concept versioning topologi (blm masuk scope
    sebelum v3; field ini disediakan skema utk nanti).

    Return: jumlah baris calculation_context yang ditulis (0-3, biasanya
    3 krn Z1/Z2/Z3 semua diproses walau statusnya bukan complete).
    """
    computed_at = datetime.date.today().isoformat()

    old_context_ids = [
        row[0] for row in conn.execute(
            "SELECT context_id FROM calculation_context WHERE relay_function_id = ?", (relay_function_id,),
        ).fetchall()
    ]
    if old_context_ids:
        placeholders = ",".join("?" * len(old_context_ids))
        conn.execute(f"DELETE FROM calculation_branch WHERE context_id IN ({placeholders})", old_context_ids)
        conn.execute("DELETE FROM calculation_context WHERE relay_function_id = ?", (relay_function_id,))

    written = 0
    for computation in computations:
        result = computation.result
        # Field yang HANYA ada di Zone2Result/Zone3Result (traversal),
        # tidak di Zone1Result (murni lokal, tanpa cabang/cap trafo).
        selected_branch_line_id = getattr(result, "selected_branch_line_id", None)

        context_id = conn.execute(
            """INSERT INTO calculation_context
               (relay_function_id, line_id, zone, direction, status,
                cumulative_r_ohm, cumulative_x_ohm,
                reach_secondary_r_ohm, reach_secondary_x_ohm,
                ground_fault_primary_r_ohm, ground_fault_primary_x_ohm,
                ground_fault_secondary_r_ohm, ground_fault_secondary_x_ohm,
                rfpp_primary_ohm, rfpp_secondary_ohm, reach_percent, delay_s,
                selected_branch_line_id, safety_cap_hops, model_version, computed_at)
               VALUES (?, ?, ?, 'FORWARD', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                relay_function_id, line_id, computation.zone, computation.status,
                result.z_primary_ohm.real if result else None,
                result.z_primary_ohm.imag if result else None,
                result.z_secondary_ohm.real if result else None,
                result.z_secondary_ohm.imag if result else None,
                result.z0_primary_ohm.real if result else None,
                result.z0_primary_ohm.imag if result else None,
                result.z0_secondary_ohm.real if result else None,
                result.z0_secondary_ohm.imag if result else None,
                result.rfpp_primary_ohm if result else None,
                result.rfpp_secondary_ohm if result else None,
                result.reach_percent if result else None,
                result.delay_s if result else None,
                selected_branch_line_id, SAFETY_CAP_HOPS, model_version, computed_at,
            ),
        ).lastrowid
        written += 1

        for step_order, (branch_line_id, is_selected, note) in enumerate(computation.branch_trace, start=1):
            conn.execute(
                """INSERT INTO calculation_branch
                   (context_id, step_order, line_id, is_selected, branch_status, note)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (context_id, step_order, branch_line_id, int(is_selected), computation.status, note or None),
            )

    return written
