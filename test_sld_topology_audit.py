"""Crosswalk and traversal boundaries: an SLD observation is not a setting."""
import csv
import json
import sqlite3

import pytest

import sld_topology_audit as audit
from test_calculation_loader import conn, _insert_site_ss, _insert_line, _insert_dist_relay


def node(code, name=None, kv=150.0, file="test.xlsx"):
    return {"key": f"{file}|{code}|{kv}", "file": file, "code": code,
            "name": name or code, "voltage_kv": kv, "kind": "Busbar GI",
            "legacy_names": [], "views": [],
            "evidence": [{"sha256": "source-hash", "sheet": "Gardu_Induk_dan_Aset", "row": 2}]}


def edge(a, b, row=2, status="ACTIVE", kind="LINE", views="K"):
    return {"file": "test.xlsx", "sha256": "source-hash", "sheet": "Jalur_Transmisi", "row": row,
            "from_code": a, "to_code": b, "voltage_kv": 150.0, "name": f"{a}-{b}",
            "status": status, "kind": kind, "circuit_count": 2, "views": views}


def source(nodes, edges):
    return {"nodes": nodes, "edges": edges, "sources": [{"file": "test.xlsx", "sha256": "source-hash"}],
            "excluded_assets": [], "legacy_names_sha256": None}


def test_names_keep_distinct_sites_and_voltage(conn):
    old = _insert_site_ss(conn, "PASAR KEMIS")
    new = _insert_site_ss(conn, "PASAR KEMIS BARU")
    gis = _insert_site_ss(conn, "MUARAKARANG BARU GIS")
    conventional = _insert_site_ss(conn, "M. KARANG BARU")
    high = _insert_site_ss(conn, "PASAR KEMIS", 500)
    stations, _ = audit.read_plms(conn)
    nodes = [node("PSKMS", "GI Pasar Kemis"), node("PSKBR", "GI Pasar Kemis Baru"),
             node("GMKRU", "GIS Muarakarang Baru"), node("MKBRU", "Muarakarang Baru"),
             node("PSKMS", "GITET Pasar Kemis", 500.0)]
    result = audit.map_nodes(nodes, stations)
    assert [n["ss_id"] for n in result.values()] == [old, new, gis, conventional, high]
    assert audit.lookup_key("GI X Lama") != audit.lookup_key("GI X Baru")
    assert audit.lookup_key("GI X II") != audit.lookup_key("GI X")


def test_unknown_voltage_and_duplicate_names_remain_unresolved(conn):
    _insert_site_ss(conn, "X")
    _insert_site_ss(conn, "X")
    stations, _ = audit.read_plms(conn)
    result = list(audit.map_nodes([node("X"), node("Y", "X", None)], stations).values())
    assert result[0]["mapping_status"] == "AMBIGUOUS"
    assert result[1]["ss_id"] is None


def test_code_only_pov_can_reuse_unique_jakban_identity_but_not_other_voltage(conn):
    sid = _insert_site_ss(conn, "M. KARANG LAMA")
    stations, _ = audit.read_plms(conn)
    nodes = [node("MKLMA", "Muarakarang Lama", file="named.xlsx"),
             node("MKLMA", file="other-pov.xlsx"), node("MKLMA", kv=500.0, file="other-pov.xlsx")]
    result = audit.map_nodes(nodes, stations)
    assert result[nodes[1]["key"]]["mapping_status"] == "MATCHED_SHARED_CODE"
    assert result[nodes[1]["key"]]["ss_id"] == sid
    assert result[nodes[1]["key"]]["shared_code_evidence"] == [nodes[0]["key"]]
    assert result[nodes[2]["key"]]["ss_id"] is None


def test_parser_keeps_source_rows_voltage_and_original_pov_note(tmp_path, monkeypatch):
    class Sheet:
        def __init__(self, values): self.values = values
        def iter_rows(self, values_only=True): return iter(self.values)

    class Workbook(dict):
        def close(self): pass

    wb = Workbook({
        "Info": Sheet([("Kode Subsistem", "SS_LBK")]),
        "Views": Sheet([("Kode View", "Nama View"), ("FULL", "SLD lengkap")]),
        "Gardu_Induk_dan_Aset": Sheet([
            ("Kode Singkatan", "Nama Asset / GI", "Tipe Asset", "Tegangan"),
            ("A", "GI A", "Busbar GI", "150 kV"), ("A", "GITET A", "Busbar GITET", "500 kV"),
            ("B", "GI B", "Busbar GI", "150 kV"), ("KIT", "KIT A", "Pembangkit", "150 kV")]),
        "Jalur_Transmisi": Sheet([
            ("Dari GI", "Ke GI", "Tegangan", "Nama Penghantar", "Status Operasi", "Catatan Sudut Pandang Sumber"),
            ("A", "B", "150 kV", "SUTT A - B", "Beroperasi", "sisi lama Kembangan")])})
    (tmp_path / "test.xlsx").write_bytes(b"source sentinel")
    monkeypatch.setattr(audit, "JAKBAN_FILES", ("test.xlsx",))
    monkeypatch.setattr(audit.openpyxl, "load_workbook", lambda *a, **k: wb)
    result = audit.read_sources(tmp_path)
    assert len(result["nodes"]) == 3
    assert {n["voltage_kv"] for n in result["nodes"] if n["code"] == "A"} == {150, 500}
    e = result["edges"][0]
    assert e["row"] == 2 and e["views"] == "FULL"
    assert e["source_pov_note"] == "sisi lama Kembangan"
    assert result["excluded_assets"][0]["code"] == "KIT"


def test_voltage_inferred_only_from_unanimous_incident_lines(conn):
    a, b = _insert_site_ss(conn, "A", None), _insert_site_ss(conn, "B")
    _insert_line(conn, "A-B", a, b)
    stations, _ = audit.read_plms(conn)
    assert stations[a]["effective_kv"] == 150
    assert stations[a]["voltage_evidence"] == "INCIDENT_LINES"
    conn.execute("INSERT INTO line(ss_from,ss_to,voltage_kv,source) VALUES (?,?,500,'TEST')", (a, b))
    stations, _ = audit.read_plms(conn)
    assert stations[a]["effective_kv"] is None


def test_durikosambi_gitet_bus_does_not_merge_into_standalone_gi(conn):
    _insert_site_ss(conn, "DURIKOSAMBI")
    stations, _ = audit.read_plms(conn)
    n = node("DKSBI", "Durikosambi (bus 150 kV)", file="ss_dkgd_ingest.xlsx")
    result = audit.map_nodes([n], stations)[n["key"]]
    assert result["mapping_status"] == "AMBIGUOUS"
    assert result["ss_id"] is None


def test_review_rejects_stale_source_and_wrong_voltage(conn, tmp_path):
    _insert_site_ss(conn, "ULUJAMI")
    stations, _ = audit.read_plms(conn)
    n = node("UUMI")
    mappings = audit.map_nodes([n], stations)
    path = tmp_path / "review.csv"
    review = {"key": n["key"], "source_sha256": "stale", "review_plms_name": "ULUJAMI",
              "review_voltage_kv": "150", "review_note": "review evidence"}

    def write():
        audit.write_csv(path, [review], list(review))

    write()
    with pytest.raises(ValueError, match="source changed"):
        audit.apply_review(mappings, stations, path)
    review.update(source_sha256="source-hash", review_voltage_kv="500")
    write()
    with pytest.raises(ValueError, match="unique station"):
        audit.apply_review(mappings, stations, path)
    review["review_voltage_kv"] = "150"
    write()
    audit.apply_review(mappings, stations, path)
    assert mappings[n["key"]]["mapping_status"] == "REVIEWED_MATCH"


def test_corridor_match_is_undirected_and_retains_parallel_line_ids(conn):
    a, b = _insert_site_ss(conn, "A"), _insert_site_ss(conn, "B")
    first = _insert_line(conn, "A-B 1", a, b)
    second = _insert_line(conn, "B-A 2", b, a)
    s = source([node("A"), node("B")], [edge("B", "A")])
    stations, lines = audit.read_plms(conn)
    result = audit.compare_edges(s, audit.map_nodes(s["nodes"], stations), lines)
    assert result[0]["relation_status"] == "CORROBORATED_CORRIDOR"
    assert result[0]["plms_line_ids"] == [first, second]
    assert "CIRCUIT_IDENTITIES_UNAVAILABLE" in result[0]["issues"]


def test_multiple_povs_do_not_duplicate_candidate_corridor(conn):
    _insert_site_ss(conn, "A")
    _insert_site_ss(conn, "B")
    s = source([node("A"), node("B")], [edge("A", "B"), edge("B", "A", row=3, views="B")])
    stations, lines = audit.read_plms(conn)
    result = audit.compare_edges(s, audit.map_nodes(s["nodes"], stations), lines)
    graph = audit.relation_graph(lines, result)
    edges = graph[f"plms:{next(iter(stations))}"]
    assert len(edges) == 1
    assert len(edges[0]["sld_evidence"]) == 2
    assert edges[0]["line_id"] is None


def test_line_title_disagreement_with_endpoint_code_is_visible(conn):
    a, b, c = [_insert_site_ss(conn, n) for n in ("MUARAKARANG LAMA", "ANGKE", "ANCOL")]
    _insert_line(conn, "Muarakarang-Angke", a, b)
    e = edge("MKLMA", "ANGKE")
    e["name"] = "SUTT Muarakarang Lama - Ancol"
    s = source([node("MKLMA", "Muarakarang Lama"), node("ANGKE"), node("ANCOL")], [e])
    stations, lines = audit.read_plms(conn)
    result = audit.compare_edges(s, audit.map_nodes(s["nodes"], stations), lines)[0]
    assert "ENDPOINT_LABEL_CONFLICT" in result["issues"]
    assert result["endpoint_label_candidates"]["to"]["candidate_ss_ids"] == [c]


def test_two_hops_survive_missing_impedance_but_loops_and_stubs_do_not_expand(conn):
    a, b, c, d = [_insert_site_ss(conn, n) for n in "ABCD"]
    protected = _insert_line(conn, "A-B", a, b)
    first = _insert_line(conn, "B-C", b, c)
    second = _insert_line(conn, "C-D", c, d)
    conn.execute("DELETE FROM line_electrical WHERE line_id=?", (first,))
    loop = _insert_line(conn, "B-A 2", b, a)
    inactive = _insert_line(conn, "B-D off", b, d)
    conn.execute("UPDATE line SET out_of_service=1 WHERE line_id=?", (inactive,))
    stations, lines = audit.read_plms(conn)
    s = source([node("B"), node("EXTERNAL")], [edge("B", "EXTERNAL", kind="BOUNDARY_STUB")])
    graph = audit.relation_graph(lines, audit.compare_edges(s, audit.map_nodes(s["nodes"], stations), lines))
    paths = audit.branch_paths(graph, f"plms:{a}", f"plms:{b}", protected, 150, 2)
    target = next(p for p in paths if [e["line_id"] for e in p["path"]] == [first, second])
    assert "MISSING_LINE_IMPEDANCE" in target["blockers"]
    assert not target["eligible_for_calculation"]
    assert next(p for p in paths if p["path"][-1]["line_id"] == loop)["excluded_reason"] == "RETURN_TO_VISITED_BUS"
    assert next(p for p in paths if p["path"][-1]["line_id"] == inactive)["excluded_reason"] == "OUT_OF_SERVICE"
    stub = next(p for p in paths if p["path"][-1]["relation_status"] == "BOUNDARY_EVIDENCE")
    assert stub["excluded_reason"] == "BOUNDARY_STUB_NOT_CONFIRMED_LINE"


def test_neighbor_suggestion_does_not_change_identity(conn):
    a, b = _insert_site_ss(conn, "NEW SENAYAN"), _insert_site_ss(conn, "ULUJAMI")
    _insert_line(conn, "New Senayan-Ulujami", a, b)
    s = source([node("NSYAN", "New Senayan"), node("UUMI")], [edge("NSYAN", "UUMI")])
    stations, lines = audit.read_plms(conn)
    mappings = audit.map_nodes(s["nodes"], stations)
    audit.suggest_by_neighbors(mappings, s["edges"], stations, lines)
    candidate = mappings[s["nodes"][1]["key"]]
    assert candidate["ss_id"] is None
    assert candidate["neighbor_suggestions"][0]["ss_id"] == b


def test_end_to_end_audit_does_not_write_db_and_all_relays_have_context(conn, tmp_path, monkeypatch):
    a, b, c = [_insert_site_ss(conn, n) for n in "ABC"]
    protected = _insert_line(conn, "A-B", a, b)
    rf = _insert_dist_relay(conn, a, protected)
    orphan = _insert_dist_relay(conn, a, None)
    s = source([node(n) for n in "ABC"], [edge("B", "C")])
    monkeypatch.setattr(audit, "read_sources", lambda _: s)
    db_path = tmp_path / "plms.db"
    conn.commit()
    with sqlite3.connect(db_path) as copy:
        conn.backup(copy)
    before = audit.digest(db_path)
    report = audit.run(tmp_path, db_path, tmp_path / "out")
    assert audit.digest(db_path) == before
    by_rf = {r["relay_function_id"]: r for r in report["relay_contexts"]}
    assert by_rf[rf]["zones"]["Z2"][0]["path"][0]["relation_status"] == "CANDIDATE_NEW_CORRIDOR"
    assert "UNRESOLVED_PROTECTED_LINE" in by_rf[orphan]["blockers"]
    assert json.loads((tmp_path / "out" / "audit.json").read_text(encoding="utf-8"))["summary"]["relay_functions"] == 2
    with (tmp_path / "out" / "gi_crosswalk.csv").open(encoding="utf-8-sig") as handle:
        assert "review_plms_name" in next(csv.reader(handle))
