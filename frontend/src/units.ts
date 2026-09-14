const KG_PER_POUND = 0.45359237;
const CM_PER_INCH = 2.54;
const ML_PER_FLUID_OUNCE = 29.5735295625;

function round(value: number, decimals: number) {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

export const poundsToKg = (pounds: number) => round(pounds * KG_PER_POUND, 3);
export const kgToPounds = (kg: number) => round(kg / KG_PER_POUND, 1);
export const inchesToCm = (inches: number) => round(inches * CM_PER_INCH, 1);
export const cmToInches = (cm: number) => round(cm / CM_PER_INCH, 1);
export const fluidOuncesToMl = (ounces: number) => round(ounces * ML_PER_FLUID_OUNCE, 1);
export const mlToFluidOunces = (ml: number) => round(ml / ML_PER_FLUID_OUNCE, 1);
