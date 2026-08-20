export type OcrCurveType = "SI" | "VI" | "EI" | "LTI";

export type OcrInputs = {
  loadCurrent: number;
  ctPrimary: number;
  ctSecondary: number;
  pickupMultiplier: number;
  curveType: OcrCurveType;
  tms: number;
  faultCurrentMax: number;
  faultCurrentMin: number;
  gradingMarginS: number;
};

export type OcrResults = {
  pickupPrimary: number;
  pickupSecondary: number;
  tripTimeAtMaxFault: number | null;
  tripTimeAtMinFault: number | null;
  ctRatio: number;
  curveK: number;
  curveAlpha: number;
  warnings: string[];
};

const CURVE: Record<OcrCurveType, { k: number; alpha: number }> = {
  SI: { k: 0.14, alpha: 0.02 },
  VI: { k: 13.5, alpha: 1 },
  EI: { k: 80, alpha: 2 },
  LTI: { k: 120, alpha: 1 },
};

function round(value: number, digits = 3) {
  return Number(value.toFixed(digits));
}

function calculateTripTime(faultCurrent: number, pickupPrimary: number, tms: number, curveType: OcrCurveType) {
  const multiple = faultCurrent / pickupPrimary;
  if (!Number.isFinite(multiple) || multiple <= 1) return null;
  const curve = CURVE[curveType];
  return round(tms * (curve.k / (Math.pow(multiple, curve.alpha) - 1)));
}

export function calculateOcr(input: OcrInputs): OcrResults {
  const ctRatio = input.ctSecondary > 0 ? input.ctPrimary / input.ctSecondary : 0;
  const pickupPrimary = input.loadCurrent * input.pickupMultiplier;
  const pickupSecondary = ctRatio > 0 ? pickupPrimary / ctRatio : 0;
  const curve = CURVE[input.curveType];
  const tripTimeAtMaxFault = calculateTripTime(
    input.faultCurrentMax,
    pickupPrimary,
    input.tms,
    input.curveType
  );
  const tripTimeAtMinFault = calculateTripTime(
    input.faultCurrentMin,
    pickupPrimary,
    input.tms,
    input.curveType
  );

  const warnings: string[] = [];
  if (input.pickupMultiplier < 1.05) {
    warnings.push("Pickup terlalu dekat dengan beban maksimum; margin load kurang dari 5%.");
  }
  if (pickupSecondary > 5) {
    warnings.push("Pickup secondary di atas 5 A; cek kembali CT ratio dan relay input nominal.");
  }
  if (tripTimeAtMinFault === null) {
    warnings.push("Fault current minimum tidak melewati pickup; sensitivitas OCR/GFR belum terpenuhi.");
  }
  if (tripTimeAtMaxFault !== null && tripTimeAtMinFault !== null) {
    const spread = tripTimeAtMinFault - tripTimeAtMaxFault;
    if (spread < input.gradingMarginS) {
      warnings.push("Selisih waktu operasi max/min fault lebih kecil dari target grading margin.");
    }
  }
  if (input.tms <= 0) {
    warnings.push("TMS harus lebih besar dari nol.");
  }

  return {
    pickupPrimary: round(pickupPrimary),
    pickupSecondary: round(pickupSecondary, 4),
    tripTimeAtMaxFault,
    tripTimeAtMinFault,
    ctRatio: round(ctRatio, 2),
    curveK: curve.k,
    curveAlpha: curve.alpha,
    warnings,
  };
}
