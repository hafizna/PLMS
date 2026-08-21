-- PLMS v1 — skema inti (SQLite).
-- Sumber definisi: PLMS_Rebuild_Prompt_v2.md, bagian "Model data".
-- v1 mengisi: site, substation, ss_alias, line, line_electrical, bus_sc,
-- scope_definition. Tabel relay/protection_chain/relay_setting didefinisikan
-- di sini (FK saling terkait) tapi baru diisi loader mulai v2.

PRAGMA foreign_keys = ON;

-- Lokasi fisik. Satu GI bisa punya beberapa level tegangan.
CREATE TABLE site (
    site_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name   TEXT NOT NULL,
    site_code   TEXT,
    latitude    REAL,
    longitude   REAL,
    is_gis      INTEGER          -- 0/1 boolean
);

-- Site x level tegangan. INI yang jadi node graph, bukan site.
CREATE TABLE substation (
    ss_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id          INTEGER NOT NULL REFERENCES site(site_id),
    voltage_kv       REAL,
    name_digsilent   TEXT,
    ultg             TEXT,
    upt              TEXT,
    unit_induk       TEXT,
    valid_from       TEXT,        -- ISO date; struktur organisasi berubah, topologi tidak
    valid_to         TEXT,
    in_scope         INTEGER NOT NULL DEFAULT 0,
    hop_distance     INTEGER,     -- NULL = di luar +1 hop / tidak terhubung graph
    topology_source  TEXT         -- 'DIGSILENT' | NULL (lihat legacy-knowledge/TOPOLOGI_GI_TANPA_DIGSILENT.md)
);

CREATE INDEX idx_substation_site ON substation(site_id);

CREATE TABLE ss_alias (
    alias_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ss_id         INTEGER NOT NULL REFERENCES substation(ss_id),
    alias_text    TEXT NOT NULL,
    source_system TEXT,           -- 'DIGSILENT' | 'UPT_DKSBI' | ...
    is_curated    INTEGER NOT NULL DEFAULT 0  -- 1 = dikurasi manual (lihat alias_review.csv)
);

CREATE INDEX idx_ss_alias_ss ON ss_alias(ss_id);
CREATE INDEX idx_ss_alias_text ON ss_alias(alias_text);

CREATE TABLE line (
    line_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    line_name          TEXT,
    line_name_digsilent TEXT,
    ss_from            INTEGER REFERENCES substation(ss_id),  -- NULL bila ujung tanpa topology_source
    bay_from           TEXT,
    ss_to              INTEGER REFERENCES substation(ss_id),
    bay_to             TEXT,
    circuit_no         TEXT,
    technology         TEXT,
    voltage_kv         REAL,
    conductor_type     TEXT,
    conductor_earth    TEXT,
    rating_a           REAL,
    out_of_service     INTEGER,
    is_boundary        INTEGER NOT NULL DEFAULT 0,
    source             TEXT NOT NULL  -- 'DIGSILENT' | 'UPT_MANUAL' (lihat TOPOLOGI_GI_TANPA_DIGSILENT.md)
);

CREATE INDEX idx_line_from ON line(ss_from);
CREATE INDEX idx_line_to ON line(ss_to);

-- Dipisah dari line: parameter berubah saat rekonduktoring,
-- sementara identitas penghantar tetap.
CREATE TABLE line_electrical (
    line_id           INTEGER PRIMARY KEY REFERENCES line(line_id),
    length_km         REAL,
    z1_ohm            REAL,
    phiz1_deg         REAL,
    r1_ohm            REAL,
    x1_ohm            REAL,
    r0_ohm            REAL,
    x0_ohm            REAL,
    r1_ohm_km         REAL,
    x1_ohm_km         REAL,
    r0_ohm_km         REAL,
    x0_ohm_km         REAL,
    k0                REAL,
    phik0_deg         REAL,
    irated_ka         REAL,
    ice_a             REAL,
    earth_resistivity REAL,
    model_version     TEXT,
    model_date        TEXT,
    source            TEXT
);

CREATE TABLE bus_sc (
    bus_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ss_id         INTEGER NOT NULL REFERENCES substation(ss_id),
    bus_name      TEXT,
    voltage_kv    REAL,
    r1_pu         REAL,
    x1_pu         REAL,
    r2_pu         REAL,
    x2_pu         REAL,
    r0_pu         REAL,
    x0_pu         REAL,
    r1_ohm        REAL,
    x1_ohm        REAL,
    z_base        REAL,
    isc_1ph_ka    REAL,
    isc_3ph_ka    REAL,
    model_version TEXT,
    source        TEXT
);

CREATE INDEX idx_bus_sc_ss ON bus_sc(ss_id);

-- v2: IED fisik. Fungsi dipisahkan karena satu IED dapat muncul pada lebih
-- dari satu sheet/fungsi (mis. LCD + DIST + AR).
CREATE TABLE relay (
    relay_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ss_id              INTEGER NOT NULL REFERENCES substation(ss_id),
    bay                TEXT,
    line_id            INTEGER REFERENCES line(line_id),
    manufacturer       TEXT,
    model              TEXT,
    serial_no          TEXT,
    ct_ratio           TEXT,
    pt_ratio           TEXT,
    status             TEXT,
    pst_asset_id       TEXT,
    identity_key       TEXT NOT NULL UNIQUE,
    identity_confidence TEXT NOT NULL,
    identity_status    TEXT NOT NULL
);

CREATE INDEX idx_relay_ss ON relay(ss_id);
CREATE INDEX idx_relay_line ON relay(line_id);

CREATE TABLE relay_function (
    relay_function_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    relay_id           INTEGER NOT NULL REFERENCES relay(relay_id),
    function_type      TEXT NOT NULL,
    coordination_class TEXT NOT NULL,
    source_logical     TEXT NOT NULL,
    status             TEXT,
    UNIQUE (relay_id, function_type, source_logical)
);

CREATE INDEX idx_relay_function_relay ON relay_function(relay_id);

CREATE TABLE relay_source (
    relay_source_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    relay_id           INTEGER NOT NULL REFERENCES relay(relay_id),
    relay_function_id  INTEGER NOT NULL REFERENCES relay_function(relay_function_id),
    candidate_ref      TEXT NOT NULL UNIQUE,
    source_workbook    TEXT NOT NULL,
    source_sheet       TEXT NOT NULL,
    source_row         INTEGER NOT NULL,
    device_slot        TEXT NOT NULL,
    source_hash        TEXT NOT NULL,
    observed_at        TEXT NOT NULL,
    raw_gi             TEXT,
    raw_bay            TEXT,
    raw_circuit        TEXT,
    line_link_status   TEXT NOT NULL
);

-- v3+: rantai grading vertikal. TERPISAH dari `line` karena arahnya
-- menembus level tegangan di dalam satu GI, bukan antar-GI.
CREATE TABLE protection_chain (
    chain_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_type        TEXT,      -- OCR_GRADING | GFR_GRADING
    relay_function_id INTEGER NOT NULL REFERENCES relay_function(relay_function_id),
    upstream_relay_function_id INTEGER REFERENCES relay_function(relay_function_id),
    level_order       INTEGER,
    voltage_kv        REAL,
    chain_status      TEXT       -- complete | incomplete_external
);

-- v2+: setting rele, key-value panjang (parameter terlalu beragam untuk skema lebar).
CREATE TABLE relay_setting (
    setting_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    relay_id         INTEGER NOT NULL REFERENCES relay(relay_id),
    relay_function_id INTEGER NOT NULL REFERENCES relay_function(relay_function_id),
    parameter_name   TEXT,
    parameter_value  TEXT,
    unit             TEXT,
    setting_group    TEXT,
    effective_date   TEXT,
    source_doc       TEXT,
    is_current       INTEGER,
    topology_version TEXT,
    source_event_id  INTEGER REFERENCES official_event(official_event_id),
    source_workbook  TEXT NOT NULL,
    source_sheet     TEXT NOT NULL,
    source_row       INTEGER NOT NULL,
    source_column    TEXT NOT NULL,
    source_header    TEXT NOT NULL,
    source_formula_present INTEGER NOT NULL DEFAULT 0,
    source_formula_hash TEXT,
    source_hash      TEXT NOT NULL,
    observed_at      TEXT NOT NULL,
    UNIQUE (relay_function_id, setting_group, parameter_name,
            source_workbook, source_sheet, source_row, source_column)
);

CREATE INDEX idx_relay_setting_relay ON relay_setting(relay_id);
CREATE INDEX idx_relay_setting_function ON relay_setting(relay_function_id);

CREATE TABLE official_event (
    official_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ultg              TEXT,
    gi                TEXT,
    bay               TEXT,
    protections       TEXT,
    requester         TEXT,
    sequence_no       TEXT,
    effective_date    TEXT,
    official_setting  TEXT,
    note              TEXT,
    status            TEXT,
    source_workbook   TEXT NOT NULL,
    source_sheet      TEXT NOT NULL,
    source_row        INTEGER NOT NULL,
    source_hash       TEXT NOT NULL,
    observed_at       TEXT NOT NULL,
    UNIQUE (source_workbook, source_sheet, source_row)
);

CREATE TABLE official_event_line (
    official_event_id INTEGER NOT NULL REFERENCES official_event(official_event_id),
    line_id           INTEGER NOT NULL REFERENCES line(line_id),
    link_status       TEXT NOT NULL,
    PRIMARY KEY (official_event_id, line_id)
);

CREATE TABLE v2_data_review (
    review_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    review_type        TEXT NOT NULL,
    source_ref         TEXT,
    identity_key       TEXT,
    logical_source     TEXT,
    detail             TEXT,
    recommended_action TEXT
);

CREATE TABLE scope_definition (
    scope_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_name        TEXT NOT NULL,
    seed_substations  TEXT,      -- JSON array nama GI seed
    hop_depth         INTEGER NOT NULL,
    snapshot_date     TEXT NOT NULL,
    notes             TEXT
);

-- v3a: engine koordinasi distance. calculation_context TIDAK menaikkan
-- management scope (+1 hop tetap dipakai utk register/UI) -- ini konteks
-- perhitungan PER RELE yang traversal graph-nya independen dari batas
-- scope, sesuai "Management scope vs calculation context" di prompt v2.
--
-- 1 baris = 1 (relay_function, zone) yang dihitung. `zone` bebas teks
-- ('Z1','Z2','Z3','REVERSE', dst) supaya tidak terikat 1 taksonomi zona
-- vendor tertentu -- rele ABB REL670 py ZM01..ZM05 terpisah, vendor lain
-- mungkin py penamaan beda; jangan hardcode ke skema 1 vendor.
--
-- `status` HANYA salah satu dari 4 nilai yang didefinisikan prompt:
-- complete | incomplete_topology | incomplete_external | ambiguous_branch.
-- Bila graph terputus, `status` menandai TITIK PUTUSNYA (lewat
-- calculation_branch.status di baris terakhir yang berhasil) -- BUKAN
-- mengestimasi impedansi/line yang hilang.
-- Diperluas (semula cuma cumulative_r/x_ohm) supaya hasil kaya
-- Zone1/2/3Result (distance_engine.py) queryable langsung tanpa parse
-- JSON -- konsisten dgn pola relay_setting yang jg eksplisit per kolom,
-- bukan blob. cumulative_r/x_ohm dipertahankan sbg ALIAS reach primer
-- (nama netral-vendor utk keperluan traversal/audit graph, lihat
-- komentar asli di bawah); reach_*_ohm/ground_fault_*_ohm/rfpp_ohm/
-- delay_s/reach_percent adalah field spesifik distance_engine.py.
CREATE TABLE calculation_context (
    context_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    relay_function_id  INTEGER NOT NULL REFERENCES relay_function(relay_function_id),
    line_id            INTEGER NOT NULL REFERENCES line(line_id),  -- protected line
    zone                TEXT NOT NULL,       -- 'Z1' | 'Z2' | 'Z3' | 'REVERSE' | ...
    direction           TEXT NOT NULL,       -- 'FORWARD' | 'REVERSE'
    status              TEXT NOT NULL,       -- complete | incomplete_topology | incomplete_external | ambiguous_branch
    cumulative_r_ohm    REAL,     -- impedansi kumulatif R sepanjang path yang DIPAKAI (bukan semua cabang dicoba) -- alias reach_primary_r_ohm
    cumulative_x_ohm    REAL,     -- alias reach_primary_x_ohm
    reach_secondary_r_ohm REAL,   -- reach phase-phase sisi sekunder (relay), Zone1/2/3Result.z_secondary_ohm.real
    reach_secondary_x_ohm REAL,   -- Zone1/2/3Result.z_secondary_ohm.imag
    ground_fault_primary_r_ohm   REAL,  -- reach ground fault (zero-sequence), Zone*Result.z0_primary_ohm.real
    ground_fault_primary_x_ohm   REAL,
    ground_fault_secondary_r_ohm REAL,
    ground_fault_secondary_x_ohm REAL,
    rfpp_primary_ohm     REAL,    -- resistive reach phase-to-phase, Zone*Result.rfpp_primary_ohm
    rfpp_secondary_ohm   REAL,
    reach_percent        REAL,    -- thd |ZL11| protected line -- Zone*Result.reach_percent
    delay_s              REAL,    -- NULL bila T3/T2 belum py sumber definitif (jangan ditebak)
    selected_branch_line_id INTEGER REFERENCES line(line_id),  -- NULL bila fallback/cap trafo, bukan cabang manapun
    safety_cap_hops     INTEGER NOT NULL DEFAULT 3,  -- prompt: cap 3 hop, traversal tidak boleh lewat ini
    model_version       TEXT,     -- versi topologi yang jadi dasar hitung (selaras line_electrical.model_version)
    computed_at         TEXT NOT NULL,
    UNIQUE (relay_function_id, zone, direction)
);

CREATE INDEX idx_calculation_context_relay_function ON calculation_context(relay_function_id);
CREATE INDEX idx_calculation_context_line ON calculation_context(line_id);

-- Ordered path/cabang yang DICOBA selama traversal satu calculation_context
-- -- bukan cuma path yang akhirnya dipakai. Z3 minimal py >1 baris (protected
-- line + tiap cabang di remote bus + next line), termasuk cabang yang
-- dicoba lalu tidak dipakai (mis. karena ambiguous_branch/beda arah) --
-- transparansi keputusan traversal adalah bagian dari spek, bukan detail
-- implementasi yang boleh disembunyikan.
CREATE TABLE calculation_branch (
    branch_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id           INTEGER NOT NULL REFERENCES calculation_context(context_id),
    step_order           INTEGER NOT NULL,     -- urutan traversal, 1-based
    line_id               INTEGER REFERENCES line(line_id),  -- NULL bila step gagal sebelum resolve ke line manapun
    from_ss_id            INTEGER REFERENCES substation(ss_id),
    to_ss_id              INTEGER REFERENCES substation(ss_id),
    branch_r_ohm          REAL,     -- kontribusi R segmen INI saja (bukan kumulatif)
    branch_x_ohm          REAL,
    is_selected           INTEGER NOT NULL DEFAULT 0,  -- 1 = bagian dari path final yang dipakai reach
    branch_status         TEXT NOT NULL,   -- complete | incomplete_topology | incomplete_external | ambiguous_branch
    note                  TEXT,     -- alasan (mis. kenapa cabang ini tidak dipilih)
    UNIQUE (context_id, step_order)
);

CREATE INDEX idx_calculation_branch_context ON calculation_branch(context_id);
