#!/usr/bin/env python3
"""
Test untuk plms_etl.py -- fokus ke area yang prompt v2 tandai rawan
("Jebakan data") dan bug yang sudah pernah lolos ke production sebelum
ditangkap manual (dicatat di komentar tiap test, bukan cuma diperbaiki).

Pakai: python3 -m pytest test_plms_etl.py -v
"""
import datetime
import pytest

from plms_etl import (
    fix_bay, split_voltage, canon, qualifier_set, same_qualifiers,
    bay_to_gi_lawan, build_alias, find_500kv_gaps, GI_HEAD, GI_STRIP,
    MANUAL_ALIAS, CONFIRMED_ALIAS, REJECT_NODES, BLOCKLIST, SEED_GI,
)


# ------------------------------------------------------- fix_bay (bay-as-date)

class TestFixBay:
    def test_datetime_recovered_and_flagged(self):
        # Prompt v2: bay 'I-5' dkk sebagian terbaca Excel sebagai datetime
        # (contoh 2021-01-05). Harus dipulihkan ke string, bukan dibiarkan
        # jadi objek datetime yang lolos ke CSV mentah-mentah.
        v = datetime.datetime(2021, 1, 5)
        result = fix_bay(v)
        assert isinstance(result, str)
        assert result.startswith('?')  # ditandai, bukan ditebak diam-diam

    def test_date_object_also_recovered(self):
        result = fix_bay(datetime.date(2021, 1, 5))
        assert isinstance(result, str)

    def test_normal_string_passthrough(self):
        assert fix_bay('I-5') == 'I-5'
        assert fix_bay('II') == 'II'

    def test_none_passthrough(self):
        assert fix_bay(None) is None


# ---------------------------------------------------- split_voltage (akhiran)

class TestSplitVoltage:
    @pytest.mark.parametrize('name,expected_clean,expected_kv', [
        ('KEMBANGAN5', 'KEMBANGAN', 150.0),
        ('CURUG4', 'CURUG', 70.0),
        ('DKSBI7', 'DKSBI', 500.0),
    ])
    def test_known_suffix_stripped(self, name, expected_clean, expected_kv):
        clean, kv = split_voltage(name)
        assert clean == expected_clean
        assert kv == expected_kv

    @pytest.mark.parametrize('name', [
        'BEKASI 2',     # digit bagian dari nama, bukan kode tegangan
        'TUBAN3',       # idem -- prompt v2 eksplisit sebut ini sbg jebakan
        'BINTARO2',
        'SEPATAN2',     # angka bukan 4/5/7 -> jangan dipotong
    ])
    def test_non_voltage_suffix_not_stripped(self, name):
        clean, kv = split_voltage(name)
        assert kv is None
        assert clean == name.upper()

    def test_no_suffix_returns_none_kv(self):
        # Mayoritas GI tanpa akhiran -- prompt v2: JANGAN diartikan 150kV
        # default.
        clean, kv = split_voltage('ANGKE')
        assert clean == 'ANGKE'
        assert kv is None

    def test_empty_and_none(self):
        assert split_voltage(None) == (None, None)
        assert split_voltage('') == (None, None)


# ------------------------------------------------------------------- canon

class TestCanon:
    def test_muarakarang_abbreviation_normalized(self):
        assert canon('M. KARANG BARU') == 'MUARAKARANG BARU'
        assert canon('M.KARANG LAMA') == 'MUARAKARANG LAMA'

    def test_voltage_suffix_stripped_before_canon(self):
        assert canon('KEMBANGAN5') == 'KEMBANGAN'


# --------------------------------------------------- qualifier_set / same_qualifiers

class TestQualifiers:
    def test_baru_detected(self):
        assert 'BARU' in qualifier_set('TANGERANG BARU')
        assert qualifier_set('TANGERANG') == set()

    def test_tangerang_vs_tangerang_baru_different_qualifiers(self):
        # Bug asal-mula sesi ini: substring match menganggap TANGERANG BARU
        # sbg alias TANGERANG karena salah satu string ada di dalam yang
        # lain. Keduanya GI FISIK BERBEDA -- qualifier set harus beda.
        assert not same_qualifiers('TANGERANG', 'TANGERANG BARU')

    def test_same_qualifiers_when_both_have_baru(self):
        assert same_qualifiers('CENGKARENG BARU', 'GROGOL BARU')

    def test_no_qualifier_both_sides_matches(self):
        assert same_qualifiers('SUMMARECON', 'SERPONG')


# ------------------------------------------------------- bay_to_gi_lawan

class TestBayToGiLawan:
    @pytest.mark.parametrize('bay,expected', [
        ('PHT 150kV ANCOL#1', 'ANCOL'),
        ('PHT 150kV KETAPANG #2', 'KETAPANG'),
        ('PHT 150kV GIS MUARAKARANG BARU#1', 'MUARAKARANG BARU'),
        ('PHT 500KV LENGKONG #1', 'LENGKONG'),
    ])
    def test_lawan_extracted(self, bay, expected):
        assert bay_to_gi_lawan(bay) == expected

    @pytest.mark.parametrize('bay', [
        'PHT.01',            # kolom ID, bukan nama bay
        'PHT & KOPEL',       # header kategori
        'PHT & KOPEL 12',
        'KOPEL BUS 150kV',   # kopel internal, bukan penghantar antar-GI
        None,
        123,
    ])
    def test_non_bay_returns_none(self, bay):
        assert bay_to_gi_lawan(bay) is None


# ---------------------------------------------------------- GI_HEAD regex

class TestGiHeadRegex:
    # Bug yang lolos sampai loader v1: '^(GI|GIS|GITET)\\b' tidak pernah
    # match 'GISTET ...' karena \b gagal di tengah kata (huruf 'T' bukan
    # batas kata). Akibatnya GISTET DURIKOSAMBI / GISTET MUARAKARANG tidak
    # pernah terhitung sbg GI ditemukan di UPT sampai regex diperbaiki.
    @pytest.mark.parametrize('text', [
        'GISTET 500KV DURIKOSAMBI',
        'GITET 500KV BALARAJA',
        'GIS 150KV ANGKE',
        'GI 150KV ANGKE',
    ])
    def test_all_prefixes_matched(self, text):
        assert GI_HEAD.match(text)

    def test_gistet_stripped_correctly(self):
        import re
        s = GI_STRIP.sub('', 'GISTET 500KV DURIKOSAMBI')
        assert s.strip() == 'DURIKOSAMBI'


# --------------------------------------------------------------- build_alias

DUMMY_UPT_FOUND = frozenset()
DUMMY_UPT_LAWAN = frozenset()


class TestBuildAliasExactAndPartial:
    def test_exact_match(self):
        rows, unmatched = build_alias(['ANGKE'], {'ANGKE', 'CURUG'})
        assert len(rows) == 1
        assert rows[0]['match'] == 'exact'
        assert rows[0]['review'] == 'OK'
        assert 'ANGKE' not in unmatched

    def test_qualifier_mismatch_rejected_as_partial_candidate(self):
        # TANGERANG seed sendiri exact-match ke node TANGERANG -- tidak
        # boleh ada baris partial tambahan ke TANGERANG BARU/II sama sekali
        # (exact menekan partial, dan qualifier beda menolak partial itu
        # sejak awal).
        rows, unmatched = build_alias(
            ['TANGERANG'], {'TANGERANG', 'TANGERANG BARU', 'TANGERANG BARU II'})
        assert len(rows) == 1
        assert rows[0]['alias_digsilent'] == 'TANGERANG'
        assert rows[0]['match'] == 'exact'

    def test_no_exact_falls_back_to_qualifier_matched_partial(self):
        # Tidak ada exact utk 'CENGKARENG BARU' -- tapi kalau seandainya
        # cuma ada varian kualifier beda, harus tetap unmatched, bukan
        # partial yang salah.
        rows, unmatched = build_alias(['PASAR KEMIS BARU'], {'PASAR KEMIS', 'NEW PASAR KEMIS'})
        # PASAR KEMIS punya qualifier {} beda dari PASAR KEMIS BARU {'BARU'}
        # -> tidak boleh jadi partial candidate.
        assert all(r['match'] != 'partial' for r in rows)

    def test_blocklist_excluded(self):
        # KOSAMBI BARU eksplisit di-blocklist -- tidak boleh muncul sbg
        # alias GI manapun meski secara substring/qualifier bisa lolos.
        rows, unmatched = build_alias(
            ['DURIKOSAMBI'], {'DURIKOSAMBI', 'KOSAMBI BARU'})
        aliases = {r['alias_digsilent'] for r in rows}
        assert 'KOSAMBI BARU' not in aliases


class TestBuildAliasManualConfirmedReject:
    def test_manual_alias_upgraded_to_exact(self):
        # DURIKOSAMBI -> DKSBI7 tidak overlap string sama sekali; harus
        # tetap muncul via MANUAL_ALIAS meski canon()/substring gagal total.
        rows, unmatched = build_alias(['DURIKOSAMBI'], {'DURIKOSAMBI', 'DKSBI7'})
        aliases = {(r['alias_digsilent'], r['match']) for r in rows}
        assert ('DKSBI7', 'exact') in aliases
        assert ('DURIKOSAMBI', 'exact') in aliases

    def test_confirmed_alias_upgraded_from_partial_to_exact(self):
        rows, unmatched = build_alias(['SUVARNA'], {'SUVARNA SUTERA'})
        assert len(rows) == 1
        assert rows[0]['match'] == 'exact'
        assert rows[0]['review'] == 'OK'

    def test_reject_node_produces_rejected_row_not_ok(self):
        rows, unmatched = build_alias(
            ['SUMMARECON GADING SERPONG'], {'SERPONG'})
        assert len(rows) == 1
        assert rows[0]['match'] == 'rejected'
        assert 'DITOLAK' in rows[0]['review']
        # GI dianggap tanpa topologi kalau SEMUA kandidat string-match
        # ditolak (bukan diam-diam dianggap tak ada baris sama sekali).
        assert 'SUMMARECON GADING SERPONG' in unmatched

    def test_reject_does_not_suppress_other_valid_candidate(self):
        # SERPONG ditolak, tapi SUMMARECON (kandidat lain, kebetulan juga
        # sudah confirmed di CONFIRMED_ALIAS global) tetap harus muncul
        # dan lolos -- bukan ikut tertekan/hilang gara-gara SERPONG ditolak.
        rows, unmatched = build_alias(
            ['SUMMARECON GADING SERPONG'], {'SERPONG', 'SUMMARECON'})
        by_alias = {r['alias_digsilent']: r for r in rows}
        assert by_alias['SERPONG']['match'] == 'rejected'
        assert by_alias['SUMMARECON']['match'] in ('exact', 'partial')

    def test_partial_without_global_confirmation_stays_partial(self):
        # Kandidat yang TIDAK ada di CONFIRMED_ALIAS harus tetap 'partial'
        # (butuh review manusia), bukan naik status sendiri.
        rows, unmatched = build_alias(['SPINMILL'], {'SPINMILL CONSUMER'})
        row = next(r for r in rows if r['alias_digsilent'] == 'SPINMILL CONSUMER')
        assert row['match'] == 'partial'
        assert row['review'] == 'PERIKSA'

    def test_rejected_alias_digsilent_not_treated_as_seed_node(self):
        # Regresi utk bug nyata: main() dulu membangun seed_nodes dari
        # SEMUA baris ber-alias_digsilent, termasuk match='rejected'.
        # Kontrak yang benar: caller (main()) HARUS memfilter match !=
        # 'rejected' sebelum membangun seed_nodes -- test ini mengunci
        # bahwa baris rejected tetap eksplisit ditandai match='rejected'
        # sehingga filter itu mungkin dilakukan.
        rows, _ = build_alias(['SUMMARECON GADING SERPONG'], {'SERPONG'})
        seed_nodes = {r['alias_digsilent'] for r in rows
                      if r['alias_digsilent'] and r['match'] != 'rejected'}
        assert 'SERPONG' not in seed_nodes


class TestBuildAliasUptEvidence:
    def test_unmatched_with_upt_asal_evidence(self):
        rows, unmatched = build_alias(
            ['LONTAR'], {'ANGKE'}, upt_found={'LONTAR'})
        row = next(r for r in rows if r['gi_upt'] == 'LONTAR')
        assert 'ada baris GI asal di UPT' in row['review']

    def test_unmatched_with_lawan_only_evidence(self):
        rows, unmatched = build_alias(
            ['SEPATAN BARU'], {'ANGKE'}, upt_found=frozenset(),
            upt_lawan={'SEPATAN BARU'})
        row = next(r for r in rows if r['gi_upt'] == 'SEPATAN BARU')
        assert 'hanya disebut sbg GI lawan' in row['review']

    def test_unmatched_with_no_evidence(self):
        rows, unmatched = build_alias(
            ['GHOST GI'], {'ANGKE'}, upt_found=frozenset(), upt_lawan=frozenset())
        row = next(r for r in rows if r['gi_upt'] == 'GHOST GI')
        assert 'tidak ditemukan di UPT juga' in row['review']


# ----------------------------------------------------------- find_500kv_gaps

class TestFind500kvGaps:
    def test_gap_detected_when_no_500kv_node(self):
        # GISTET MUARAKARANG disebut UPT tapi seed_nodes cuma punya node
        # 150kV Muarakarang -- harus terdeteksi sbg gap.
        upt_gi = {'GISTET MUARAKARANG', 'GI 150KV MUARAKARANG BARU'}
        seed_nodes = {'M. KARANG BARU'}  # tanpa suffix 7/500kV
        gaps = find_500kv_gaps(upt_gi, SEED_GI, seed_nodes)
        assert any('MUARAKARANG' in g for g in gaps)

    def test_no_gap_when_500kv_node_present(self):
        upt_gi = {'GISTET 500KV DURIKOSAMBI'}
        seed_nodes = {'DKSBI7'}  # split_voltage() -> ('DKSBI', 500.0)
        gaps = find_500kv_gaps(upt_gi, SEED_GI, seed_nodes)
        assert not any('DURIKOSAMBI' in g or 'DKSBI' in g for g in gaps)


# ------------------------------------------------- regression: known-good seed decisions

class TestKnownGoodDecisions:
    """Kunci keputusan kurasi yang sudah disetujui pemilik data supaya
    perubahan matching di masa depan tidak diam-diam membalikkannya."""

    def test_manual_alias_constants_unchanged_keys(self):
        assert MANUAL_ALIAS['DURIKOSAMBI'] == [('DKSBI7', 500.0)]

    def test_confirmed_alias_contains_expected_pairs(self):
        assert ('DAAN MOGOT', 'DAAN MOGOT GIS') in CONFIRMED_ALIAS
        assert ('SUVARNA', 'SUVARNA SUTERA') in CONFIRMED_ALIAS
        assert ('SUMMARECON GADING SERPONG', 'SUMMARECON') in CONFIRMED_ALIAS

    def test_reject_nodes_contains_expected_entries(self):
        assert 'SUMMARECON5' in REJECT_NODES
        assert 'SERPONG' in REJECT_NODES

    def test_blocklist_contains_false_positive_guards(self):
        # Prompt v2: KOSAMBI BARU bukan UPT Durikosambi (area Indramayu/
        # Dawuan); TELUKJAMBE bukan TELUK NAGA.
        assert 'KOSAMBI BARU' in BLOCKLIST
        assert 'TELUKJAMBE' in BLOCKLIST


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
