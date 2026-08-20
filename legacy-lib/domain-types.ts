// Extracted from POC_PLMS (repo lama) src/domain/types.ts.
// HANYA tipe yang dipakai oleh 5 modul kalkulasi murni di legacy-lib/.
// Tipe governance/approval lama (TapSettingRecord, ApprovalAction, dst)
// SENGAJA dibuang -- lihat PLMS_Rebuild_Prompt_v2.md prinsip #1.
//
// Ini adalah titik awal, BUKAN skema final. Model data resmi ada di
// bagian "Model data" PLMS_Rebuild_Prompt_v2.md (site/substation/line/...).
// Modul kalkulasi ini perlu diadaptasi ke skema itu saat dipakai di v3.

export type Substation = {
  id: string;
  name: string;
  short_code: string;
  voltage_kv: number;
  is_synthetic?: boolean;
};

export type ConductorSpec = {
  type: string;
  is_underground: boolean;
  Z1_R_per_km: number;
  Z1_X_per_km: number;
  Z0_R_per_km: number;
  Z0_X_per_km: number;
};

export type LineSegment = {
  id: string;
  from_substation: string;
  to_substation: string;
  length_km: number;
  conductor: ConductorSpec;
  is_synthetic?: boolean;
};

export type ZoneId = "Z1" | "Z2" | "Z3";

export type Zone = {
  id: ZoneId;
  X_reach_ohm: number;
  R_reach_ohm: number;
  RFPP_ohm_per_loop: number;
  RFPE_ohm_per_loop: number;
  time_delay_pp_s: number;
  time_delay_pe_s: number;
  operate_pp: boolean;
  operate_pe: boolean;
};

export type LoadEncroachment = {
  enabled: boolean;
  RLdFw_ohm_per_phase: number;
  RLdRv_ohm_per_phase: number;
  ArgLd_deg: number;
};

export type RelayDirection = "forward" | "reverse";

export type Relay = {
  id: string;
  substation_id: string;
  segment_id: string;
  direction: RelayDirection;
  make: string;
  model: string;
  bay_name: string;
  setting_doc_no?: string;
  setting_doc_valid_from?: string;
  zones: [Zone, Zone, Zone];
  load_encroachment: LoadEncroachment;
  characteristic_angle_deg: number;
  is_synthetic?: boolean;
};

// Topology = collection of substations, segments, relays.
// A "corridor" is an ordered list of segment IDs forming a path through this graph.
export type Topology = {
  substations: Substation[];
  segments: LineSegment[];
  relays: Relay[];
};

export type Corridor = {
  id: string;
  label: string;
  ordered_segment_ids: string[];
  start_substation_id: string;
  axis_unit_label?: string;
};

// Diagnostic types
export type DiagnosticSeverity = "ok" | "info" | "warning" | "error";

export type Diagnostic = {
  id: string;
  severity: DiagnosticSeverity;
  code: string;
  title: string;
  detail: string;
  affected_relay_ids: string[];
  affected_zones?: ZoneId[];
};
