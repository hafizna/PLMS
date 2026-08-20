export type DistanceCalculationInput = {
  bayName: string;
  relayModel: string;
  nominalVoltageKv: number;
  lineLengthKm: number;
  r1PerKm: number;
  x1PerKm: number;
  nextLineROhm: number;
  nextLineXOhm: number;
  ctPrimaryA: number;
  ctSecondaryA: number;
  vtPrimaryKv: number;
  vtSecondaryV: number;
  z1Percent: number;
  z2Percent: number;
  z3OwnLinePercent: number;
  z3NextLinePercent: number;
  rfppMultiplier: number;
  rfpeMultiplier: number;
  z2DelayS: number;
  z3DelayS: number;
  loadMw: number;
  loadPowerFactor: number;
};

export type DistanceZoneResult = {
  id: "Z1" | "Z2" | "Z3";
  xPrimaryOhm: number;
  rPrimaryOhm: number;
  xSecondaryOhm: number;
  rSecondaryOhm: number;
  rfppOhm: number;
  rfpeOhm: number;
  delayS: number;
  formula: string;
};

export type DistanceCalculationResult = {
  lineROhm: number;
  lineXOhm: number;
  lineZOhm: number;
  lineAngleDeg: number;
  ctRatio: number;
  vtRatio: number;
  secondaryFactor: number;
  loadImpedanceOhm: number | null;
  zones: DistanceZoneResult[];
  warnings: string[];
};

export const DEFAULT_DISTANCE_INPUT: DistanceCalculationInput = {
  bayName: "Select Line",
  relayModel: "Generic Relay",
  nominalVoltageKv: 150,
  lineLengthKm: 1.0,
  r1PerKm: 0.1,
  x1PerKm: 0.4,
  nextLineROhm: 0.1,
  nextLineXOhm: 0.4,
  ctPrimaryA: 1000,
  ctSecondaryA: 1,
  vtPrimaryKv: 150,
  vtSecondaryV: 100,
  z1Percent: 80,
  z2Percent: 120,
  z3OwnLinePercent: 100,
  z3NextLinePercent: 100,
  rfppMultiplier: 2.0,
  rfpeMultiplier: 5.0,
  z2DelayS: 0.4,
  z3DelayS: 1.2,
  loadMw: 100,
  loadPowerFactor: 0.85,
};

function round(value: number, digits = 3): number {
  return Number(value.toFixed(digits));
}

export function calculateDistanceSetting(
  input: DistanceCalculationInput
): DistanceCalculationResult {
  const lineROhm = input.lineLengthKm * input.r1PerKm;
  const lineXOhm = input.lineLengthKm * input.x1PerKm;
  const lineZOhm = Math.hypot(lineROhm, lineXOhm);
  const lineAngleDeg = (Math.atan2(lineXOhm, lineROhm) * 180) / Math.PI;
  const ctRatio = input.ctPrimaryA / input.ctSecondaryA;
  const vtRatio = (input.vtPrimaryKv * 1000) / input.vtSecondaryV;
  const secondaryFactor = ctRatio / vtRatio;
  const loadMva =
    input.loadPowerFactor > 0 ? input.loadMw / input.loadPowerFactor : 0;
  const loadImpedanceOhm =
    loadMva > 0 ? (input.nominalVoltageKv * input.nominalVoltageKv) / loadMva : null;

  const z1X = lineXOhm * (input.z1Percent / 100);
  const z1R = lineROhm * (input.z1Percent / 100);
  const z2X = lineXOhm * (input.z2Percent / 100);
  const z2R = lineROhm * (input.z2Percent / 100);
  const z3X =
    lineXOhm * (input.z3OwnLinePercent / 100) +
    input.nextLineXOhm * (input.z3NextLinePercent / 100);
  const z3R =
    lineROhm * (input.z3OwnLinePercent / 100) +
    input.nextLineROhm * (input.z3NextLinePercent / 100);

  const rawZones: DistanceZoneResult[] = [
    {
      id: "Z1",
      xPrimaryOhm: z1X,
      rPrimaryOhm: z1R,
      xSecondaryOhm: z1X * secondaryFactor,
      rSecondaryOhm: z1R * secondaryFactor,
      rfppOhm: z1X * input.rfppMultiplier,
      rfpeOhm: z1X * input.rfpeMultiplier,
      delayS: 0,
      formula: `Z1 = ${input.z1Percent}% x protected line`,
    },
    {
      id: "Z2",
      xPrimaryOhm: z2X,
      rPrimaryOhm: z2R,
      xSecondaryOhm: z2X * secondaryFactor,
      rSecondaryOhm: z2R * secondaryFactor,
      rfppOhm: z2X * input.rfppMultiplier,
      rfpeOhm: z2X * input.rfpeMultiplier,
      delayS: input.z2DelayS,
      formula: `Z2 = ${input.z2Percent}% x protected line`,
    },
    {
      id: "Z3",
      xPrimaryOhm: z3X,
      rPrimaryOhm: z3R,
      xSecondaryOhm: z3X * secondaryFactor,
      rSecondaryOhm: z3R * secondaryFactor,
      rfppOhm: z3X * input.rfppMultiplier,
      rfpeOhm: z3X * input.rfpeMultiplier,
      delayS: input.z3DelayS,
      formula: `Z3 = ${input.z3OwnLinePercent}% x protected line + ${input.z3NextLinePercent}% x next line`,
    },
  ];

  const zones: DistanceZoneResult[] = rawZones.map((zone) => ({
    ...zone,
    xPrimaryOhm: round(zone.xPrimaryOhm),
    rPrimaryOhm: round(zone.rPrimaryOhm),
    xSecondaryOhm: round(zone.xSecondaryOhm),
    rSecondaryOhm: round(zone.rSecondaryOhm),
    rfppOhm: round(zone.rfppOhm),
    rfpeOhm: round(zone.rfpeOhm),
  }));

  const warnings: string[] = [];
  if (input.z1Percent < 70) {
    warnings.push("Z1 di bawah 70% line: instantaneous coverage terlalu pendek.");
  }
  if (input.z1Percent > 85) {
    warnings.push("Z1 di atas 85% line: ada risiko overreach ke remote bus.");
  }
  if (input.z2Percent < 100) {
    warnings.push("Z2 belum mencapai remote bus, line tidak tercakup penuh.");
  }
  if (input.z2DelayS <= 0) {
    warnings.push("Timer Z2 nol, selectivity terhadap downstream relay tidak terjaga.");
  }
  if (input.z3DelayS - input.z2DelayS < 0.3) {
    warnings.push("Margin timer Z2-Z3 kurang dari 300 ms.");
  }
  if (loadImpedanceOhm !== null && loadImpedanceOhm < zones[2].rfpeOhm) {
    warnings.push("Load impedance berada dekat resistive reach Z3, perlu review load encroachment.");
  }

  return {
    lineROhm: round(lineROhm),
    lineXOhm: round(lineXOhm),
    lineZOhm: round(lineZOhm),
    lineAngleDeg: round(lineAngleDeg, 2),
    ctRatio: round(ctRatio, 2),
    vtRatio: round(vtRatio, 2),
    secondaryFactor: round(secondaryFactor, 6),
    loadImpedanceOhm: loadImpedanceOhm === null ? null : round(loadImpedanceOhm),
    zones,
    warnings,
  };
}
