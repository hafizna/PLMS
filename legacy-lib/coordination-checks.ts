import { Diagnostic, Relay, Topology, Corridor } from "./domain-types";
import {
  buildCorridorSegments,
  computeRelayZoneExtents,
  CorridorSegment,
} from "./corridor-math";

const TIME_GRADING_MARGIN_S = 0.3;

// Get all relays whose segment is part of the active corridor.
function relaysOnCorridor(corridor: Corridor, topology: Topology): Relay[] {
  const segIds = new Set(corridor.ordered_segment_ids);
  return topology.relays.filter((r) => segIds.has(r.segment_id));
}

// Get the X impedance of a segment.
function segXImpedance(cs: CorridorSegment): number {
  return cs.segment.length_km * cs.X_per_km;
}

export function runCoordinationChecks(
  topology: Topology,
  corridor: Corridor,
  effectiveRelay: (id: string) => Relay
): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];
  const cs = buildCorridorSegments(corridor, topology);
  const relays = relaysOnCorridor(corridor, topology).map((r) => effectiveRelay(r.id));

  for (const relay of relays) {
    const segCs = cs.find((c) => c.segment.id === relay.segment_id);
    if (!segCs) continue;
    const segX = segXImpedance(segCs);
    const [Z1, Z2, Z3] = relay.zones;

    // ---- Check 1: Z1 under-reach margin (should be 70-85% of segment X) ----
    const z1_pct = (Z1.X_reach_ohm / segX) * 100;
    if (z1_pct < 70) {
      diagnostics.push({
        id: `${relay.id}_Z1_UNDERREACH`,
        severity: "warning",
        code: "Z1_UNDERREACH",
        title: `${relay.bay_name}: Z1 reach below typical 80% margin`,
        detail: `Z1 X reach is ${Z1.X_reach_ohm.toFixed(2)} ohm = ${z1_pct.toFixed(0)}% of line X (${segX.toFixed(2)} ohm). Standard practice is 80%, with 70-85% acceptable. Below 70% leaves more of the line uncovered by instantaneous protection than necessary.`,
        affected_relay_ids: [relay.id],
        affected_zones: ["Z1"],
      });
    } else if (z1_pct > 85) {
      diagnostics.push({
        id: `${relay.id}_Z1_OVERREACH`,
        severity: "error",
        code: "Z1_OVERREACH",
        title: `${relay.bay_name}: Z1 risk of remote-bus over-reach`,
        detail: `Z1 X reach is ${Z1.X_reach_ohm.toFixed(2)} ohm = ${z1_pct.toFixed(0)}% of line X (${segX.toFixed(2)} ohm). Z1 must under-reach the remote bus to remain selective; values >85% risk false instantaneous tripping for faults beyond the remote bus due to measurement error and infeed.`,
        affected_relay_ids: [relay.id],
        affected_zones: ["Z1"],
      });
    }

    // ---- Check 2: Z2 must reach beyond remote bus ----
    if (Z2.X_reach_ohm < segX) {
      diagnostics.push({
        id: `${relay.id}_Z2_SHORT`,
        severity: "error",
        code: "Z2_SHORT",
        title: `${relay.bay_name}: Z2 does not reach remote bus`,
        detail: `Z2 X reach is ${Z2.X_reach_ohm.toFixed(2)} ohm but the protected line X is ${segX.toFixed(2)} ohm. Z2 must reach beyond the remote bus to provide full primary coverage of the protected line; current setting leaves a gap.`,
        affected_relay_ids: [relay.id],
        affected_zones: ["Z2"],
      });
    }

    // ---- Check 3: Z2 over-reach into next-next line ----
    const z2_pct = (Z2.X_reach_ohm / segX) * 100;
    if (z2_pct > 250) {
      diagnostics.push({
        id: `${relay.id}_Z2_OVERREACH`,
        severity: "warning",
        code: "Z2_OVERREACH",
        title: `${relay.bay_name}: Z2 reaches deep into downstream lines`,
        detail: `Z2 X reach is ${z2_pct.toFixed(0)}% of the protected line. This typically over-reaches into the second downstream line, creating coordination complexity that may require time-grading checks against the remote bay's Z2 timer.`,
        affected_relay_ids: [relay.id],
        affected_zones: ["Z2"],
      });
    }

    // ---- Check 4: Z2/Z3 time grading sanity ----
    if (Z2.time_delay_pp_s <= 0) {
      diagnostics.push({
        id: `${relay.id}_Z2_INSTANT`,
        severity: "error",
        code: "Z2_INSTANT",
        title: `${relay.bay_name}: Z2 timer is zero (no selectivity)`,
        detail: `Z2 trips instantaneously. This defeats the purpose of zone time grading and will trip the bay for faults outside the protected line that should be cleared by remote relays first.`,
        affected_relay_ids: [relay.id],
        affected_zones: ["Z2"],
      });
    }
    if (Z3.time_delay_pp_s - Z2.time_delay_pp_s < TIME_GRADING_MARGIN_S) {
      diagnostics.push({
        id: `${relay.id}_Z2_Z3_MARGIN`,
        severity: "warning",
        code: "Z2_Z3_MARGIN",
        title: `${relay.bay_name}: Z2 and Z3 timer separation below margin`,
        detail: `Z2 = ${Z2.time_delay_pp_s.toFixed(2)} s, Z3 = ${Z3.time_delay_pp_s.toFixed(2)} s. Difference of ${(Z3.time_delay_pp_s - Z2.time_delay_pp_s).toFixed(2)} s is below the typical 300 ms minimum margin between zones to ensure selective backup operation.`,
        affected_relay_ids: [relay.id],
        affected_zones: ["Z2", "Z3"],
      });
    }
  }

  // ---- Check 5: Z2 reach-vs-downstream-Z1 coordination ----
  // For each forward relay, find the next forward relay on the corridor.
  // Z2 of upstream should be greater than Z1 of downstream (so it provides backup
  // for the remote line section).
  for (let i = 0; i < cs.length - 1; i++) {
    const upSeg = cs[i];
    const downSeg = cs[i + 1];

    // Find the forward relay at the downstream end of upSeg (looking into downSeg)
    const upFwdRelay = relays.find(
      (r) =>
        r.segment_id === upSeg.segment.id &&
        r.direction === "forward" &&
        r.substation_id === upSeg.segment.from_substation
    );
    const downFwdRelay = relays.find(
      (r) =>
        r.segment_id === downSeg.segment.id &&
        r.direction === "forward" &&
        r.substation_id === downSeg.segment.from_substation
    );
    if (!upFwdRelay || !downFwdRelay) continue;

    // Z2 reach of upstream (in km along corridor)
    const upExtents = computeRelayZoneExtents(upFwdRelay, cs);
    const downExtents = computeRelayZoneExtents(downFwdRelay, cs);
    if (!upExtents || !downExtents) continue;

    const upZ2EndKm = upExtents.zone_extents[1].endpoint.km;
    const downZ1EndKm = downExtents.zone_extents[0].endpoint.km;

    // Upstream Z2 should reach beyond downstream Z1's end (otherwise no overlap = backup gap)
    if (upZ2EndKm < downZ1EndKm) {
      diagnostics.push({
        id: `${upFwdRelay.id}_BACKUP_GAP`,
        severity: "warning",
        code: "BACKUP_GAP",
        title: `Backup gap: ${upFwdRelay.bay_name} Z2 does not cover ${downFwdRelay.bay_name} Z1 territory`,
        detail: `Z2 of upstream relay ends at ${upZ2EndKm.toFixed(2)} km but Z1 of downstream relay reaches ${downZ1EndKm.toFixed(2)} km. There is a ${(downZ1EndKm - upZ2EndKm).toFixed(2)} km region between the two zones with no fast backup if the downstream Z1 fails.`,
        affected_relay_ids: [upFwdRelay.id, downFwdRelay.id],
      });
    }

    // Time grading: t(Z2_up) should be greater than or equal to t(Z1_down) + margin
    const z2UpTime = effectiveRelay(upFwdRelay.id).zones[1].time_delay_pp_s;
    const z1DownTime = effectiveRelay(downFwdRelay.id).zones[0].time_delay_pp_s;
    if (z2UpTime - z1DownTime < TIME_GRADING_MARGIN_S) {
      diagnostics.push({
        id: `${upFwdRelay.id}_Z2_DOWN_Z1_RACE`,
        severity: "warning",
        code: "Z2_DOWN_Z1_RACE",
        title: `Time race risk: ${upFwdRelay.bay_name} Z2 vs ${downFwdRelay.bay_name} Z1`,
        detail: `Z2 timer of upstream (${z2UpTime.toFixed(2)} s) leaves only ${(z2UpTime - z1DownTime).toFixed(2)} s margin over downstream Z1 (${z1DownTime.toFixed(2)} s). For overlapping fault locations both relays will see the fault; the downstream Z1 must clear first.`,
        affected_relay_ids: [upFwdRelay.id, downFwdRelay.id],
      });
    }
  }

  return diagnostics;
}

export function summarizeDiagnostics(diags: Diagnostic[]) {
  return {
    error: diags.filter((d) => d.severity === "error").length,
    warning: diags.filter((d) => d.severity === "warning").length,
    info: diags.filter((d) => d.severity === "info").length,
    ok: diags.filter((d) => d.severity === "ok").length,
  };
}
