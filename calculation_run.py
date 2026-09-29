#!/usr/bin/env python3
"""
v3a: CLI utk menjalankan compute_relay_function_zones() + persist_
calculation_context() thd SELURUH rele DIST di database, dan menulis
hasilnya ke calculation_context/calculation_branch.

TERPISAH dari load.py (bukan bagian pipeline v0-v2 utama) -- v3a masih
fase awal: Z2/Z3 tetap incomplete_topology utk hampir semua GI krn data
trafo tidak ada, kecuali whitelist eksplisit ss_id yang nameplate MVA-nya
sudah dibaca dari SLD (status complete_assumed_transformer, lihat
calculation_loader.py). Menyatukan ke load.py sekarang
akan memperlambat/mengacaukan rebuild pipeline yang sudah stabil utk
sesuatu yang belum banyak menghasilkan nilai. Jalankan manual:

    python3 calculation_run.py plms.db

Idempoten (persist_calculation_context menghapus baris lama per
relay_function_id sebelum insert baru) -- aman dijalankan ulang kapan
saja, mis. setelah scanning_reference.csv diperbarui atau load.py
di-rebuild ulang.
"""
from __future__ import annotations

import sqlite3
import argparse
from pathlib import Path

from calculation_loader import (
    STATUS_AMBIGUOUS_BRANCH,
    STATUS_COMPLETE,
    STATUS_COMPLETE_ASSUMED_TRANSFORMER,
    STATUS_INCOMPLETE_EXTERNAL,
    STATUS_INCOMPLETE_TOPOLOGY,
    compute_relay_function_zones,
    persist_calculation_context,
)
from scanning_reference_loader import build_line_id_timer_map


def run(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    scanning_timers = build_line_id_timer_map(conn)  # sekali saja, bukan per relay_function

    dist_relay_functions = conn.execute(
        """SELECT rf.relay_function_id, r.line_id
           FROM relay_function rf JOIN relay r ON rf.relay_id = r.relay_id
           WHERE rf.function_type = 'DIST' AND r.line_id IS NOT NULL"""
    ).fetchall()

    status_counts: dict[str, dict[str, int]] = {
        "Z1": {}, "Z2": {}, "Z3": {},
    }
    written_total = 0
    for row in dist_relay_functions:
        results = compute_relay_function_zones(conn, row["relay_function_id"], scanning_timers)
        written_total += persist_calculation_context(conn, row["relay_function_id"], row["line_id"], results)
        for computation in results:
            bucket = status_counts[computation.zone]
            bucket[computation.status] = bucket.get(computation.status, 0) + 1

    conn.commit()
    conn.close()

    print(f"=== v3a calculation_context ({db_path}) ===")
    print(f"Rele DIST diproses    : {len(dist_relay_functions)}")
    print(f"Baris context ditulis : {written_total}")
    for zone in ("Z1", "Z2", "Z3"):
        counts = status_counts[zone]
        parts = ", ".join(
            f"{status}={counts.get(status, 0)}"
            for status in ("complete_assumed_inputs", STATUS_COMPLETE, STATUS_COMPLETE_ASSUMED_TRANSFORMER, STATUS_INCOMPLETE_TOPOLOGY, STATUS_INCOMPLETE_EXTERNAL, STATUS_AMBIGUOUS_BRANCH)
        )
        print(f"{zone}: {parts}")
    print()
    print("Z2/Z3 incomplete_topology masih diharapkan utk sebagian besar GI --")
    print("data trafo (XT1) tidak tersedia di plms.db kecuali whitelist eksplisit")
    print("(lihat calculation_loader.py: _ASSUMED_TRANSFORMER_NAMEPLATE). GI di")
    print("whitelist itu tercatat status complete_assumed_transformer, BUKAN")
    print("complete -- reach-nya bertumpu pada asumsi 12,5% x MVA nameplate,")
    print("bukan Z% trafo terukur.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path")
    parser.add_argument("--sld-root", type=Path, help="generate Jakban relation audit after calculation")
    parser.add_argument("--audit-out", type=Path, default=Path(__file__).with_name("sld_audit"))
    parser.add_argument("--review", type=Path, help="reviewed GI crosswalk CSV")
    args = parser.parse_args()
    if args.review and not args.sld_root:
        parser.error("--review requires --sld-root")
    run(args.db_path)
    if args.sld_root:
        from sld_topology_audit import run as run_audit
        report = run_audit(args.sld_root, args.db_path, args.audit_out, args.review)
        print(f"Audit relasi SLD: {args.audit_out / 'report.md'}")
        print(f"Rele dengan bukti SLD: {report['summary']['relays_with_sld_evidence']}")
