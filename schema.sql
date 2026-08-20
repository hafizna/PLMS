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

-- v2+: register rele. Didefinisikan sekarang karena protection_chain/
-- relay_setting mereferensikannya, tapi loader v1 TIDAK mengisi tabel ini.
CREATE TABLE relay (
    relay_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ss_id              INTEGER NOT NULL REFERENCES substation(ss_id),
    bay                TEXT,
    line_id            INTEGER REFERENCES line(line_id),
    function_type      TEXT,     -- DIST, LCD, OCR, OCR_KOPEL, DIFF, DV,
                                  -- BUSPRO, AR, CBF, SYNCHRO, CCP, SZP, KAPASITOR
    coordination_class TEXT,     -- GRADED | UNIT | AUXILIARY
    manufacturer       TEXT,
    model              TEXT,
    serial_no          TEXT,
    ct_ratio           TEXT,
    pt_ratio           TEXT,
    status             TEXT,
    pst_asset_id       TEXT      -- rujukan register aset PLN; tidak diintegrasikan tahap ini
);

CREATE INDEX idx_relay_ss ON relay(ss_id);
CREATE INDEX idx_relay_line ON relay(line_id);

-- v3+: rantai grading vertikal. TERPISAH dari `line` karena arahnya
-- menembus level tegangan di dalam satu GI, bukan antar-GI.
CREATE TABLE protection_chain (
    chain_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_type        TEXT,      -- OCR_GRADING | GFR_GRADING
    relay_id          INTEGER NOT NULL REFERENCES relay(relay_id),
    upstream_relay_id INTEGER REFERENCES relay(relay_id),
    level_order       INTEGER,
    voltage_kv        REAL,
    chain_status      TEXT       -- complete | incomplete_external
);

-- v2+: setting rele, key-value panjang (parameter terlalu beragam untuk skema lebar).
CREATE TABLE relay_setting (
    setting_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    relay_id         INTEGER NOT NULL REFERENCES relay(relay_id),
    parameter_name   TEXT,
    parameter_value  TEXT,
    unit             TEXT,
    setting_group    TEXT,
    effective_date   TEXT,
    source_doc       TEXT,
    is_current       INTEGER,
    topology_version TEXT,       -- versi model yang jadi dasar hitung
    source_event_id  TEXT        -- rujukan Power Inspect; tidak diintegrasikan tahap ini
);

CREATE INDEX idx_relay_setting_relay ON relay_setting(relay_id);

CREATE TABLE scope_definition (
    scope_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_name        TEXT NOT NULL,
    seed_substations  TEXT,      -- JSON array nama GI seed
    hop_depth         INTEGER NOT NULL,
    snapshot_date     TEXT NOT NULL,
    notes             TEXT
);
