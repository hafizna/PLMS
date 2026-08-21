#!/usr/bin/env python3
"""
PLMS loader v2 — idempoten, dari output plms_etl.py + alias_review.csv +
output plms_v2_etl.py ke SQLite (schema.sql).

Urutan pengisian (FK harus sudah ada sebelum dirujuk):
  1. site + substation  (site fisik dikelompokkan menurut site_name;
     substation adalah site x level tegangan/node DIgSILENT)
  2. ss_alias            (dari alias_review.csv, baris match='exact')
  3. scope_definition    (44 GI seed, dari plms_etl.py SEED_GI)
  4. line + line_electrical  (dari line.csv, DIgSILENT)
  5. line manual         (dari MANUAL_LINES di bawah -- lihat
     legacy-knowledge/TOPOLOGI_GI_TANPA_DIGSILENT.md)
  6. bus_sc              (dari bus_sc.csv)
  7. relay/function/setting + official history (opsional, dari v2b_out)

Idempoten: database dibangun di file sementara lalu diganti atomik setelah
integrity/FK check lulus. Database lama tetap utuh bila rebuild gagal.

Pakai: python3 load.py <dir_etl_output> <alias_review.csv> <db_path> [v2b_out]
"""
import sys, os, csv, sqlite3, json, datetime, re

from plms_etl import bay_to_gi_lawan, canon

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
    with open(path, newline='', encoding='utf-8-sig') as f:
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
    """substation.csv -> site fisik + node site/tegangan.

    Identity key untuk lookup nanti: name_digsilent bila ada, else site_name.
    """
    key_to_ssid = {}
    site_by_name = {}
    for r in rows:
        name_dig = (r['name_digsilent'] or '').strip()
        site_name = (r['site_name'] or '').strip()
        key = name_dig or site_name
        if not key:
            continue
        site_id = site_by_name.get(site_name)
        if site_id is None:
            cur = conn.execute(
                'INSERT INTO site (site_name, is_gis) VALUES (?, NULL)', (site_name,))
            site_id = cur.lastrowid
            site_by_name[site_name] = site_id
        cur = conn.execute(
            '''INSERT INTO substation
               (site_id, voltage_kv, name_digsilent, in_scope, hop_distance, topology_source)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (site_id, to_float(r['voltage_kv']), name_dig or None,
             to_bool(r.get('in_scope', r.get('in_seed'))), to_int(r['hop_distance']),
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
        cur = conn.execute(
            '''INSERT INTO line
               (line_name, line_name_digsilent, ss_from, bay_from, ss_to, bay_to,
                technology, voltage_kv, conductor_type, rating_a,
                out_of_service, is_boundary, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DIGSILENT')''',
            (r['line_name'], r['line_name'], ss_from, r['bay_from'],
             ss_to, r['bay_to'], r.get('technology'), to_float(r.get('voltage_kv')),
             r.get('conductor_type'), to_float(r.get('rating_a')),
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


# --------------------------------------------------------------- v2 relay data

GI_LABEL = re.compile(r'^(?:GISTET|GITET|GIS|GI)\s*(?:(?:20|70|150|500)\s*KV)?\s*', re.I)


def normalized_gi(value):
    """Return (canonical physical name, explicit voltage or None)."""
    raw = re.sub(r'\s+', ' ', str(value or '').strip().upper())
    voltage_match = re.search(r'\b(20|70|150|500)\s*KV\b', raw)
    voltage = float(voltage_match.group(1)) if voltage_match else None
    raw = re.sub(r'^.*?\s-\s(?=(?:GISTET|GITET|GIS|GI)\b)', '', raw)
    raw = GI_LABEL.sub('', raw).strip(' -')
    return canon(raw), voltage


def build_ss_lookup(conn):
    lookup = {}
    rows = conn.execute('''
        SELECT ss.ss_id, ss.voltage_kv, s.site_name, ss.name_digsilent
        FROM substation ss JOIN site s USING (site_id)
    ''').fetchall()
    for ss_id, voltage, site_name, name_digsilent in rows:
        for raw in (site_name, name_digsilent):
            name, _ = normalized_gi(raw)
            if name:
                lookup.setdefault(name, set()).add((ss_id, voltage))
    for ss_id, alias in conn.execute('SELECT ss_id, alias_text FROM ss_alias'):
        name, _ = normalized_gi(alias)
        voltage = conn.execute('SELECT voltage_kv FROM substation WHERE ss_id=?', (ss_id,)).fetchone()[0]
        if name:
            lookup.setdefault(name, set()).add((ss_id, voltage))
    return lookup


def resolve_ss(lookup, raw_gi):
    name, voltage = normalized_gi(raw_gi)
    options = sorted(lookup.get(name, set())) if name else []
    if voltage is not None:
        exact = [ss_id for ss_id, kv in options if kv is not None and abs(kv - voltage) < 0.001]
        if len(exact) == 1:
            return exact[0], 'EXACT_NAME_VOLTAGE'
    ids = sorted({ss_id for ss_id, _ in options})
    if len(ids) == 1:
        return ids[0], 'EXACT_NAME'
    return None, 'UNRESOLVED' if not ids else 'AMBIGUOUS_VOLTAGE'


def circuit_numbers(value):
    raw = str(value or '').upper()
    return set(re.findall(r'(?<!\d)([12])(?!\d)', raw))


def line_circuit(row, sibling_names=None):
    """Nomor sirkit dari circuit_no (belum pernah diisi loader manapun --
    kolom disiapkan skema, tapi selalu NULL) atau fallback ke akhiran nama.

    Fallback dulu HANYA menangkap akhiran didahului separator eksplisit
    ('-', '#', spasi) -- gagal utk nama tanpa separator ('CITRA-TRKSA1'),
    yang menyebabkan resolve_lines() tak bisa mempersempit sirkit lewat
    raw_circuit meski datanya ada (AMBIGUOUS_LINE utk 12 rele, mis.
    CITRA HABITAT<->TIGARAKSA #1 vs #2).

    Perluasan ini menangkap akhiran TANPA separator juga ('TRKSA1' -> '1'),
    tapi HANYA kalau sibling_names (nama line lain yg bersaing sbg
    kandidat pada resolve yang sama) memuat base name yang sama dgn
    akhiran sirkit lain -- itu bukti pasangan sirkit nyata (mis.
    'CITRA-TRKSA1' & 'CITRA-TRKSA 2' sama-sama ada). Tanpa bukti pasangan,
    digit akhir bisa jadi bagian nama substation itu sendiri (mis.
    'ASAHI-ASAHI2', endpoint 'ASAHIMAS 2') -- TIDAK dianggap sirkit."""
    if row['circuit_no']:
        numbers = circuit_numbers(row['circuit_no'])
        if numbers:
            return next(iter(numbers))
    name = row['line_name'] or ''
    match = re.search(r'(?:-|#|\s)([12])\s*$', name)
    if match:
        return match.group(1)
    match = re.search(r'([12])\s*$', name.strip())
    if not match:
        return None
    if sibling_names:
        base = name.strip()[:match.start(1)].rstrip('-# ').strip()
        other_digit = '2' if match.group(1) == '1' else '1'
        has_pair = any(
            other.strip()[:len(base)].rstrip('-# ').strip() == base
            and other.strip() != name.strip()
            for other in sibling_names
        )
        if has_pair:
            return match.group(1)
    return None


def incident_lines(conn, ss_id):
    conn.row_factory = sqlite3.Row
    return conn.execute('''
        SELECT l.*, CASE WHEN l.ss_from = ? THEN stsite.site_name ELSE sfsite.site_name END other_site
        FROM line l
        LEFT JOIN substation sf ON l.ss_from = sf.ss_id
        LEFT JOIN site sfsite ON sf.site_id = sfsite.site_id
        LEFT JOIN substation st ON l.ss_to = st.ss_id
        LEFT JOIN site stsite ON st.site_id = stsite.site_id
        WHERE l.ss_from = ? OR l.ss_to = ?
    ''', (ss_id, ss_id, ss_id)).fetchall()


def resolve_lines(conn, ss_id, raw_bay, raw_circuit='', allow_multiple=False):
    """Resolve only from exact incident endpoint + opponent + circuit evidence."""
    if ss_id is None:
        return [], 'SUBSTATION_UNRESOLVED'
    lines = incident_lines(conn, ss_id)
    if not lines:
        return [], 'NO_INCIDENT_LINE'
    bay = str(raw_bay or '')
    target = bay_to_gi_lawan(bay)
    target_name = normalized_gi(target)[0] if target else None
    if target_name:
        lines = [row for row in lines if normalized_gi(row['other_site'])[0] == target_name]
    else:
        bay_norm = normalized_gi(re.sub(r'\b(?:PHT|UGC|SKTT|BAY)\b', ' ', bay))[0] or ''
        named = [row for row in lines
                 if normalized_gi(row['other_site'])[0]
                 and normalized_gi(row['other_site'])[0] in bay_norm]
        if named:
            lines = named
        else:
            return [], 'OPPONENT_UNRESOLVED'
    wanted_circuits = circuit_numbers(raw_circuit) or circuit_numbers(bay)
    if wanted_circuits:
        sibling_names = [row['line_name'] for row in lines]
        with_circuit = [row for row in lines
                         if line_circuit(row, sibling_names) in wanted_circuits]
        if with_circuit:
            lines = with_circuit
    is_cable = bool(re.search(r'\b(?:UGC|SKTT|CABLE|KABEL)\b', bay, re.I))
    if len(lines) > 1:
        technology_match = [row for row in lines if (row['technology'] == 'CAB') == is_cable]
        if technology_match:
            lines = technology_match
    ids = sorted({row['line_id'] for row in lines})
    if not ids:
        return [], 'NO_EXACT_LINE'
    if allow_multiple:
        return ids, 'EXACT_MULTI' if len(ids) > 1 else 'EXACT'
    return (ids, 'EXACT') if len(ids) == 1 else ([], 'AMBIGUOUS_LINE')


def first_value(rows, field):
    return next((row.get(field) for row in rows if (row.get(field) or '').strip()), None)


def add_v2_review(conn, review_type, source_ref='', identity_key='', logical_source='',
                  detail='', recommended_action=''):
    conn.execute('''INSERT INTO v2_data_review
        (review_type, source_ref, identity_key, logical_source, detail, recommended_action)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (review_type, source_ref, identity_key, logical_source, detail, recommended_action))


def load_v2(conn, v2_dir):
    candidates = read_csv(os.path.join(v2_dir, 'relay_candidates.csv'))
    settings = read_csv(os.path.join(v2_dir, 'relay_settings.csv'))
    events = read_csv(os.path.join(v2_dir, 'official_events.csv'))
    reviews = read_csv(os.path.join(v2_dir, 'review_queue.csv'))
    for row in reviews:
        add_v2_review(conn, row['review_type'], row['source_ref'], row['identity_key'],
                      row['logical_source'], row['detail'], row['recommended_action'])

    ss_lookup = build_ss_lookup(conn)
    conflict_keys = {row['identity_key'] for row in reviews
                     if row['review_type'] == 'IDENTITY_METADATA_CONFLICT'}
    line_expected = {'LCD+DIST', 'OCR', 'DIFF Pilot', 'AR', 'Synchro'}
    resolved = []
    for row in candidates:
        ss_id, ss_status = resolve_ss(ss_lookup, row['gi'])
        line_ids, line_status = resolve_lines(conn, ss_id, row['bay'], row['circuit'])
        row['_ss_id'], row['_ss_status'] = ss_id, ss_status
        row['_line_id'], row['_line_status'] = (line_ids[0] if line_ids else None), line_status
        if ss_id is None:
            add_v2_review(conn, 'SUBSTATION_LINK', row['candidate_ref'], row['identity_key'],
                          row['logical_source'], f"{ss_status}: {row['gi']}",
                          'Map the exact GI alias before loading this relay candidate.')
            continue
        if not line_ids and row['logical_source'] in line_expected:
            add_v2_review(conn, 'LINE_LINK', row['candidate_ref'], row['identity_key'],
                          row['logical_source'], f"{line_status}: {row['bay']} / {row['circuit']}",
                          'Keep site-level until exact opponent and circuit are verified.')
        if row['identity_confidence'] == 'LOW' or row['identity_key'] in conflict_keys:
            row['_db_identity'] = f"{row['identity_key']}|SOURCE|{row['candidate_ref']}"
        else:
            row['_db_identity'] = row['identity_key']
        resolved.append(row)

    groups = {}
    for row in resolved:
        groups.setdefault(row['_db_identity'], []).append(row)
    candidate_map = {}
    for db_identity, group in sorted(groups.items()):
        ss_ids = {row['_ss_id'] for row in group}
        if len(ss_ids) != 1:
            for row in group:
                add_v2_review(conn, 'IDENTITY_SUBSTATION_CONFLICT', row['candidate_ref'], db_identity,
                              row['logical_source'], 'Exact identity resolved to multiple substations.',
                              'Do not merge until physical identity is verified.')
            continue
        linked_lines = {row['_line_id'] for row in group if row['_line_id'] is not None}
        line_id = next(iter(linked_lines)) if len(linked_lines) == 1 else None
        if len(linked_lines) > 1:
            add_v2_review(conn, 'IDENTITY_LINE_CONFLICT', ' | '.join(r['candidate_ref'] for r in group),
                          db_identity, '', f"Resolved line IDs: {sorted(linked_lines)}",
                          'Verify physical IED association before assigning a line.')
        first = group[0]
        cur = conn.execute('''INSERT INTO relay
            (ss_id, bay, line_id, manufacturer, model, serial_no, ct_ratio, pt_ratio, status,
             pst_asset_id, identity_key, identity_confidence, identity_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (first['_ss_id'], first_value(group, 'bay'), line_id,
             first_value(group, 'manufacturer'), first_value(group, 'model'),
             first_value(group, 'serial_no'), first_value(group, 'ct_ratio'),
             first_value(group, 'pt_ratio'), first_value(group, 'status'),
             first_value(group, 'asset_id'), db_identity, first['identity_confidence'],
             'REVIEW' if first['identity_confidence'] == 'LOW' or first['identity_key'] in conflict_keys else 'EXACT'))
        relay_id = cur.lastrowid
        function_ids = {}
        for row in group:
            function_key = (row['function_type'], row['logical_source'])
            if function_key not in function_ids:
                function_ids[function_key] = conn.execute('''INSERT INTO relay_function
                    (relay_id, function_type, coordination_class, source_logical, status)
                    VALUES (?, ?, ?, ?, ?)''',
                    (relay_id, row['function_type'], row['coordination_class'], row['logical_source'],
                     'REVIEW' if row['coordination_class'] == 'REVIEW' else 'ACTIVE')).lastrowid
            function_id = function_ids[function_key]
            conn.execute('''INSERT INTO relay_source
                (relay_id, relay_function_id, candidate_ref, source_workbook, source_sheet,
                 source_row, device_slot, source_hash, observed_at, raw_gi, raw_bay,
                 raw_circuit, line_link_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (relay_id, function_id, row['candidate_ref'], row['source_workbook'],
                 row['source_sheet'], to_int(row['source_row']), row['device_slot'],
                 row['source_hash'], row['observed_at'], row['gi'], row['bay'], row['circuit'],
                 row['_line_status']))
            candidate_map[row['candidate_ref']] = (relay_id, function_id)

    n_settings = 0
    for row in settings:
        ids = candidate_map.get(row['candidate_ref'])
        if not ids:
            continue
        relay_id, function_id = ids
        conn.execute('''INSERT INTO relay_setting
            (relay_id, relay_function_id, parameter_name, parameter_value, unit, setting_group,
             effective_date, source_doc, is_current, source_workbook, source_sheet, source_row,
             source_column, source_header, source_formula_present, source_formula_hash,
             source_hash, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (relay_id, function_id, row['parameter_name'], row['parameter_value'], row['unit'],
             row['setting_group'], row['effective_date'] or None, row['source_doc'] or None,
             to_int(row['is_current']), row['source_workbook'], row['source_sheet'],
             to_int(row['source_row']), row['source_column'], row['source_header'],
             to_int(row['source_formula_present']), row['source_formula_hash'] or None,
             row['source_hash'], row['observed_at']))
        n_settings += 1

    duplicate_currents = conn.execute('''
        SELECT relay_function_id, parameter_name
        FROM relay_setting WHERE is_current = 1
        GROUP BY relay_function_id, parameter_name HAVING count(*) > 1
    ''').fetchall()
    for function_id, parameter_name in duplicate_currents:
        choices = conn.execute('''
            SELECT setting_id, setting_group, effective_date, source_row, parameter_value,
                   source_sheet, source_column
            FROM relay_setting
            WHERE relay_function_id = ? AND parameter_name = ? AND is_current = 1
        ''', (function_id, parameter_name)).fetchall()
        rank = {'TAP_SET': 1, 'SETTING': 2, 'SET_RELAY': 3}
        winner = max(choices, key=lambda row: (
            rank.get(row['setting_group'], 0), row['effective_date'] or '',
            row['source_row'], row['setting_id']))
        conn.execute('''UPDATE relay_setting SET is_current = 0
                        WHERE relay_function_id = ? AND parameter_name = ? AND setting_id != ?''',
                     (function_id, parameter_name, winner['setting_id']))
        values = {row['parameter_value'] for row in choices}
        if len(values) > 1:
            refs = ' | '.join(f"{row['source_sheet']}!{row['source_row']}:{row['source_column']}"
                              for row in choices)
            add_v2_review(conn, 'CURRENT_SETTING_CONFLICT', refs, '', '',
                          f"{parameter_name}: {sorted(values)}",
                          'Latest deterministic source wins provisionally; verify effective setting.')

    n_event_links = 0
    for row in events:
        event_id = conn.execute('''INSERT INTO official_event
            (ultg, gi, bay, protections, requester, sequence_no, effective_date,
             official_setting, note, status, source_workbook, source_sheet, source_row,
             source_hash, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (row['ultg'], row['gi'], row['bay'], row['protections'], row['requester'],
             row['sequence_no'], row['effective_date'] or None, row['official_setting'],
             row['note'], row['status'], row['source_workbook'], row['source_sheet'],
             to_int(row['source_row']), row['source_hash'], row['observed_at'])).lastrowid
        ss_id, ss_status = resolve_ss(ss_lookup, row['gi'])
        line_ids, link_status = resolve_lines(conn, ss_id, row['bay'], allow_multiple=True)
        if not line_ids:
            add_v2_review(conn, 'OFFICIAL_EVENT_LINK', f"{row['source_sheet']}!{row['source_row']}", '',
                          'OFFICIAL_HISTORY', f"{ss_status}/{link_status}: {row['gi']} / {row['bay']}",
                          'Retain event without line link until exact bay mapping is available.')
        for line_id in line_ids:
            conn.execute('INSERT INTO official_event_line VALUES (?, ?, ?)',
                         (event_id, line_id, link_status))
            n_event_links += 1

    return {
        'relay_candidates': len(candidates),
        'relays': conn.execute('SELECT count(*) FROM relay').fetchone()[0],
        'relay_functions': conn.execute('SELECT count(*) FROM relay_function').fetchone()[0],
        'settings': n_settings, 'official_events': len(events), 'official_event_links': n_event_links,
        'reviews': conn.execute('SELECT count(*) FROM v2_data_review').fetchone()[0],
    }


def main(etl_dir, alias_path, db_path, v2_dir=None):
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')
    db_path = os.path.abspath(db_path)
    tmp_path = db_path + '.tmp'
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    conn = sqlite3.connect(tmp_path)
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
    v2_stats = load_v2(conn, v2_dir) if v2_dir else None

    conn.commit()

    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    fk_violations = conn.execute('PRAGMA foreign_key_check').fetchall()
    if integrity != 'ok' or fk_violations:
        conn.close()
        os.remove(tmp_path)
        raise RuntimeError(
            f'Database gagal validasi: integrity={integrity!r}, '
            f'foreign_key_violations={len(fk_violations)}')

    print('=== PLMS loader v2 ===')
    print(f'Substation dimuat     : {len(key_to_ssid)}')
    print(f'Alias dimuat          : {n_alias}')
    print(f'Line DIgSILENT dimuat : {n_line_ok}  (skip FK hilang: {n_line_skip})')
    print(f'Line manual dimuat    : {n_manual_ok}  (skip FK hilang: {n_manual_skip})')
    print(f'Bus SC dimuat         : {n_bus_ok}  (skip di luar scope: {n_bus_skip})')
    if v2_stats:
        print(f'Rele fisik v2         : {v2_stats["relays"]}')
        print(f'Fungsi rele v2        : {v2_stats["relay_functions"]}')
        print(f'Setting long-form v2  : {v2_stats["settings"]}')
        print(f'Event official v2     : {v2_stats["official_events"]} '
              f'(link ruas: {v2_stats["official_event_links"]})')
        print(f'Review queue v2       : {v2_stats["reviews"]}')
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
    os.replace(tmp_path, db_path)


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5):
        print('Pakai: python3 load.py <dir_etl_output> <alias_review.csv> <db_path> [v2b_out]')
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) == 5 else None)
