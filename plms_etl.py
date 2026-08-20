#!/usr/bin/env python3
"""
PLMS ETL v0 — parser referensi.

Membaca tiga workbook sumber, menghasilkan CSV siap-DB + laporan profiling.
Peta kolom sudah diverifikasi terhadap file asli. Semua asumsi ditandai ASSUMPTION.

Pakai: python3 plms_etl.py <dir_uploads> <dir_output>
"""
import sys, os, re, csv, datetime
from collections import defaultdict, Counter
import openpyxl

DIGSILENT = 'Aplikasi_Crosscheck_Setting_Relay__Digsilent__9_Maret_2021__IHS_1-2021_.xlsx'
UPT_DOC   = 'Data_Setting_Penghantar_UPT_DKSBI.xlsx'
OFFICIAL  = 'List_Official_Setting___Resetting_UPT_Durikosambi.xlsx'

# Akhiran -> tegangan. Diturunkan empiris dari 1.122 baris IHS.
# HANYA 4/5/7. Angka lain adalah bagian dari nama (BEKASI 2, TUBAN3).
VOLTAGE_SUFFIX = {'4': 70.0, '5': 150.0, '7': 500.0}

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

# Nama yang TIDAK boleh tertangkap substring match.
BLOCKLIST = {'KOSAMBI BARU', 'KOSAMBI BARU4', 'KOSAMBI BARU5', 'TELUKJAMBE'}

# Alias yang TIDAK bisa ditemukan lewat canon()/substring karena ejaan
# tidak overlap sama sekali. Dikurasi manual, satu per satu, dengan bukti.
#
# DURIKOSAMBI -> DKSBI7: GITET/GISTET Durikosambi 500kV. Dokumen UPT
# menyebutnya 'GISTET 500KV DURIKOSAMBI' terpisah dari 'GI 150KV
# DURIKOSAMBI'; DIgSILENT menyingkatnya 'DKSBI7' (bukan 'DURIKOSAMBI7'),
# jadi split_voltage()/canon() tidak bisa menangkapnya. Diverifikasi via
# penghantar DKSBI-KMBGN1/2 yang menghubungkan DKSBI7 <-> KEMBANGAN7
# (sama-sama 500kV).
MANUAL_ALIAS = {
    'DURIKOSAMBI': [('DKSBI7', 500.0)],
}

# Node DIgSILENT yang SECARA TOPOLOGI terbukti bukan GI seed meski lolos
# substring/canon match. Dikeluarkan eksplisit, dengan alasan.
#
# SUMMARECON5 -> bukan SUMMARECON GADING SERPONG. Dokumen UPT cuma
# menyebut SATU GI Summarecon ('GIS 150KV SUMMARECON GADING SERPONG',
# area Tangerang). SUMMARECON5 di DIgSILENT terhubung ke penghantar
# 'SUMMARECON - BEKASI 1/2' -- area Bekasi, jauh di luar cluster ULTG
# Angke/Cikupa/Citra Raya/Durikosambi/Tangkot.
#
# SERPONG -> dikonfirmasi pemilik data: jalur berbeda, bukan Summarecon
# Gading Serpong (meski topologinya -- Bintaro/Gandul/Lengkong Baru --
# sempat terlihat masuk akal secara area).
#
# Sisa kandidat 'SUMMARECON' (tanpa suffix) tetap PERIKSA -- terhubung ke
# ALAM SUTRA/CURUG, belum dipastikan.
REJECT_NODES = {
    'SUMMARECON5': 'topologi ke BEKASI, bukan cluster Durikosambi -- bukan Summarecon Gading Serpong',
    'SERPONG': 'dikonfirmasi pemilik data: jalur berbeda, bukan Summarecon Gading Serpong',
}

# Kandidat 'partial' yang sudah dikonfirmasi manual oleh pemilik data
# (bukan ditebak algoritma) -- di-upgrade ke OK meski hanya partial
# match, karena kebenarannya sudah dipastikan lewat verifikasi topologi
# di luar apa yang bisa dicek otomatis di sini.
#
# DAAN MOGOT -> DAAN MOGOT GIS: dikonfirmasi -- GI 150kV di jalur
# Durikosambi -> PIK.
# SUVARNA -> SUVARNA SUTERA: dikonfirmasi -- terhubung ke Alam Sutera.
# SUMMARECON GADING SERPONG -> SUMMARECON: dikonfirmasi -- terhubung ke
# ALAM SUTRA/CURUG. (SERPONG dan SUMMARECON5 tetap ditolak, lihat
# REJECT_NODES -- keduanya jalur/area berbeda.)
CONFIRMED_ALIAS = {
    ('DAAN MOGOT', 'DAAN MOGOT GIS'),
    ('SUVARNA', 'SUVARNA SUTERA'),
    ('SUMMARECON GADING SERPONG', 'SUMMARECON'),
}

anomalies = []
def flag(kind, detail):
    anomalies.append((kind, str(detail)[:160]))


# ---------------------------------------------------------------- utilities

def fix_bay(v):
    """Bay 'I', 'II', 'I-5' sebagian dibaca Excel sebagai datetime. Pulihkan."""
    if isinstance(v, (datetime.datetime, datetime.date)):
        flag('bay_as_date', v)
        return f'?{v.day}-{v.month}'          # ditandai, butuh koreksi manual
    return str(v).strip() if v is not None else None


def split_voltage(name):
    """Pisahkan akhiran tegangan. Kembalikan (nama_bersih, kv_atau_None)."""
    if not name:
        return None, None
    s = re.sub(r'\s+', ' ', str(name).strip().upper())
    m = re.search(r'(\d)\Z', s)
    if m and m.group(1) in VOLTAGE_SUFFIX:
        return s[:-1].strip(), VOLTAGE_SUFFIX[m.group(1)]
    return s, None                             # jangan menebak 150 kV


def canon(name):
    """Bentuk kanonik untuk pencocokan alias."""
    s, _ = split_voltage(name)
    if not s:
        return None
    for a, b in (('M. KARANG', 'MUARAKARANG'), ('M.KARANG', 'MUARAKARANG')):
        s = s.replace(a, b)
    return re.sub(r'\s+', ' ', s).strip()


# Kata kualifier: menandai GI FISIK berbeda (ekspansi/GI baru terpisah),
# bukan variasi ejaan dari GI yang sama. 'TANGERANG' vs 'TANGERANG BARU'
# adalah dua substation berbeda, bukan alias -- meski salah satu string
# ada di dalam yang lain.
QUALIFIER_WORDS = {'BARU', 'LAMA', 'NEW', 'II', 'III', '2', '3'}


def qualifier_set(name):
    """Set kata kualifier yang muncul di nama (setelah tegangan dibuang)."""
    words = set(re.findall(r'\S+', name))
    return words & QUALIFIER_WORDS


def same_qualifiers(a, b):
    """True kalau dua nama punya kata kualifier yang identik -- syarat
    minimum supaya partial match dianggap alias, bukan GI tetangga."""
    return qualifier_set(a) == qualifier_set(b)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------- DIgSILENT: topologi

def read_digsilent(path):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb['DB']
    lines = []
    for r in ws.iter_rows(min_row=4, values_only=True):
        name = r[19]
        ss_i, ss_j = r[23], r[25]
        if not name or not isinstance(ss_i, str) or not isinstance(ss_j, str):
            continue
        length = num(r[32])
        r1, x1, r0, x0 = num(r[45]), num(r[46]), num(r[47]), num(r[48])
        perkm = {}
        if length and length > 0:
            for k, v in (('r1', r1), ('x1', x1), ('r0', r0), ('x0', x0)):
                perkm[k + '_ohm_km'] = round(v / length, 6) if v is not None else None
        else:
            if r1 is not None:
                flag('length_missing_with_impedance', name)
        lines.append(dict(
            line_name=str(name).strip(),
            type_raw=str(r[22]).strip() if r[22] else None,
            ss_from_raw=ss_i.strip(), bay_from=fix_bay(r[24]),
            ss_to_raw=ss_j.strip(),   bay_to=fix_bay(r[26]),
            out_of_service=num(r[31]),
            thermal_rating=r[31], length_km=length,
            conductor_phase=r[36], conductor_earth=r[37],
            earth_resistivity=num(r[40]), irated_ka=num(r[42]),
            z1_ohm=num(r[43]), phiz1_deg=num(r[44]),
            r1_ohm=r1, x1_ohm=x1, r0_ohm=r0, x0_ohm=x0,
            ice_a=num(r[49]), k0=num(r[50]), phik0_deg=num(r[51]),
            **perkm,
        ))

    buses = []
    ws = wb['IHS']
    for r in ws.iter_rows(min_row=6, values_only=True):
        gi, kv = r[6], r[8]
        if not isinstance(gi, str) or kv is None:
            continue
        buses.append(dict(
            bus_name=str(r[5]).strip() if r[5] else None,
            ss_raw=gi.strip(), apb=r[7], voltage_kv=num(kv),
            r1_pu=num(r[9]), x1_pu=num(r[10]),
            r2_pu=num(r[11]), x2_pu=num(r[12]),
            r0_pu=num(r[13]), x0_pu=num(r[14]),
            isc_1ph_ka=num(r[16]), isc_3ph_ka=num(r[17]),
        ))
    wb.close()
    return lines, buses


# ------------------------------------------------------ dokumen UPT: scope

GI_PREFIX = re.compile(r'^TRS-[\d.]+\s*-\s*', re.I)
# Urutan panjang->pendek wajib: 'GISTET' harus dicoba sebelum 'GIS',
# kalau tidak 'GISTET ...' berhenti di 'GIS' + \b gagal (huruf 'T' bukan
# batas kata) dan baris GITET/GISTET (GI 500kV) lolos tak terhitung.
GI_HEAD   = re.compile(r'^(GISTET|GITET|GIS|GI)\b', re.I)
GI_STRIP  = re.compile(r'^(GISTET|GITET|GIS|GI)\s*(150|70|500|20)?\s*KV\s*', re.I)

# Nama bay penghantar: 'PHT 150kV ANCOL#1', 'PHT 150 kV KETAPANG #2'.
# TIDAK menangkap 'PHT.01' (kolom ID) atau 'PHT & KOPEL' (header kategori).
BAY_PHT     = re.compile(r'^PHT\s+\d+\s*k?V\s+(.+)$', re.I)
BAY_SUFFIX  = re.compile(r'\s*#\s*\d+\Z')
BAY_GIS_PFX = re.compile(r'^GIS\s+', re.I)

def bay_to_gi_lawan(bay):
    """Ekstrak kandidat nama GI lawan dari nama bay penghantar.
    'PHT 150kV ANCOL#1' -> 'ANCOL'. None kalau bukan bay penghantar."""
    if not isinstance(bay, str):
        return None
    m = BAY_PHT.match(bay.strip())
    if not m:
        return None
    s = BAY_SUFFIX.sub('', m.group(1)).strip()
    s = BAY_GIS_PFX.sub('', s).strip()          # 'GIS MUARAKARANG BARU' -> 'MUARAKARANG BARU'
    s = re.sub(r'\s+', ' ', s.upper())
    return s or None


def read_upt(path):
    """Scan SELURUH sheet. Membaca satu sheet lalu menyimpulkan = sumber
    kesalahan terbesar dalam analisis awal.

    UPT adalah penentu scope, DIgSILENT pelengkap (lihat prompt v2).
    Selain nama GI dari sel 'GI ...' (found), kumpulkan juga kandidat
    GI lawan dari nama bay ('PHT 150kV <lawan>#N') -- ini sinyal
    keberadaan GI yang tidak tergantung pada DIgSILENT sama sekali.
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    found, per_sheet, lawan = set(), {}, set()
    for ws in wb.worksheets:
        local = set()
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if not isinstance(v, str):
                    continue
                g = bay_to_gi_lawan(v)
                if g:
                    lawan.add(g)
                s = GI_PREFIX.sub('', v.strip())
                if not GI_HEAD.match(s) or len(s) > 50:
                    continue
                s = GI_STRIP.sub('', re.sub(r'\s+', ' ', s.upper())).strip()
                if s.endswith('.PDF') or s.startswith('GI /') or len(s) < 3:
                    continue
                local.add(s)
        per_sheet[ws.title] = len(local)
        found |= local
    wb.close()
    return found, per_sheet, lawan


# --------------------------------------------------------- alias & scoping

def build_alias(seed, dig_names, upt_found=frozenset(), upt_lawan=frozenset()):
    """Kandidat alias untuk KURASI MANUAL. Bukan untuk dipakai langsung.

    UPT adalah penentu scope (lihat prompt v2); DIgSILENT pelengkap.
    Kalau GI seed tidak match ke DIgSILENT, cek dulu apakah UPT sendiri
    punya bukti keberadaannya -- sebagai baris GI asal (upt_found) atau
    sebagai GI lawan yang disebut di nama bay GI lain (upt_lawan) --
    sebelum menandainya tanpa bukti sama sekali.
    """
    by_canon = defaultdict(set)
    for n in dig_names:
        c = canon(n)
        if c:
            by_canon[c].add(n)
    rows, unmatched = [], []
    for gi in sorted(seed):
        exact_hits, partial_hits, rejected = set(), set(), []
        for c, originals in by_canon.items():
            if c in BLOCKLIST:
                continue
            exact = (c == gi)
            # Partial hanya kandidat alias kalau kata kualifier (BARU/LAMA/
            # NEW/II/...) di kedua sisi sama persis. 'TANGERANG' di dalam
            # 'TANGERANG BARU' TIDAK cukup -- itu GI tetangga, bukan alias.
            partial = (not exact and len(gi) > 6 and (gi in c or c in gi)
                       and same_qualifiers(gi, c))
            if exact or partial:
                for o in originals:
                    if o.upper() in BLOCKLIST:
                        continue
                    if o.upper() in REJECT_NODES:
                        rejected.append((o, REJECT_NODES[o.upper()]))
                        continue
                    _, kv = split_voltage(o)
                    # Partial yang sudah dikonfirmasi manual (topologi
                    # diverifikasi pemilik data) naik status ke exact.
                    confirmed = (gi, o.upper()) in CONFIRMED_ALIAS
                    (exact_hits if (exact or confirmed) else partial_hits).add((o, kv))
        # Alias manual dikurasi eksplisit (ejaan tak overlap sama sekali,
        # mis. DKSBI7) -- diverifikasi sudah, langsung diperlakukan exact.
        for o, kv in MANUAL_ALIAS.get(gi, []):
            if o in dig_names:
                exact_hits.add((o, kv))
        # Exact match menekan partial: kalau GI seed sudah punya rumah pasti
        # di DIgSILENT, jangan tawarkan nama GI tetangga sebagai alias juga.
        hits = ([(o, kv, 'exact') for o, kv in exact_hits] if exact_hits
                else [(o, kv, 'partial') for o, kv in partial_hits])
        if hits:
            for o, kv, how in sorted(hits):
                rows.append(dict(gi_upt=gi, alias_digsilent=o, voltage_kv=kv,
                                 match=how,
                                 review='OK' if how == 'exact' else 'PERIKSA'))
            for o, reason in sorted(rejected):
                rows.append(dict(gi_upt=gi, alias_digsilent=o, voltage_kv='',
                                 match='rejected',
                                 review=f'DITOLAK — {reason}'))
        elif rejected:
            # Semua kandidat string-match ditolak topologinya -- GI ini
            # jadi TANPA TOPOLOGI, bukan diam-diam dibiarkan tanpa baris.
            unmatched.append(gi)
            for o, reason in sorted(rejected):
                rows.append(dict(gi_upt=gi, alias_digsilent=o, voltage_kv='',
                                 match='rejected',
                                 review=f'DITOLAK — {reason}'))
        else:
            unmatched.append(gi)
            in_upt_asal  = gi in upt_found
            in_upt_lawan = any(gi in l or l in gi for l in upt_lawan if len(gi) > 6)
            if in_upt_asal:
                note = 'TANPA TOPOLOGI DIGSILENT — ada baris GI asal di UPT'
            elif in_upt_lawan:
                note = 'TANPA TOPOLOGI DIGSILENT — hanya disebut sbg GI lawan di UPT'
            else:
                note = 'TANPA TOPOLOGI DIGSILENT — tidak ditemukan di UPT juga'
            rows.append(dict(gi_upt=gi, alias_digsilent='', voltage_kv='',
                             match='none', review=note))
    return rows, unmatched


def hops(lines, seed_nodes, depth):
    adj = defaultdict(set)
    for l in lines:
        adj[l['ss_from_raw']].add(l['ss_to_raw'])
        adj[l['ss_to_raw']].add(l['ss_from_raw'])
    cur = set(n for n in seed_nodes if n in adj)
    dist = {n: 0 for n in cur}
    for d in range(1, depth + 1):
        nxt = set(cur)
        for x in cur:
            for y in adj[x]:
                if y not in dist:
                    dist[y] = d
                nxt.add(y)
        cur = nxt
    return cur, dist


# ------------------------------------------------------------------- output

def write_csv(path, rows, cols=None):
    if not rows:
        open(path, 'w').close()
        return
    cols = cols or list(rows[0].keys())
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def find_500kv_gaps(upt_gi, seed, seed_nodes):
    """GI seed yang UPT sebut sebagai GITET/GISTET (500kV) tapi seed_nodes
    tidak punya node 500kV untuknya -- baik karena belum di-alias-kan
    maupun karena memang tak ada di DIgSILENT (mis. GISTET Muarakarang).
    Beda dari 'TANPA TOPOLOGI': GI-nya SUDAH exact-match di level lain
    (150kV), cuma level 500kV-nya yang tidak lengkap -- gampang terlewat.

    Sadar MANUAL_ALIAS: node yang ejaannya tak overlap sama sekali (mis.
    DKSBI7 utk DURIKOSAMBI) tidak akan pernah ketemu lewat canon()/
    substring -- tanpa pengecualian ini, gap yang SUDAH diselesaikan lewat
    alias manual akan terus dilaporkan sbg gap (regresi yang pernah
    terjadi di sesi pengembangan awal)."""
    gitet_names = {re.sub(r'^(GITET|GISTET)\s*(500)?\s*KV?\s*', '', g).strip()
                   for g in upt_gi if re.match(r'^(GITET|GISTET)\b', g)}
    have_500 = set()
    for n in seed_nodes:
        clean, kv = split_voltage(n)
        if kv == 500.0 and clean:
            have_500.add(clean)
    manually_covered_500 = {
        gi for gi, aliases in MANUAL_ALIAS.items()
        for alias_name, kv in aliases
        if kv == 500.0 and alias_name in seed_nodes
    }
    gaps = []
    for g in sorted(gitet_names):
        base = canon(g) or g
        if base in manually_covered_500:
            continue
        if not any(base in canon(h) or canon(h) in base for h in have_500 if canon(h)):
            gaps.append(g)
    return gaps


def main(src, out):
    os.makedirs(out, exist_ok=True)
    lines, buses = read_digsilent(os.path.join(src, DIGSILENT))
    upt_gi, per_sheet, upt_lawan = read_upt(os.path.join(src, UPT_DOC))

    dig_names = set()
    for l in lines:
        dig_names.add(l['ss_from_raw'])
        dig_names.add(l['ss_to_raw'])

    alias_rows, unmatched = build_alias(SEED_GI, dig_names, upt_gi, upt_lawan)
    # match='rejected' TETAP punya alias_digsilent terisi (untuk mencatat
    # alasan penolakan di CSV) -- HARUS dikecualikan di sini, kalau tidak
    # node yang sudah ditolak (mis. SUMMARECON5, SERPONG) diam-diam masuk
    # scope lagi lewat jalur ini.
    seed_nodes = {r['alias_digsilent'] for r in alias_rows
                  if r['alias_digsilent'] and r['match'] != 'rejected'}
    gaps_500kv = find_500kv_gaps(upt_gi, SEED_GI, seed_nodes)

    scope1, dist1 = hops(lines, seed_nodes, 1)
    for l in lines:
        a, b = l['ss_from_raw'], l['ss_to_raw']
        l['in_seed'] = a in seed_nodes or b in seed_nodes
        l['in_scope_1hop'] = a in scope1 or b in scope1
        l['is_boundary'] = l['in_seed'] and not (a in seed_nodes and b in seed_nodes)

    # substation dari kedua sumber, tanpa membuang yang tak cocok
    ss = {}
    for n in sorted(dig_names):
        clean, kv = split_voltage(n)
        ss[n] = dict(name_digsilent=n, site_name=clean, voltage_kv=kv,
                     in_seed=n in seed_nodes, hop_distance=dist1.get(n),
                     topology_source='DIGSILENT')
    for gi in unmatched:
        ss['UPT:' + gi] = dict(name_digsilent='', site_name=gi, voltage_kv=None,
                               in_seed=True, hop_distance=0, topology_source='')

    write_csv(os.path.join(out, 'alias_review.csv'), alias_rows)
    write_csv(os.path.join(out, 'substation.csv'), list(ss.values()))
    write_csv(os.path.join(out, 'line.csv'), lines)
    write_csv(os.path.join(out, 'bus_sc.csv'), buses)
    write_csv(os.path.join(out, 'anomalies.csv'),
              [dict(kind=k, detail=d) for k, d in anomalies])

    seed_l = sum(1 for l in lines if l['in_seed'])
    h1_l = sum(1 for l in lines if l['in_scope_1hop'])

    # GI seed yang tak cocok DIgSILENT: pecah berdasarkan bukti di UPT sendiri.
    asal_only = [g for g in unmatched if g in upt_gi]
    lawan_only = [g for g in unmatched if g not in upt_gi
                  and any(g in l or l in g for l in upt_lawan if len(g) > 6)]
    no_evidence = [g for g in unmatched if g not in asal_only and g not in lawan_only]

    rep = [
        '=== PLMS ETL v0 — laporan profiling ===', '',
        f'Penghantar DIgSILENT      : {len(lines)}',
        f'  dengan panjang + R1     : {sum(1 for l in lines if l["length_km"] and l["r1_ohm"] is not None)}',
        f'Bus di IHS                : {len(buses)}',
        f'Substation unik DIgSILENT : {len(dig_names)}', '',
        f'GI ditemukan di dokumen UPT: {len(upt_gi)}',
        f'GI-lawan ditemukan di nama bay UPT: {len(upt_lawan)}',
        f'GI seed dicari             : {len(SEED_GI)}',
        f'  cocok di DIgSILENT       : {len(SEED_GI) - len(unmatched)}',
        f'  TANPA topologi DIgSILENT : {len(unmatched)} -> {", ".join(unmatched)}',
        f'    ada sbg GI asal di UPT  : {len(asal_only)} -> {", ".join(asal_only) or "-"}',
        f'    hanya GI lawan di UPT   : {len(lawan_only)} -> {", ".join(lawan_only) or "-"}',
        f'    tanpa bukti di UPT juga : {len(no_evidence)} -> {", ".join(no_evidence) or "-"}',
        f'  GITET/GISTET (500kV) UPT tanpa node 500kV di seed: {len(gaps_500kv)}'
        f' -> {", ".join(gaps_500kv) or "-"}',
        '',
        f'Node seed                 : {len(seed_nodes)}',
        f'Penghantar seed           : {seed_l}',
        f'  boundary (1 ujung luar) : {sum(1 for l in lines if l["is_boundary"])}',
        f'Node +1 hop               : {len(scope1)}',
        f'Penghantar +1 hop         : {h1_l}  ({100*h1_l/len(lines):.0f}% dari total)', '',
        'GI per sheet dokumen UPT:',
    ]
    for k, v in per_sheet.items():
        rep.append(f'  {k:<14} {v}')
    rep += ['', 'Anomali:']
    for k, v in Counter(k for k, _ in anomalies).most_common():
        rep.append(f'  {k:<32} {v}')
    rep += ['', 'LANGKAH BERIKUTNYA: periksa alias_review.csv secara manual.',
            'Baris ber-review PERIKSA atau TANPA TOPOLOGI wajib dikonfirmasi',
            'sebelum loader dijalankan.']
    text = '\n'.join(rep)
    open(os.path.join(out, 'profiling_report.txt'), 'w', encoding='utf-8').write(text)
    print(text)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.',
         sys.argv[2] if len(sys.argv) > 2 else './out')
