// Helpers for the R-X plane drilldown view.
// Generates polygon points for quadrilateral characteristic and circle params for MHO.

import { Zone } from "./domain-types";

export type Point = { R: number; X: number };

// Quadrilateral characteristic: simplified rectangular shape tilted by line angle.
// Four corners:
//   - top-right: at the X reach with R reach extension, tilted by angle
//   - top-left: at the X reach with reverse R extension
//   - bottom-right: at zero X with R reach (full RFPP/RFPE)
//   - bottom-left: small reverse R at zero X
export function quadrilateralCorners(
  zone: Zone,
  characteristicAngleDeg: number,
  loopType: "PP" | "PE" = "PP"
): Point[] {
  const angleRad = (characteristicAngleDeg * Math.PI) / 180;
  const cosA = Math.cos(angleRad);
  const sinA = Math.sin(angleRad);
  const X = zone.X_reach_ohm;
  const R_fault = loopType === "PP" ? zone.RFPP_ohm_per_loop : zone.RFPE_ohm_per_loop;
  const R_resistive = R_fault / 2; // half-loop on each side approximation

  // top edge along the line angle, length = R_resistive on each side of the X-reach axis
  const top_center: Point = { R: X * cosA / sinA, X: X };
  const top_right: Point = {
    R: top_center.R + R_resistive * cosA,
    X: top_center.X - R_resistive * sinA + R_resistive * sinA, // simplification: keep at X
  };
  // Use a simpler construction: parallelogram with horizontal R reach at top and bottom,
  // tilted by line angle.
  const top_right_simple: Point = { R: top_center.R + R_resistive, X: X };
  const top_left_simple: Point = { R: top_center.R - R_resistive * 0.5, X: X };
  const bottom_right_simple: Point = { R: R_resistive, X: 0 };
  const bottom_left_simple: Point = { R: -R_resistive * 0.3, X: 0 };

  // Reverse offset for completeness (relays usually have slight reverse to pick up close-in faults)
  const reverseX = -X * 0.05;
  const bottom_right_with_reverse: Point = { R: R_resistive, X: reverseX };
  const bottom_left_with_reverse: Point = { R: -R_resistive * 0.3, X: reverseX };

  return [
    bottom_left_with_reverse,
    bottom_right_with_reverse,
    top_right_simple,
    top_left_simple,
  ];
}

// MHO circle: passes through origin with diameter = X_reach / sin(angle), centered along line angle.
export function mhoCircle(
  zone: Zone,
  characteristicAngleDeg: number
): { centerR: number; centerX: number; radius: number } {
  const angleRad = (characteristicAngleDeg * Math.PI) / 180;
  // Reach magnitude = X / sin(angle) (the impedance magnitude at the line angle)
  const Z_mag = zone.X_reach_ohm / Math.sin(angleRad);
  const radius = Z_mag / 2;
  const centerR = radius * Math.cos(angleRad);
  const centerX = radius * Math.sin(angleRad);
  return { centerR, centerX, radius };
}

// Load encroachment wedge boundary (right half-plane, as a polygon).
export function loadEncroachmentPolygon(
  RLdFw: number,
  ArgLd_deg: number
): Point[] {
  const angleRad = (ArgLd_deg * Math.PI) / 180;
  return [
    { R: 0, X: 0 },
    { R: RLdFw * 1.4, X: RLdFw * 1.4 * Math.tan(angleRad) },
    { R: RLdFw * 1.4, X: -RLdFw * 1.4 * Math.tan(angleRad) },
  ];
}
