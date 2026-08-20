#!/usr/bin/env python3
"""
PLMS loader v1 — idempoten, dari output plms_etl.py + alias_review.csv
ke SQLite (schema.sql).

Urutan pengisian (FK harus sudah ada sebelum dirujuk):
  1. site + substation  (dari substation.csv; site 1:1 dengan substation di
     v1 -- pemisahan site x voltage disiapkan skema, dipakai penuh saat ada
     GI multi-voltage yang perlu clustering eksplisit)
  2. ss_alias            (dari alias_review.csv, baris match='exact')
  3. scope_definition    (44 GI seed, dari plms_etl.py SEED_GI)
  4. line + line_electrical  (dari line.csv, DIgSILENT)
  5. line manual         (dari MANUAL_LINES di bawah -- lihat
     legacy-knowledge/TOPOLOGI_GI_TANPA_DIGSILENT.md)
  6. bus_sc              (dari bus_sc.csv)

Idempoten: DROP+CREATE ulang semua tabel tiap run (v1 belum punya data
yang tidak-reproducible -- lihat catatan v2 soal relay_setting).

Pakai: python3 load.py <dir_etl_output> <alias_review.csv> <db_path>
"""
import sys, os, csv, sqlite3, json, datetime

SEED_GI = [
    'ALAM SUTERA','ANGKE','BALARAJA','CENGKARENG','CENGKARENG BARU','CIKUPA',
    'CILEDUG','CITRA HABITAT','CURUG','DAAN MOGOT','DADAP','DURIKOSAMBI',
    'GAJAH TUNGGAL','GROGOL','GROGOL BARU','ITS','JATAKE','JATAKE BARU',
    'KEBON JERUK','KEMBANGAN','LAUTAN STEEL','LONTAR','MAXIMANGANDO','METLAND',
    'MILENIUM','MUARAKARANG BARU','MUARAKARANG LAMA','NEW BALARAJA',
    'NEW SENAYAN','PANTAI INDAH KAPUK','PASAR KEMIS','PASAR KEMIS BARU',
    'SEPATAN','SEPATAN BARU','SINDANG JAYA','SPINMILL',
    'SUMMARECON GADING SERPONG','SUVARNA','TANGERANG','TANGERANG BARU',
    'TELUK NAGA','TIGARAKSA','TOMANG','ULUJAMI',
]

# Penghantar tanpa node DIgSILENT, ditelusuri manual dari dokumen UPT.
# Lihat legacy-knowledge/TOPOLOGI_GI_TANPA_DIGSILENT.md untuk bukti
# (kode aset TRS-xxxx-nnn.nnn + bay dua arah).
# Kunci substation dicocokkan ke site_name (bukan name_digsilent, karena
# GI-GI ini tidak punya node DIgSILENT).
MANUAL_LINES = [
    dict(line_name='LONTAR-TELUK NAGA', ss_from_name='LONTAR', ss_to_name='TELUK NAGA',
         voltage_kv=150.0, source='UPT_MANUAL'),
    dict(line_name='LONTAR-TANGERANG BARU', ss_from_name='LONTAR', ss_to_name='TANGERANG BARU',
         voltage_kv=150.0, source='UPT_MANUAL'),
    dict(line_name='DADAP-TELUK NAGA', ss_from_name='DADAP', ss_to_name='TELUK NAGA',
         voltage_kv=150.0, source='UPT_MANUAL'),
    dict(line_name='DADAP-LONTAR', ss_from_name='DADAP', ss_to_name='LONTAR',
         voltage_kv=150.0, source='UPT_MANUAL'),
]

# Sheet IHS (sumber bus_sc) dan sheet DB (sumber topologi/substation) di
# DIgSILENT TIDAK selalu konsisten penamaan node yang sama -- ejaan beda
# antar sheet dalam satu file yang sama, terpisah dari isu alias GI-UPT.
# Hanya dipetakan untuk node yang relevan scope Durikosambi (44 seed);
# node IHS lain yang tak match (area Jateng/Jatim/Bali dll) dibiarkan
# ter-skip -- di luar scope v1.
BUS_SC_ALIAS = {
    'DURIKOSAMBI7': 'DKSBI7',   # sheet DB pakai singkatan DKSBI, sheet IHS pakai nama penuh
    'DAAN MOGOT': 'DAAN MOGOT GIS',
}


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def to_bool(v):
    return 1 if str(v).strip().lower() == 'true' else 0


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_int(v):
    f = to_float(v)
    return int(f) if f is not None else None


def load_schema(conn, schema_path):
    with open(schema_path, encoding='utf-8') as f:
        conn.executescript(f.read())


def load_substations(conn, rows):
    """substation.csv -> site (1 site per substation row in v1) + substation.
    Identity key untuk lookup nanti: name_digsilent bila ada, else site_name."""
    key_to_ssid = {}
    for r in rows:
        name_dig = (r['name_digsilent'] or '').strip()
        site_name = (r['site_name'] or '').strip()
        key = name_dig or site_name
        if not key:
            continue
        cur = conn.execute(
            'INSERT INTO site (site_name, is_gis) VALUES (?, NULL)', (site_name,))
        site_id = cur.lastrowid
        cur = conn.execute(
            '''INSERT INTO substation
               (site_id, voltage_kv, name_digsilent, in_scope, hop_distance, topology_source)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (site_id, to_float(r['voltage_kv']), name_dig or None,
             to_bool(r['in_seed']), to_int(r['hop_distance']),
             (r['topology_source'] or '').strip() or None))
        key_to_ssid[key] = cur.lastrowid
    return key_to_ssid


def load_aliases(conn, rows, key_to_ssid):
    """alias_review.csv, baris match='exact' -> ss_alias. Kandidat 'partial'/
    'rejected' TIDAK dimuat -- itu jejak keputusan kurasi, bukan identitas DB."""
    n = 0
    for r in rows:
        if r['match'] != 'exact':
            continue
        alias_name = (r['alias_digsilent'] or '').strip()
        if not alias_name or alias_name not in key_to_ssid:
            continue
        ss_id = key_to_ssid[alias_name]
        conn.execute(
            '''INSERT INTO ss_alias (ss_id, alias_text, source_system, is_curated)
               VALUES (?, ?, 'UPT_DKSBI', 1)''',
            (ss_id, r['gi_upt'].strip()))
        n += 1
    return n


def load_scope(conn):
    conn.execute(
        '''INSERT INTO scope_definition
           (scope_name, seed_substations, hop_depth, snapshot_date, notes)
           VALUES (?, ?, ?, ?, ?)''',
        ('UPT Durikosambi v0/v1 seed', json.dumps(SEED_GI), 1,
         datetime.date.today().isoformat(),
         '44 GI seed dari 5 ULTG (Angke, Cikupa, Citra Raya, Durikosambi, '
         'Tangkot); scope topologis, bukan organisasi. Lihat PLMS_Rebuild_Prompt_v2.md.'))


def load_lines(conn, rows, key_to_ssid):
    n_ok, n_skip = 0, 0
    for r in rows:
        ss_from = key_to_ssid.get((r['ss_from_raw'] or '').strip())
        ss_to = key_to_ssid.get((r['ss_to_raw'] or '').strip())
        if ss_from is None or ss_to is None:
            n_skip += 1
            continue
        _, kv = None, None
        cur = conn.execute(
            '''INSERT INTO line
               (line_name, line_name_digsilent, ss_from, bay_from, ss_to, bay_to,
                technology, out_of_service, is_boundary, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'DIGSILENT')''',
            (r['line_name'], r['line_name'], ss_from, r['bay_from'],
             ss_to, r['bay_to'], r['type_raw'],
             to_int(r['out_of_service']), to_bool(r['is_boundary'])))
        line_id = cur.lastrowid
        conn.execute(
            '''INSERT INTO line_electrical
               (line_id, length_km, z1_ohm, phiz1_deg, r1_ohm, x1_ohm, r0_ohm, x0_ohm,
                r1_ohm_km, x1_ohm_km, r0_ohm_km, x0_ohm_km, k0, phik0_deg,
                irated_ka, ice_a, earth_resistivity, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DIGSILENT')''',
            (line_id, to_float(r['length_km']), to_float(r['z1_ohm']), to_float(r['phiz1_deg']),
             to_float(r['r1_ohm']), to_float(r['x1_ohm']), to_float(r['r0_ohm']), to_float(r['x0_ohm']),
             to_float(r['r1_ohm_km']), to_float(r['x1_ohm_km']), to_float(r['r0_ohm_km']), to_float(r['x0_ohm_km']),
             to_float(r['k0']), to_float(r['phik0_deg']),
             to_float(r['irated_ka']), to_float(r['ice_a']), to_float(r['earth_resistivity'])))
        n_ok += 1
    return n_ok, n_skip


def load_manual_lines(conn, key_to_ssid):
    """Penghantar tanpa DIgSILENT, ditelusuri manual dari dokumen UPT.
    ss_from/ss_to di-resolve via site_name (bukan name_digsilent)."""
    n_ok, n_skip = 0, 0
    for m in MANUAL_LINES:
        ss_from = key_to_ssid.get(m['ss_from_name'])
        ss_to = key_to_ssid.get(m['ss_to_name'])
        if ss_from is None or ss_to is None:
            n_skip += 1
            continue
        conn.execute(
            '''INSERT INTO line
               (line_name, ss_from, ss_to, voltage_kv, is_boundary, source)
               VALUES (?, ?, ?, ?, 0, ?)''',
            (m['line_name'], ss_from, ss_to, m['voltage_kv'], m['source']))
        n_ok += 1
    return n_ok, n_skip


def load_bus_sc(conn, rows, key_to_ssid):
    n_ok, n_skip = 0, 0
    for r in rows:
        raw = (r['ss_raw'] or '').strip()
        ss_id = key_to_ssid.get(raw) or key_to_ssid.get(BUS_SC_ALIAS.get(raw, ''))
        if ss_id is None:
            n_skip += 1
            continue
        conn.execute(
            '''INSERT INTO bus_sc
               (ss_id, bus_name, voltage_kv, r1_pu, x1_pu, r2_pu, x2_pu, r0_pu, x0_pu,
                isc_1ph_ka, isc_3ph_ka, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DIGSILENT')''',
            (ss_id, r['bus_name'], to_float(r['voltage_kv']),
             to_float(r['r1_pu']), to_float(r['x1_pu']), to_float(r['r2_pu']), to_float(r['x2_pu']),
             to_float(r['r0_pu']), to_float(r['x0_pu']),
             to_float(r['isc_1ph_ka']), to_float(r['isc_3ph_ka'])))
        n_ok += 1
    return n_ok, n_skip


def main(etl_dir, alias_path, db_path):
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')

    if os.path.exists(db_path):
        os.remove(db_path)          # idempoten: rebuild penuh tiap run
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys = ON')
    load_schema(conn, schema_path)

    substation_rows = read_csv(os.path.join(etl_dir, 'substation.csv'))
    alias_rows = read_csv(alias_path)
    line_rows = read_csv(os.path.join(etl_dir, 'line.csv'))
    bus_rows = read_csv(os.path.join(etl_dir, 'bus_sc.csv'))

    key_to_ssid = load_substations(conn, substation_rows)
    n_alias = load_aliases(conn, alias_rows, key_to_ssid)
    load_scope(conn)
    n_line_ok, n_line_skip = load_lines(conn, line_rows, key_to_ssid)
    n_manual_ok, n_manual_skip = load_manual_lines(conn, key_to_ssid)
    n_bus_ok, n_bus_skip = load_bus_sc(conn, bus_rows, key_to_ssid)

    conn.commit()

    print('=== PLMS loader v1 ===')
    print(f'Substation dimuat     : {len(key_to_ssid)}')
    print(f'Alias dimuat          : {n_alias}')
    print(f'Line DIgSILENT dimuat : {n_line_ok}  (skip FK hilang: {n_line_skip})')
    print(f'Line manual dimuat    : {n_manual_ok}  (skip FK hilang: {n_manual_skip})')
    print(f'Bus SC dimuat         : {n_bus_ok}  (skip di luar scope: {n_bus_skip})')
    print()
    print('Bus SC skip: node bus_sc.csv (sheet IHS) di luar 44 GI seed dan')
    print('tetangganya (mis. area Jateng/Jatim/Bali) -- diharapkan, bukan bug.')
    print('Lihat BUS_SC_ALIAS di load.py untuk kasus beda ejaan IHS vs DB yang')
    print('sudah dipetakan (DURIKOSAMBI7->DKSBI7, DAAN MOGOT->DAAN MOGOT GIS).')

    if n_line_skip or n_manual_skip:
        print()
        print('PERINGATAN: line.csv/MANUAL_LINES ada FK tidak resolve -- ini TIDAK')
        print('diharapkan (line seharusnya selalu antar node yang sudah dimuat).')
        print('Cek substation.csv konsisten dengan line.csv yang dipakai.')

    conn.close()


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print('Pakai: python3 load.py <dir_etl_output> <alias_review.csv> <db_path>')
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
