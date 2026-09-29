"""Read-only Jakban SLD crosswalk and per-relay Z2/Z3 topology audit.

No topology or electrical values are promoted to plms.db. Workbook observations
retain their file hash, sheet, row and PoV. A missing observation in a drawing
is not evidence that a PLMS circuit has ceased to exist.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import openpyxl

JAKBAN_FILES = (
    "ss_slcg_ingest.xlsx", "ss_gucl_ingest.xlsx", "ss_lbk_ingest.xlsx",
    "ss_bll_ingest.xlsx", "ss_cwd_ingest.xlsx",
    "ss_muarakarang_durikosambi_ingest.xlsx", "ss_dkgd_ingest.xlsx",
    "ss_prbc_ingest.xlsx", "ss_plbratu_ingest.xlsx",
    "ss_bksi_cbng_ingest.xlsx", "ss_gndul24_ingest.xlsx",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def name_key(value):
    """Retain BARU/LAMA/II and GIS; only remove presentation wording."""
    value = str(value or "").upper().strip()
    # Existing PLMS spelling expansion; retain trailing 2/3 qualifiers.
    value = re.sub(r"\bM\.\s*KARANG\b", "MUARAKARANG", value)
    value = re.sub(r"\((?:BUS|SISI)\s+\d+\s*KV\)", "", value)
    value = re.sub(r"^(?:GI|GITET|GISTET)\s+(?:\d+\s*KV\s+)?", "", value)
    if value.startswith("GIS "):
        value = re.sub(r"^GIS\s+(?:\d+\s*KV\s+)?", "", value) + " GIS"
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", value).split())


def lookup_key(value):
    # TELUKNAGA / TELUK NAGA differ only in spacing. Qualifiers survive.
    return name_key(value).replace(" ", "")


def voltage(value):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:kV)?\s*", str(value or ""), re.I)
    return float(match.group(1)) if match else None


def rows(workbook, sheet):
    if sheet not in workbook:
        return
    iterator = workbook[sheet].iter_rows(values_only=True)
    headers = [str(v or "").strip() for v in next(iterator)]
    for number, values in enumerate(iterator, 2):
        if any(v is not None for v in values):
            yield number, dict(zip(headers, values))


def get(row, *names):
    for name in names:
        if row.get(name) is not None:
            return row[name]
    return None


def source_status(raw):
    value = str(raw or "").strip().upper()
    if value in {"BEROPERASI", "ENERGIZED", "IN_SERVICE"}:
        return "ACTIVE"
    if value in {"BELUM OPERASI", "TIDAK BEROPERASI", "OFF", "NEW_NOT_ENERGIZED", "OUT_OF_SERVICE"}:
        return "INACTIVE"
    return "UNKNOWN"


def read_sources(root):
    root = Path(root)
    samples = root / "samples" if (root / "samples").is_dir() else root
    legacy_path = samples / "sources" / "jakban_legacy_names.json"
    legacy = json.loads(legacy_path.read_text(encoding="utf-8")) if legacy_path.exists() else {}
    sources, nodes, edges, exclusions = [], [], [], []
    for filename in JAKBAN_FILES:
        path = samples / filename
        if not path.is_file():
            raise FileNotFoundError(f"Missing Jakban source: {path}")
        file_hash = digest(path)
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for required in ("Gardu_Induk_dan_Aset", "Jalur_Transmisi"):
                if required not in wb:
                    raise ValueError(f"{filename}: missing sheet {required}")
            info = {str(r[0]).strip(): r[1] for r in wb["Info"].values if len(r) > 1} if "Info" in wb else {}
            subsystem = str(info.get("Kode Subsistem") or filename)
            views = [r for _, r in rows(wb, "Views")]
            default_view = str(get(views[0], "Kode View", "View Key") or "") if len(views) == 1 else ""
            sources.append({"file": filename, "sha256": file_hash, "subsystem": subsystem, "views": views, "info": info})
            local = {}
            for sheet in ("Gardu_Induk_dan_Aset", "Bay"):
                for row_no, row in rows(wb, sheet):
                    code = str(get(row, "Kode Singkatan", "Kode GI", "Kode", "Code") or "").strip()
                    if not code:
                        continue
                    kind = str(get(row, "Tipe Asset", "Tipe", "Type") or "Bay")
                    kv = voltage(get(row, "Tegangan", "Voltage"))
                    ref = {"file": filename, "sha256": file_hash, "sheet": sheet, "row": row_no}
                    if any(word in kind.upper() for word in ("IBT", "WINDING", "PEMBANGKIT", "GENERATOR", "TRAFO")):
                        exclusions.append({**ref, "code": code, "reason": "TRANSFORMER_OR_GENERATOR", "kind": kind})
                        continue
                    key = f"{filename}|{code}|{kv}"
                    label = str(get(row, "Nama Asset / GI", "Nama Asset", "Nama GI", "Name") or code).strip()
                    names = []
                    # Only code-only labels may receive a legacy spelling. Never
                    # override a revised descriptive name with an older label.
                    if name_key(label) == name_key(code):
                        for k, v in legacy.get(subsystem, {}).items():
                            old_code, _, old_kv = k.split("|", 2)
                            if old_code == code and voltage(old_kv) == kv:
                                names.append(v)
                    if key not in local:
                        local[key] = {"key": key, "file": filename, "code": code, "name": label,
                                      "voltage_kv": kv, "kind": kind, "legacy_names": sorted(set(names)),
                                      "evidence": [], "views": []}
                    node = local[key]
                    pov = get(row, "Sudut Pandang", "View", "View Key") or default_view
                    source_pov_note = str(get(row, "Catatan Sudut Pandang Sumber") or "")
                    node["evidence"].append({**ref, "name": label, "views": str(pov or ""), "source_pov_note": source_pov_note})
                    if pov:
                        node["views"].append(str(pov))
                    if sheet == "Bay":
                        feeder = str(get(row, "Feeder (GI Induk)", "Feeder", "GI Induk") or "").strip()
                        if feeder:
                            edges.append({**ref, "from_code": feeder, "to_code": code, "voltage_kv": kv,
                                          "kind": "BOUNDARY_STUB", "name": label, "views": str(pov or ""),
                                          "source_pov_note": source_pov_note,
                                          "circuit_count": get(row, "Jumlah Sirkit", "Sirkit"),
                                          "status": source_status(get(row, "Status Operasi", "Status"))})
            nodes.extend(local.values())
            for row_no, row in rows(wb, "Jalur_Transmisi"):
                fr, to = get(row, "Dari GI", "Dari", "From"), get(row, "Ke GI", "Ke", "To")
                if not fr or not to:
                    continue
                edges.append({"file": filename, "sha256": file_hash, "sheet": "Jalur_Transmisi", "row": row_no,
                              "from_code": str(fr).strip(), "to_code": str(to).strip(),
                              "voltage_kv": voltage(get(row, "Tegangan", "Voltage")), "kind": "LINE",
                              "name": str(get(row, "Nama Penghantar", "Nama", "Name") or ""),
                              "views": str(get(row, "Sudut Pandang", "View", "View Key") or default_view),
                              "source_pov_note": str(get(row, "Catatan Sudut Pandang Sumber") or ""),
                              "circuit_count": get(row, "Jumlah Sirkit", "Sirkit"),
                              "status": source_status(get(row, "Status Operasi", "Status"))})
        finally:
            wb.close()
        if digest(path) != file_hash:
            raise RuntimeError(f"Source changed during audit: {filename}; run again")
    return {"sources": sources, "nodes": nodes, "edges": edges, "excluded_assets": exclusions,
            "legacy_names_sha256": digest(legacy_path) if legacy_path.exists() else None}


def read_plms(conn):
    conn.row_factory = sqlite3.Row
    stations = {r["ss_id"]: dict(r) for r in conn.execute(
        "SELECT s.ss_id,s.voltage_kv,s.name_digsilent,t.site_name FROM substation s JOIN site t USING(site_id)")}
    lines = {r["line_id"]: dict(r) for r in conn.execute(
        """SELECT l.*,e.r1_ohm,e.x1_ohm,e.r0_ohm,e.x0_ohm FROM line l
           LEFT JOIN line_electrical e USING(line_id)""")}
    for s in stations.values():
        known = {l["voltage_kv"] for l in lines.values()
                 if s["ss_id"] in (l["ss_from"], l["ss_to"]) and l["voltage_kv"] is not None}
        s["effective_kv"] = s["voltage_kv"] if s["voltage_kv"] is not None else (next(iter(known)) if len(known) == 1 else None)
        s["voltage_evidence"] = "SUBSTATION" if s["voltage_kv"] is not None else "INCIDENT_LINES" if len(known) == 1 else "UNKNOWN"
        s["names"] = [s["site_name"], s["name_digsilent"]]
    for r in conn.execute("SELECT ss_id,alias_text FROM ss_alias WHERE is_curated=1"):
        stations[r["ss_id"]]["names"].append(r["alias_text"])
    return stations, lines


def map_nodes(nodes, stations):
    index = defaultdict(set)
    for sid, s in stations.items():
        for name in s["names"]:
            if lookup_key(name):
                index[lookup_key(name)].add(sid)
    mappings = {}
    for n in nodes:
        labels = [n["name"], n["code"], *n["legacy_names"], *[e.get("name") for e in n["evidence"]]]
        # Source convention NAME / CODE: the name is usable only when the
        # other side is literally the code in the same record.
        parts = [p.strip() for p in n["name"].split("/")]
        if len(parts) == 2 and n["code"] in parts:
            labels.extend(parts)
        candidates = set().union(*(index[lookup_key(label)] for label in labels))
        compatible = sorted(sid for sid in candidates if n["voltage_kv"] is not None
                            and stations[sid]["effective_kv"] == n["voltage_kv"])
        status = "MATCHED" if len(compatible) == 1 else "AMBIGUOUS" if len(compatible) > 1 else "UNRESOLVED"
        reason = "exact name/code or curated alias, with voltage" if status == "MATCHED" else "identity or voltage needs review"
        # Keep automatic matching conservative. The verified 150 kV crosswalk
        # is supplied explicitly via docs/SLD_DURIKOSAMBI_REVIEW.csv (--review).
        if n["code"] == "DKSBI" and n["voltage_kv"] == 150 and n["file"] in {
            "ss_dkgd_ingest.xlsx", "ss_muarakarang_durikosambi_ingest.xlsx"
        }:
            status, reason = "AMBIGUOUS", "GITET 150 kV bus versus standalone GI Durikosambi: physical site needs review"
        sid = compatible[0] if status == "MATCHED" else None
        mappings[n["key"]] = {**n, "mapping_status": status, "ss_id": sid,
                               "plms_name": stations[sid]["site_name"] if sid else None,
                               "voltage_evidence": stations[sid]["voltage_evidence"] if sid else None,
                               "candidate_ss_ids": sorted(candidates), "reason": reason}
    # All inputs belong to the same Jakban source namespace. A code-only
    # appearance in another PoV may reuse an unambiguous, named appearance.
    # Descriptive revised labels and explicit ambiguous sites are not replaced.
    anchors = defaultdict(list)
    for n in mappings.values():
        if n["mapping_status"] == "MATCHED":
            anchors[(n["code"], n["voltage_kv"])].append(n)
    for n in mappings.values():
        if n["mapping_status"] != "UNRESOLVED" or name_key(n["name"]) != name_key(n["code"]):
            continue
        evidence = anchors[(n["code"], n["voltage_kv"])]
        targets = {a["ss_id"] for a in evidence}
        if len(targets) == 1:
            sid = next(iter(targets))
            n.update(mapping_status="MATCHED_SHARED_CODE", ss_id=sid, plms_name=stations[sid]["site_name"],
                     voltage_evidence=stations[sid]["voltage_evidence"],
                     reason="same Jakban code and voltage as uniquely named source appearance",
                     shared_code_evidence=[a["key"] for a in evidence])
    return mappings


def apply_review(mappings, stations, path):
    """Apply only explicit, source-hash-bound crosswalk edits to the audit."""
    if path is None:
        return
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for r in csv.DictReader(handle):
            target = (r.get("review_plms_name") or "").strip()
            if not target:
                continue
            n = mappings.get(r.get("key"))
            if n is None or r.get("source_sha256") != n["evidence"][0]["sha256"]:
                raise ValueError(f"Review source changed or missing: {r.get('key')}")
            if not (r.get("review_note") or "").strip():
                raise ValueError(f"Review needs evidence/reason: {n['key']}")
            kv = voltage(r.get("review_voltage_kv"))
            found = [sid for sid, s in stations.items() if s["site_name"] == target and s["effective_kv"] == kv]
            if len(found) != 1 or kv != n["voltage_kv"]:
                raise ValueError(f"Review target must be a unique station at source voltage: {n['key']}")
            sid = found[0]
            n.update(mapping_status="REVIEWED_MATCH", ss_id=sid, plms_name=target,
                     voltage_evidence=stations[sid]["voltage_evidence"], reason=r["review_note"])


def suggest_by_neighbors(mappings, edges, stations, lines):
    """Suggest identities from shared mapped neighbours; never auto-promote."""
    plms_neighbors = defaultdict(set)
    for line in lines.values():
        if line["out_of_service"] != 1 and None not in (line["ss_from"], line["ss_to"]):
            plms_neighbors[line["ss_from"]].add(line["ss_to"])
            plms_neighbors[line["ss_to"]].add(line["ss_from"])
    source_neighbors = defaultdict(set)
    for e in edges:
        if e["kind"] != "LINE" or e["status"] != "ACTIVE":
            continue
        a = f"{e['file']}|{e['from_code']}|{e['voltage_kv']}"
        b = f"{e['file']}|{e['to_code']}|{e['voltage_kv']}"
        for here, other in ((a, b), (b, a)):
            if other in mappings and mappings[other]["ss_id"] is not None:
                source_neighbors[here].add(mappings[other]["ss_id"])
    for key, n in mappings.items():
        n["neighbor_suggestions"] = []
        if n["ss_id"] is not None:
            continue
        known = source_neighbors[key]
        for sid, neighbors in plms_neighbors.items():
            shared = known & neighbors
            if shared and stations[sid]["effective_kv"] == n["voltage_kv"]:
                n["neighbor_suggestions"].append({"ss_id": sid, "name": stations[sid]["site_name"],
                    "shared_neighbor_ids": sorted(shared), "known_source_neighbors": len(known)})
        n["neighbor_suggestions"].sort(key=lambda s: (-len(s["shared_neighbor_ids"]), s["ss_id"]))


def has_impedance(line):
    return all(line.get(k) is not None for k in ("r1_ohm", "x1_ohm", "r0_ohm", "x0_ohm"))


def compare_edges(source, mappings, lines):
    node_index = defaultdict(list)
    label_index = defaultdict(set)
    for n in mappings.values():
        node_index[(n["file"], n["code"], n["voltage_kv"])].append(n)
        if n["ss_id"] is not None:
            for label in (n["name"], n["plms_name"], *n["legacy_names"]):
                label_index[(lookup_key(label), n["voltage_kv"])].add(n["ss_id"])
    pairs = defaultdict(list)
    for line in lines.values():
        if line["ss_from"] is not None and line["ss_to"] is not None:
            pairs[(frozenset((line["ss_from"], line["ss_to"])), line["voltage_kv"])].append(line)
    audits = []
    excluded_codes = {(e["file"], e["code"]) for e in source["excluded_assets"]}
    for edge in source["edges"]:
        row = {**edge, "edge_id": f"{edge['file']}|{edge['sheet']}|{edge['row']}", "issues": []}
        for side in ("from", "to"):
            found = node_index[(edge["file"], edge[f"{side}_code"], edge["voltage_kv"])]
            node = found[0] if len(found) == 1 else None
            row[f"{side}_key"] = f"plms:{node['ss_id']}" if node and node["ss_id"] is not None else (
                node["key"] if node else f"{edge['file']}|{edge[f'{side}_code']}|{edge['voltage_kv']}")
            row[f"{side}_ss_id"] = node["ss_id"] if node else None
            row[f"{side}_name"] = node["name"] if node else edge[f"{side}_code"]
        pair = frozenset((row["from_ss_id"], row["to_ss_id"]))
        matched = pairs.get((pair, edge["voltage_kv"]), []) if None not in pair else []
        row["plms_line_ids"] = [l["line_id"] for l in matched]
        row["endpoint_label_candidates"] = {}
        title = re.sub(r"^(?:SUTT|SUTET|SKTT|PHT|INTERKONEKSI)\s+", "", edge["name"], flags=re.I)
        parts = re.split(r"\s+-\s+", title)
        if len(parts) == 2:
            for side, label in zip(("from", "to"), parts):
                label = re.sub(r"\s*\(incomer\)\s*$", "", label, flags=re.I)
                if lookup_key(label) == lookup_key(edge[f"{side}_code"]):
                    continue
                claims = label_index[(lookup_key(label), edge["voltage_kv"])]
                if claims:
                    row["endpoint_label_candidates"][side] = {"label": label, "candidate_ss_ids": sorted(claims)}
                    sid = row[f"{side}_ss_id"]
                    if sid is not None and sid not in claims:
                        row["issues"].append("ENDPOINT_LABEL_CONFLICT")
        excluded = any((edge["file"], edge[f"{side}_code"]) in excluded_codes for side in ("from", "to"))
        if excluded:
            row["relation_status"] = "NON_LINE_ASSET"
        elif edge["kind"] == "BOUNDARY_STUB":
            row["relation_status"] = "BOUNDARY_EVIDENCE"
        elif None in pair:
            row["relation_status"] = "UNRESOLVED_IDENTITY"
        elif len(pair) == 1:
            row["relation_status"] = "SELF_LOOP_CONFLICT"
        elif matched:
            row["relation_status"] = "CORROBORATED_CORRIDOR"
            if edge["status"] == "ACTIVE" and all(l["out_of_service"] == 1 for l in matched):
                row["issues"].append("OPERATING_STATUS_CONFLICT")
            if edge["status"] == "INACTIVE" and any(l["out_of_service"] == 0 for l in matched):
                row["issues"].append("OPERATING_STATUS_CONFLICT")
            # A manual corridor without per-circuit IDs is not comparable
            # to Jumlah Sirkit. Avoid claiming an invented circuit match.
            numbered = [str(l["circuit_no"]) for l in matched if l["circuit_no"] not in (None, "")]
            if len(numbered) != len(matched):
                row["issues"].append("CIRCUIT_IDENTITIES_UNAVAILABLE")
            elif edge["circuit_count"] is not None:
                try:
                    if len(set(numbered)) != int(edge["circuit_count"]):
                        row["issues"].append("CIRCUIT_COUNT_CONFLICT")
                except (ValueError, TypeError):
                    row["issues"].append("CIRCUIT_COUNT_UNPARSEABLE")
        else:
            row["relation_status"] = "CANDIDATE_NEW_CORRIDOR"
        audits.append(row)
    return audits


def relation_graph(lines, audits):
    """Union for inspection only; candidates never become numeric inputs."""
    observations = defaultdict(list)
    graph = defaultdict(list)
    for a in audits:
        for lid in a["plms_line_ids"]:
            observations[lid].append(a)
    for lid, line in lines.items():
        a, b = line["ss_from"], line["ss_to"]
        edge = {"id": f"plms-line:{lid}", "line_id": lid, "name": line["line_name"],
                "a": f"plms:{a}" if a is not None else f"boundary:{lid}:from",
                "b": f"plms:{b}" if b is not None else f"boundary:{lid}:to",
                "status": "INACTIVE" if line["out_of_service"] == 1 else "ACTIVE" if line["out_of_service"] == 0 else "UNKNOWN",
                "impedance_available": has_impedance(line), "voltage_kv": line["voltage_kv"],
                "relation_status": "PLMS_EXISTING", "sld_evidence": [o["edge_id"] for o in observations[lid]],
                "issues": sorted({i for o in observations[lid] for i in o["issues"]})}
        graph[edge["a"]].append(edge)
        graph[edge["b"]].append(edge)
    candidate_corridors = {}
    for a in audits:
        if a["plms_line_ids"] or a["relation_status"] in {"NON_LINE_ASSET", "SELF_LOOP_CONFLICT"}:
            continue
        pair = (tuple(sorted((a["from_key"], a["to_key"]))), a["voltage_kv"], a["kind"])
        if pair in candidate_corridors:
            existing = candidate_corridors[pair]
            existing["sld_evidence"].append(a["edge_id"])
            existing["issues"] = sorted(set(existing["issues"] + a["issues"]))
            if existing["status"] != a["status"]:
                existing["status"] = "UNKNOWN"
                existing["issues"] = sorted(set(existing["issues"] + ["OPERATING_STATUS_CONFLICT"]))
            continue
        edge = {"id": f"sld:{a['edge_id']}", "line_id": None, "name": a["name"],
                "a": a["from_key"], "b": a["to_key"], "status": a["status"],
                "impedance_available": False, "voltage_kv": a["voltage_kv"],
                "relation_status": a["relation_status"], "sld_evidence": [a["edge_id"]], "issues": list(a["issues"])}
        candidate_corridors[pair] = edge
        graph[edge["a"]].append(edge)
        graph[edge["b"]].append(edge)
    return graph


def branch_paths(graph, local, remote, protected_id, kv, max_hops):
    result = []

    def walk(current, visited, path, blockers):
        for e in graph.get(current, []):
            if e["line_id"] == protected_id:
                continue
            other = e["b"] if e["a"] == current else e["a"]
            reasons = list(blockers)
            excluded = None
            if other in visited:
                excluded = "RETURN_TO_VISITED_BUS"
            elif e["status"] == "INACTIVE":
                excluded = "OUT_OF_SERVICE"
            elif e["relation_status"] == "BOUNDARY_EVIDENCE":
                excluded = "BOUNDARY_STUB_NOT_CONFIRMED_LINE"
            elif e["voltage_kv"] != kv:
                excluded = "VOLTAGE_MISMATCH_OR_UNKNOWN"
            if not e["impedance_available"]:
                reasons.append("MISSING_LINE_IMPEDANCE")
            if e["relation_status"] != "PLMS_EXISTING":
                reasons.append(e["relation_status"])
            if e["status"] == "UNKNOWN":
                reasons.append("OPERATING_STATUS_UNKNOWN")
            reasons.extend(e["issues"])
            if other.startswith("boundary:"):
                reasons.append("UNKNOWN_ENDPOINT")
            step = {**e, "from_key": current, "to_key": other}
            new_path = path + [step]
            result.append({"hop": len(new_path), "path": new_path, "excluded_reason": excluded,
                           "blockers": sorted(set(reasons)), "eligible_for_calculation": False})
            if not excluded and len(new_path) < max_hops:
                walk(other, visited | {other}, new_path, reasons)

    walk(remote, {local, remote}, [], [])
    return result


def audit_relays(conn, stations, lines, audits):
    graph = relation_graph(lines, audits)
    result = []
    for relay in conn.execute("""SELECT rf.relay_function_id,r.ss_id,r.line_id,r.bay
        FROM relay_function rf JOIN relay r USING(relay_id)
        WHERE rf.function_type='DIST' ORDER BY rf.relay_function_id"""):
        row = dict(relay)
        line = lines.get(row["line_id"])
        row["local_name"] = stations[row["ss_id"]]["site_name"]
        row["protected_line_name"] = line["line_name"] if line else None
        row["zones"] = {"Z2": [], "Z3": []}
        row["blockers"] = ["MISSING_TRANSFORMER_REACTANCE"]
        if not line or row["ss_id"] not in (line["ss_from"], line["ss_to"]):
            row["blockers"].append("UNRESOLVED_PROTECTED_LINE")
        else:
            other = line["ss_to"] if row["ss_id"] == line["ss_from"] else line["ss_from"]
            row["remote_ss_id"] = other
            row["remote_name"] = stations[other]["site_name"] if other in stations else None
            if not has_impedance(line):
                row["blockers"].append("MISSING_PROTECTED_LINE_IMPEDANCE")
            if other is None:
                row["blockers"].append("UNKNOWN_REMOTE_BUS")
            else:
                paths = branch_paths(graph, f"plms:{row['ss_id']}", f"plms:{other}", line["line_id"], line["voltage_kv"], 2)
                row["zones"]["Z2"] = [p for p in paths if p["hop"] == 1]
                row["zones"]["Z3"] = paths
        result.append(row)
    return result


def write_csv(path, records, columns):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in record.items() if k in columns})


def run(sld_root, db_path, output, review=None):
    source = read_sources(sld_root)
    db_path, output = Path(db_path).resolve(), Path(output).resolve()
    wal = Path(str(db_path) + "-wal")
    before = (digest(db_path), digest(wal) if wal.exists() else None)
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        stations, lines = read_plms(conn)
        mappings = map_nodes(source["nodes"], stations)
        apply_review(mappings, stations, review)
        suggest_by_neighbors(mappings, source["edges"], stations, lines)
        edges = compare_edges(source, mappings, lines)
        relays = audit_relays(conn, stations, lines, edges)
    finally:
        conn.close()
    after = (digest(db_path), digest(wal) if wal.exists() else None)
    if before != after:
        raise RuntimeError("Database changed during audit; run again against a stable snapshot")
    edge_impact, node_impact = defaultdict(set), defaultdict(set)
    for r in relays:
        for p in r["zones"]["Z3"]:
            if p["excluded_reason"]:
                continue
            for step in p["path"]:
                for evidence in step["sld_evidence"]:
                    edge_impact[evidence].add(r["relay_function_id"])
                for key in (step["from_key"], step["to_key"]):
                    node_impact[key].add(r["relay_function_id"])
    for e in edges:
        e["affected_relay_ids"] = sorted(edge_impact[e["edge_id"]])
    for n in mappings.values():
        graph_key = f"plms:{n['ss_id']}" if n["ss_id"] is not None else n["key"]
        n["affected_relay_count"] = len(node_impact[graph_key])
    summary = {"workbooks": len(source["sources"]), "nodes": len(mappings),
               "unique_plms_stations_matched": len({n["ss_id"] for n in mappings.values() if n["ss_id"] is not None}),
               "node_mapping": dict(Counter(n["mapping_status"] for n in mappings.values())),
               "edge_relations": dict(Counter(e["relation_status"] for e in edges)),
               "unique_corroborated_corridors": len({(frozenset((e["from_ss_id"], e["to_ss_id"])), e["voltage_kv"]) for e in edges if e["relation_status"] == "CORROBORATED_CORRIDOR"}),
               "relay_functions": len(relays),
               "relays_with_sld_evidence": sum(any(s["sld_evidence"] for p in r["zones"]["Z3"] if not p["excluded_reason"] for s in p["path"]) for r in relays),
               "relays_with_sld_candidates": sum(any(s["relation_status"] != "PLMS_EXISTING" for p in r["zones"]["Z3"] if not p["excluded_reason"] for s in p["path"]) for r in relays)}
    report = {"format_version": 1, "purpose": "topology audit only; no reach or operational setting",
              "plms_database_sha256": after[0], "plms_wal_sha256": after[1], "summary": summary,
              "sources": source["sources"], "legacy_names_sha256": source["legacy_names_sha256"],
              "review_sha256": digest(review) if review else None,
              "excluded_assets": source["excluded_assets"], "crosswalk": list(mappings.values()),
              "relations": edges, "relay_contexts": relays}
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    crosswalk = [{**n, "source_sha256": n["evidence"][0]["sha256"],
                  "review_plms_name": n["plms_name"] if n["mapping_status"] == "REVIEWED_MATCH" else "",
                  "review_voltage_kv": n["voltage_kv"] if n["mapping_status"] == "REVIEWED_MATCH" else "",
                  "review_note": n["reason"] if n["mapping_status"] == "REVIEWED_MATCH" else ""} for n in mappings.values()]
    write_csv(output / "gi_crosswalk.csv", crosswalk, ["key", "file", "code", "name", "voltage_kv", "mapping_status", "ss_id", "plms_name", "voltage_evidence", "candidate_ss_ids", "shared_code_evidence", "neighbor_suggestions", "affected_relay_count", "reason", "evidence", "source_sha256", "review_plms_name", "review_voltage_kv", "review_note"])
    write_csv(output / "relations.csv", edges, ["file", "sheet", "row", "from_code", "to_code", "voltage_kv", "name", "relation_status", "plms_line_ids", "status", "circuit_count", "views", "source_pov_note", "issues", "endpoint_label_candidates", "affected_relay_ids", "sha256"])
    flat = []
    for r in relays:
        for zone, paths in r["zones"].items():
            for p in paths:
                flat.append({"relay_function_id": r["relay_function_id"], "local_gi": r["local_name"],
                             "protected_line": r["protected_line_name"], "remote_gi": r.get("remote_name"),
                             "zone": zone, "hop": p["hop"], "path": [s["id"] for s in p["path"]],
                             "path_names": [s["name"] for s in p["path"]],
                             "blockers": sorted(set(r["blockers"] + p["blockers"])), "excluded_reason": p["excluded_reason"],
                             "sld_evidence": [x for s in p["path"] for x in s["sld_evidence"]]})
    write_csv(output / "zone_branches.csv", flat, ["relay_function_id", "local_gi", "protected_line", "remote_gi", "zone", "hop", "path", "path_names", "blockers", "excluded_reason", "sld_evidence"])
    write_csv(output / "relay_summary.csv", [{**r,
        "z2_paths": sum(not p["excluded_reason"] for p in r["zones"]["Z2"]),
        "z3_paths": sum(not p["excluded_reason"] for p in r["zones"]["Z3"])} for r in relays],
        ["relay_function_id", "local_name", "bay", "line_id", "protected_line_name", "remote_name", "z2_paths", "z3_paths", "blockers"])
    text = ["# Audit relasi SLD Jakban untuk Z2/Z3", "", f"{summary['workbooks']} workbook; {summary['nodes']} node sumber; {len(relays)} fungsi rele DIST.", "",
            "## Pemetaan GI", "", "Hitungan node adalah kemunculan kode dan tegangan per workbook; satu GI dapat muncul di beberapa workbook.", "",
            *[f"- {k}: {v}" for k, v in summary["node_mapping"].items()], "",
            f"Substation PLMS unik yang terpetakan: **{summary['unique_plms_stations_matched']}**.", "",
            "## Relasi sumber", "", *[f"- {k}: {v}" for k, v in summary["edge_relations"].items()], "",
            f"Rele dengan bukti SLD pada cabang Z2/Z3: **{summary['relays_with_sld_evidence']}**.",
            f"Rele dengan kandidat relasi SLD yang perlu review: **{summary['relays_with_sld_candidates']}**.", "",
            "## Cara membaca", "", "- [Pemetaan GI](gi_crosswalk.csv): pasangan unik nama/kode/alias terkurasi dan tegangan; LAMA/BARU/GIS tetap dibedakan.",
            "- Saran tetangga belum menjadi pasangan GI. Salin CSV pemetaan, isi review_plms_name, review_voltage_kv, review_note, lalu jalankan ulang dengan --review file.csv. Hash sumber dicek agar keputusan lama tidak menimpa revisi workbook baru.",
            "- [Relasi](relations.csv): kesamaan koridor tidak membuktikan identitas setiap sirkit. Ketidakhadiran di satu gambar bukan konflik.",
            "- [Cabang Z2/Z3](zone_branches.csv): semua path dari remote bus; nomor hop dihitung setelah protected line. Cabang tanpa impedansi tetap tercatat.",
            "- [Data lengkap](audit.json): hash workbook, sheet/baris, PoV, identitas yang belum terpetakan, dan konteks semua rele termasuk yang belum punya line.",
            "- [Ringkasan per rele](relay_summary.csv): cakupan path dan blocker seluruh rele DIST.",
            "- Boundary stub, line tidak aktif, tegangan berbeda, dan path balik ke bus yang sudah dilalui ditandai sebagai pengecualian.",
            "- Tidak ada kandidat yang dipromosikan ke graf hitung. XT1, impedansi ruas, identitas sirkit dan bukti operasi masih harus dipenuhi sebelum reach final.",
            "- PoV disimpan sebagai bukti gambar; Tier tidak dipakai sebagai arah rele atau batas graf fisik.", ""]
    text.extend(["## Kandidat koridor baru", "", "Kedua ujung sudah terpetakan; relasi tetap perlu verifikasi terhadap sumber sebelum dipakai menghitung.", "",
                 "| Sumber / baris | Ujung kode | Rele terdampak dalam audit |", "|---|---|---:|"])
    for e in edges:
        if e["relation_status"] == "CANDIDATE_NEW_CORRIDOR":
            text.append(f"| {e['file']} / {e['row']} | {e['from_code']} — {e['to_code']} | {len(e['affected_relay_ids'])} |")
    text.extend(["", "## Identitas prioritas review", "", "Saran tetangga hanya bukti pendukung; tidak mengubah pasangan GI otomatis.", "",
                 "| Sumber / kode | Nama sumber | Rele terdampak |", "|---|---|---:|"])
    unresolved = sorted((n for n in mappings.values() if n["ss_id"] is None and n["affected_relay_count"]), key=lambda n: -n["affected_relay_count"])
    for n in unresolved[:12]:
        text.append(f"| {n['file']} / {n['code']} | {n['name'].replace('|', '/')} | {n['affected_relay_count']} |")
    text.append("")
    (output / "report.md").write_text("\n".join(text), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sld-root", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path(__file__).with_name("plms.db"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("sld_audit"))
    parser.add_argument("--review", type=Path, help="copy of gi_crosswalk.csv with explicit review columns filled")
    args = parser.parse_args()
    result = run(args.sld_root, args.db, args.out, args.review)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {args.out.resolve() / 'report.md'}")
