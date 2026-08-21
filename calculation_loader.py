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
Keputusan pemilik data: kalau XT1 tidak tersedia, JANGAN hitung Z2/Z3
tanpa cap (bisa overreach salah) -- tandai status incomplete_topology
persis di titik itu, sesuai prinsip "jangan mengestimasi line/impedansi
yang hilang" di prompt v2. resolve_transformer_reactance() SELALU
mengembalikan None saat ini -- disediakan sbg hook satu titik utk nanti
kalau sumber data trafo tersedia (lihat AskUserQuestion di sesi ini:
user blm py sumber, ini murni placeholder eksplisit, BUKAN estimasi).

Modul ini TIDAK mengubah plms.db langsung -- fungsi build_*() murni
baca (read-only), caller (load.py atau CLI terpisah) yang menulis ke
calculation_context/calculation_branch.
"""
from __future__ import annotations

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

SAFETY_CAP_HOPS = 3


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


def resolve_transformer_reactance(conn: sqlite3.Connection, ss_id: int) -> float | None:
    """SELALU None saat ini -- TIDAK ADA sumber data trafo (MVA/impedansi
    %) di plms.db (dikonfirmasi: 0 function_type trafo, 0 tabel
    transformer). Hook satu titik: begitu sumber data trafo tersedia
    (mis. ETL baru dari dokumen terpisah), ganti isi fungsi ini saja --
    seluruh pemanggil (build_calculation_context) otomatis ikut
    terupdate tanpa perlu disentuh.
    """
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
        "SELECT * FROM line WHERE ss_from = ? OR ss_to = ?", (ss_id, ss_id),
    ).fetchall()


def build_remote_branches(conn: sqlite3.Connection, remote_ss_id: int, exclude_line_id: int) -> list[RemoteBranch]:
    """Semua line 1-hop dari remote bus, KECUALI protected line itu
    sendiri. Line tanpa line_electrical (None) DILEWATI -- bukan
    dimasukkan dgn impedansi tebakan; ini mengurangi kandidat yg
    dipertimbangkan Zone-2/3, bukan menyembunyikan gap (candidates_
    considered pada hasil tetap mencerminkan yg BERHASIL dipakai)."""
    branches = []
    for line in incident_lines(conn, remote_ss_id):
        if line["line_id"] == exclude_line_id:
            continue
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
            second_impedance = resolve_line_impedance(conn, second_line["line_id"])
            if second_impedance is None:
                continue
            two_hop.append(TwoHopBranch(
                first_hop_line_id=first.line_id, first_hop_impedance=first.impedance,
                second_hop_line_id=second_line["line_id"], second_hop_impedance=second_impedance,
            ))
    return two_hop


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

    transformer_x = resolve_transformer_reactance(conn, remote_ss_id)
    one_hop = build_remote_branches(conn, remote_ss_id, exclude_line_id=line_id)

    if transformer_x is None:
        # Keputusan pemilik data: tanpa XT1, JANGAN hitung Z2/Z3 tanpa
        # cap -- bisa overreach salah. Tandai gap eksplisit.
        note = "XT1 (reaktansi trafo remote) tidak tersedia di plms.db"
        trace = [(b.line_id, False, note) for b in one_hop]
        results.append(ZoneComputation(zone="Z2", status=STATUS_INCOMPLETE_TOPOLOGY, result=None, branch_trace=trace))
        results.append(ZoneComputation(zone="Z3", status=STATUS_INCOMPLETE_TOPOLOGY, result=None, branch_trace=trace))
        return results

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
    z2_trace = [(b.line_id, b.line_id == z2.selected_branch_line_id, "") for b in one_hop]
    results.append(ZoneComputation(zone="Z2", status=STATUS_COMPLETE, result=z2, branch_trace=z2_trace))

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
    z3 = calculate_zone3(line_impedance, one_hop, two_hop, transformer_x, ratio, delay_s=z3_delay)
    z3_status = STATUS_COMPLETE if z3_delay is not None else STATUS_AMBIGUOUS_BRANCH
    z3_trace = (
        [(b.line_id, b.line_id == z3.selected_branch_line_id and not z3.selected_is_two_hop, "") for b in one_hop]
        + [(b.second_hop_line_id, b.second_hop_line_id == z3.selected_branch_line_id and z3.selected_is_two_hop, "")
           for b in two_hop]
    )
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
