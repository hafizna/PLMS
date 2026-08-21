"""Acceptance test v0/v1 terhadap workbook dan database nyata.

Test ini sengaja integration-level: tiga workbook dibaca, CSV dibangun, lalu
loader membuat SQLite baru di direktori sementara. Angka di bawah adalah
baseline workbook UPT 22-sheet yang di-commit pada 2026-08-21; perubahan
sumber harus terlihat sebagai perubahan test, bukan drift diam-diam.
"""
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

import pytest

import load
import plms_etl
import plms_v2_etl


ROOT = Path(__file__).resolve().parent


def csv_rows(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope='session')
def rebuilt(tmp_path_factory):
    work = tmp_path_factory.mktemp('plms-v1-rebuild')
    etl_out = work / 'etl_out'
    db_path = work / 'plms.db'
    plms_etl.main(str(ROOT), str(etl_out))
    v2b_out = work / 'v2b_out'
    plms_v2_etl.run(ROOT, v2b_out, observed_at='2026-08-21')
    load.main(str(etl_out), str(ROOT / 'alias_review.csv'), str(db_path), str(v2b_out))
    return etl_out, db_path


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_all_three_source_workbooks_are_read(rebuilt):
    etl_out, _ = rebuilt
    for filename in (plms_etl.DIGSILENT, plms_etl.UPT_DOC, plms_etl.OFFICIAL):
        assert (ROOT / filename).is_file()

    official = csv_rows(etl_out / 'official_profile.csv')
    assert len(official) == 7
    assert sum(int(r['nonempty_rows']) for r in official) == 590


def test_alias_gate_is_reproducible(rebuilt):
    etl_out, _ = rebuilt
    generated = csv_rows(etl_out / 'alias_review.csv')
    approved = csv_rows(ROOT / 'alias_review.csv')
    key = lambda r: tuple(r.get(k, '') for k in
                          ('gi_upt', 'alias_digsilent', 'voltage_kv', 'match', 'review'))
    assert sorted(map(key, generated)) == sorted(map(key, approved))


def test_database_integrity_and_current_scope_baseline(rebuilt):
    _, db_path = rebuilt
    with connect(db_path) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []

        # Workbook saat ini: 113 seed / 148 +1-hop dari DIgSILENT setelah
        # KOSAMBI BARU dikeluarkan eksplisit. 31 penghantar manual UPT
        # (4 Lontar/Dadap + 15 sisipan/ekstensi GI pasca-2021 [Metland,
        # Pasar Kemis Baru, Grogol Baru, ITS, Jatake Baru, Milenium,
        # Sindang Jaya] + 6 jaringan 500kV [GITET Balaraja/Muarakarang/
        # Tanjung Priok/Jawa 7] + 4 Gajah Tunggal/Pasar Kemis/Ulujami +
        # 2 Jatake-Tangerang/Kembangan-Petukangan -- lihat MANUAL_LINES di
        # load.py) membuat daftar UI menjadi 179.
        digs_seed = conn.execute('''
            SELECT count(*) FROM line l
            JOIN substation a ON l.ss_from = a.ss_id
            JOIN substation b ON l.ss_to = b.ss_id
            WHERE l.source = 'DIGSILENT'
              AND (a.hop_distance = 0 OR b.hop_distance = 0)
        ''').fetchone()[0]
        digs_hop1 = conn.execute('''
            SELECT count(*) FROM line l
            JOIN substation a ON l.ss_from = a.ss_id
            JOIN substation b ON l.ss_to = b.ss_id
            WHERE l.source = 'DIGSILENT' AND (a.in_scope = 1 OR b.in_scope = 1)
        ''').fetchone()[0]
        ui_total = conn.execute('''
            SELECT count(*) FROM line l
            JOIN substation a ON l.ss_from = a.ss_id
            JOIN substation b ON l.ss_to = b.ss_id
            WHERE a.in_scope = 1 OR b.in_scope = 1
        ''').fetchone()[0]
        assert digs_seed == 113
        assert digs_hop1 == 148
        assert ui_total == 179


def test_all_44_seed_gi_are_represented(rebuilt):
    _, db_path = rebuilt
    with connect(db_path) as conn:
        # Node 500kV sintetis (load.MANUAL_SUBSTATIONS) -- GITET/GISTET yg
        # ditemukan lewat analisis bay rele, BUKAN bagian 44 GI seed --
        # dikecualikan dari perbandingan represented==SEED_GI di bawah.
        # resolve_aliases (mis. 'TANJUNG PRIOK') jg masuk ss_alias krn
        # load_manual_substations() mendaftarkannya utk resolve_ss()
        # otomatis -- ikut dikecualikan.
        synthetic_500kv = {m['site_name'] for m in load.MANUAL_SUBSTATIONS}
        synthetic_500kv |= {
            alias for m in load.MANUAL_SUBSTATIONS
            for alias in m.get('resolve_aliases', [])
            if alias not in plms_etl.SEED_GI
        }

        represented = {
            row[0] for row in conn.execute('SELECT alias_text FROM ss_alias')
            if row[0] not in synthetic_500kv
        }
        represented |= {
            row[0] for row in conn.execute('''
                SELECT site.site_name
                FROM substation JOIN site USING (site_id)
                WHERE substation.topology_source IS NULL
            ''')
            if row[0] not in synthetic_500kv
        }
        assert represented == set(plms_etl.SEED_GI)
        # 13 -> 12: ALAM SUTERA dipindah ke MANUAL_ALIAS (plms_etl.py) --
        # ternyata cuma variasi ejaan dari node DIgSILENT 'ALAM SUTRA'
        # (hilang huruf 'E'), terhubung dua-arah terverifikasi ke
        # CILEDUG dan SUMMARECON. Bukan gap topologi, jadi topology_source
        # sekarang 'DIGSILENT' bukan NULL.
        # 12 + 3 node 500kV sintetis (GITET BALARAJA, GITET MUARAKARANG,
        # TANJUNG PRIOK 500KV -- lihat load.MANUAL_SUBSTATIONS) = 15.
        assert conn.execute('''
            SELECT count(*) FROM substation WHERE topology_source IS NULL
        ''').fetchone()[0] == 12 + len(load.MANUAL_SUBSTATIONS)


def test_voltage_and_line_metadata_are_not_defaulted(rebuilt):
    _, db_path = rebuilt
    with connect(db_path) as conn:
        unknown_nodes = conn.execute('''
            SELECT count(*) FROM substation
            WHERE topology_source = 'DIGSILENT' AND voltage_kv IS NULL
        ''').fetchone()[0]
        # Node tanpa bukti IHS maupun suffix tetap NULL, bukan diberi 150kV.
        assert unknown_nodes > 0
        assert conn.execute('''
            SELECT count(*) FROM line l
            JOIN substation a ON l.ss_from = a.ss_id
            JOIN substation b ON l.ss_to = b.ss_id
            WHERE l.source = 'DIGSILENT' AND (a.in_scope = 1 OR b.in_scope = 1)
              AND l.voltage_kv IS NULL
        ''').fetchone()[0] == 0
        assert conn.execute('''
            SELECT count(*) FROM line l
            JOIN substation a ON l.ss_from = a.ss_id
            JOIN substation b ON l.ss_to = b.ss_id
            WHERE l.source = 'DIGSILENT' AND (a.in_scope = 1 OR b.in_scope = 1)
              AND (l.technology IS NULL OR l.technology = '')
        ''').fetchone()[0] == 0


def test_forbidden_false_positive_aliases_stay_out(rebuilt):
    _, db_path = rebuilt
    with connect(db_path) as conn:
        for forbidden in ('KOSAMBI BARU', 'TELUKJAMBE'):
            count = conn.execute('''
                SELECT count(*)
                FROM substation ss JOIN site s USING (site_id)
                WHERE ss.in_scope = 1
                  AND (upper(s.site_name) = ? OR upper(ss.name_digsilent) = ?)
            ''', (forbidden, forbidden)).fetchone()[0]
            assert count == 0

        # TANGERANG memang seed tersendiri; yang dilarang adalah memakainya
        # sebagai alias diam-diam untuk TANGERANG BARU.
        rows = conn.execute('''
            SELECT a.alias_text, a.ss_id
            FROM ss_alias a WHERE a.alias_text IN ('TANGERANG', 'TANGERANG BARU')
        ''').fetchall()
        assert {r['alias_text'] for r in rows} == {'TANGERANG', 'TANGERANG BARU'}
        assert len({r['ss_id'] for r in rows}) == 2


def test_bay_dates_are_flagged_strings_and_per_km_is_consistent(rebuilt):
    _, db_path = rebuilt
    with connect(db_path) as conn:
        bays = [value for row in conn.execute('SELECT bay_from, bay_to FROM line')
                for value in row if value]
        assert not any(re.fullmatch(r'\d{4}-\d{2}-\d{2}(?: 00:00:00)?', value)
                       for value in bays)
        assert any(value.startswith('?') for value in bays)

        mismatches = conn.execute('''
            SELECT count(*) FROM line_electrical
            WHERE length_km IS NOT NULL AND length_km > 0 AND r1_ohm IS NOT NULL
              AND (r1_ohm_km IS NULL
                   OR abs(r1_ohm_km - r1_ohm / length_km) > 0.000001)
        ''').fetchone()[0]
        assert mismatches == 0


def test_site_is_clustered_across_voltage_nodes(rebuilt):
    _, db_path = rebuilt
    with connect(db_path) as conn:
        site_count = conn.execute('SELECT count(*) FROM site').fetchone()[0]
        node_count = conn.execute('SELECT count(*) FROM substation').fetchone()[0]
        assert site_count < node_count
        assert conn.execute('''
            SELECT count(*) FROM (
              SELECT site_id FROM substation GROUP BY site_id HAVING count(*) > 1
            )
        ''').fetchone()[0] > 0


def test_loader_is_idempotent(rebuilt, tmp_path):
    etl_out, _ = rebuilt
    db_path = tmp_path / 'idempotent.db'
    for _ in range(2):
        load.main(str(etl_out), str(ROOT / 'alias_review.csv'), str(db_path))
    with connect(db_path) as conn:
        # 1183 DIgSILENT + 31 manual (4 Lontar/Dadap + 15 sisipan/ekstensi
        # GI pasca-2021 + 6 jaringan 500kV + 4 Gajah Tunggal/Pasar Kemis/
        # Ulujami + 2 Jatake-Tangerang/Kembangan-Petukangan, lihat
        # MANUAL_LINES di load.py).
        assert conn.execute('SELECT count(*) FROM line').fetchone()[0] == 1214
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_v2_settings_and_official_history_are_loaded_with_provenance(rebuilt):
    _, db_path = rebuilt
    with connect(db_path) as conn:
        assert conn.execute('SELECT count(*) FROM relay').fetchone()[0] > 1200
        assert conn.execute('SELECT count(*) FROM relay_function').fetchone()[0] > 1400
        assert conn.execute('SELECT count(*) FROM relay_setting').fetchone()[0] > 10000
        assert conn.execute('SELECT count(*) FROM official_event').fetchone()[0] == 292
        assert conn.execute('SELECT count(*) FROM official_event_line').fetchone()[0] > 100
        assert conn.execute("SELECT count(*) FROM relay_source WHERE source_sheet='FR_OCR'").fetchone()[0] == 11
        assert conn.execute("SELECT count(*) FROM relay_setting WHERE source_sheet='FR_OCR'").fetchone()[0] == 66
        # 65->13, 142->38: load.MANUAL_SUBSTATIONS menambah node 500kV
        # sintetis (GITET BALARAJA, GITET MUARAKARANG) -- raw_gi sheet
        # CBF&CCP sering polos ('GITET Balaraja', tanpa '500KV' eksplisit
        # dalam teks; info voltage sebenarnya ada di kolom RATIO (kV)
        # terpisah yg tidak diekstrak plms_v2_etl.py ke row['gi']).
        # resolve_ss() sekarang py 2 opsi voltage (150/500) utk nama yg
        # sama -> AMBIGUOUS_VOLTAGE, row TIDAK masuk relay_source (hanya
        # v2_data_review) alih-alih dulu diam-diam nyasar ke node 150kV
        # yang salah. Ini peningkatan akurasi, bukan regresi -- perbaikan
        # lanjutan (plms_v2_etl.py membaca kolom RATIO (kV)) akan
        # mengembalikan rele ini dgn ss_id yang benar.
        assert conn.execute("SELECT count(*) FROM relay_source WHERE source_sheet='CBF&CCP'").fetchone()[0] == 13
        assert conn.execute("SELECT count(*) FROM relay_setting WHERE source_sheet='CBF&CCP'").fetchone()[0] == 38
        assert conn.execute("SELECT count(*) FROM v2_data_review WHERE review_type='SPECIAL_LAYOUT_PARSER'").fetchone()[0] == 0
        assert conn.execute('''
            SELECT count(*) FROM relay_setting
            WHERE source_workbook IS NULL OR source_sheet IS NULL OR source_row IS NULL
               OR source_column IS NULL OR source_header IS NULL OR source_hash IS NULL
        ''').fetchone()[0] == 0


def test_v2_current_setting_is_unique_per_function_parameter(rebuilt):
    _, db_path = rebuilt
    with connect(db_path) as conn:
        duplicates = conn.execute('''
            SELECT count(*) FROM (
              SELECT relay_function_id, parameter_name
              FROM relay_setting WHERE is_current = 1
              GROUP BY relay_function_id, parameter_name HAVING count(*) > 1
            )
        ''').fetchone()[0]
        assert duplicates == 0
        assert conn.execute('''
            SELECT count(DISTINCT r.line_id)
            FROM relay_setting rs JOIN relay r USING (relay_id)
            WHERE rs.is_current = 1 AND r.line_id IS NOT NULL
        ''').fetchone()[0] >= 50
