import { LineSegment, Relay, Topology, Corridor, Zone } from "./domain-types";

// Position along a corridor is measured in km from the corridor's start substation.

export type CorridorSegment = {
  segment: LineSegment;
  start_km: number;          // km along corridor where this segment starts
  end_km: number;             // km along corridor where this segment ends
  X_per_km: number;           // positive sequence X impedance per km
  R_per_km: number;
};

export function buildCorridorSegments(
  corridor: Corridor,
  topology: Topology
): CorridorSegment[] {
  let cursor = 0;
  return corridor.ordered_segment_ids.map((segId) => {
    const seg = topology.segments.find((s) => s.id === segId);
    if (!seg) throw new Error(`Segment ${segId} not found in topology`);
    const start_km = cursor;
    const end_km = cursor + seg.length_km;
    cursor = end_km;
    return {
      segment: seg,
      start_km,
      end_km,
      X_per_km: seg.conductor.Z1_X_per_km,
      R_per_km: seg.conductor.Z1_R_per_km,
    };
  });
}

export function corridorTotalKm(cs: CorridorSegment[]): number {
  return cs.length === 0 ? 0 : cs[cs.length - 1].end_km;
}

// Returns the km position where the relay is physically located on the corridor.
// For a relay at substation A protecting segment A->B looking forward, position = start of A->B.
// For a relay at substation B looking back at segment A->B (reverse), position = end of A->B.
export function relayKmOnCorridor(
  relay: Relay,
  cs: CorridorSegment[]
): number | null {
  const seg = cs.find((c) => c.segment.id === relay.segment_id);
  if (!seg) return null;
  const isFromEnd = seg.segment.from_substation === relay.substation_id;
  const isToEnd = seg.segment.to_substation === relay.substation_id;
  if (relay.direction === "forward") {
    if (isFromEnd) return seg.start_km;
    if (isToEnd) return seg.end_km;
  } else {
    if (isToEnd) return seg.end_km;
    if (isFromEnd) return seg.start_km;
  }
  return null;
}

// "Forward direction along corridor" means increasing km, "reverse" means decreasing.
// For a relay's zone, given starting km on corridor and forward/reverse direction,
// walk along corridor consuming X reach. Returns the km position where the zone ends.
//
// If the reach exceeds the corridor extent, the result is clamped to the corridor edge
// and `beyond_corridor` is set to true.
export type ReachEndpoint = {
  km: number;
  segment_id: string | null;     // segment containing the endpoint, or null if outside
  beyond_corridor: boolean;
  exhausted: boolean;             // true if the reach was fully consumed within corridor
};

export function findReachEndKm(
  zoneXReach: number,
  startKm: number,
  walkForward: boolean,
  cs: CorridorSegment[]
): ReachEndpoint {
  if (cs.length === 0) {
    return { km: startKm, segment_id: null, beyond_corridor: true, exhausted: false };
  }

  let remaining = zoneXReach;
  let pos = startKm;

  if (walkForward) {
    // walk segments in increasing order from pos
    for (const seg of cs) {
      if (seg.end_km <= pos) continue;
      const segStart = Math.max(seg.start_km, pos);
      const lenAvailableKm = seg.end_km - segStart;
      const xAvailable = lenAvailableKm * seg.X_per_km;
      if (remaining <= xAvailable) {
        const usedKm = remaining / seg.X_per_km;
        return {
          km: segStart + usedKm,
          segment_id: seg.segment.id,
          beyond_corridor: false,
          exhausted: true,
        };
      }
      remaining -= xAvailable;
      pos = seg.end_km;
    }
    // exceeded corridor end
    return { km: corridorTotalKm(cs), segment_id: null, beyond_corridor: true, exhausted: false };
  } else {
    // walk segments in decreasing order from pos
    for (let i = cs.length - 1; i >= 0; i--) {
      const seg = cs[i];
      if (seg.start_km >= pos) continue;
      const segEnd = Math.min(seg.end_km, pos);
      const lenAvailableKm = segEnd - seg.start_km;
      const xAvailable = lenAvailableKm * seg.X_per_km;
      if (remaining <= xAvailable) {
        const usedKm = remaining / seg.X_per_km;
        return {
          km: segEnd - usedKm,
          segment_id: seg.segment.id,
          beyond_corridor: false,
          exhausted: true,
        };
      }
      remaining -= xAvailable;
      pos = seg.start_km;
    }
    return { km: 0, segment_id: null, beyond_corridor: true, exhausted: false };
  }
}

// Compute reach extents (km positions) for all three zones of a relay on the corridor.
export function computeRelayZoneExtents(
  relay: Relay,
  cs: CorridorSegment[]
): { startKm: number; zone_extents: { zone: Zone; endpoint: ReachEndpoint }[] } | null {
  const startKm = relayKmOnCorridor(relay, cs);
  if (startKm === null) return null;
  const walkForward = directionAlongCorridor(relay, cs);
  if (walkForward === null) return null;
  const extents = relay.zones.map((zone) => ({
    zone,
    endpoint: findReachEndKm(zone.X_reach_ohm, startKm, walkForward, cs),
  }));
  return { startKm, zone_extents: extents };
}

// Determines whether the relay's "forward direction" corresponds to walking
// the corridor in increasing-km direction. This depends on whether the relay's
// substation is the from-end or to-end of its segment.
export function directionAlongCorridor(
  relay: Relay,
  cs: CorridorSegment[]
): boolean | null {
  const seg = cs.find((c) => c.segment.id === relay.segment_id);
  if (!seg) return null;
  const isFromEnd = seg.segment.from_substation === relay.substation_id;
  const isToEnd = seg.segment.to_substation === relay.substation_id;
  if (relay.direction === "forward") {
    if (isFromEnd) return true;   // forward = walking corridor forward
    if (isToEnd) return false;    // sub is at far end, looking forward = walking back
    return null;
  } else {
    if (isToEnd) return false;
    if (isFromEnd) return true;
    return null;
  }
}
