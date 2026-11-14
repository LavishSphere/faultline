/**
 * Display formatting of API dollar figures (docs/FINANCE_REVIEW.md F4, F20; #157). Formatting only: no figure is
 * derived here, each function renders the one number it is given.
 */

const WHOLE = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const CENTS = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const WHOLE_SIGNED = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
  signDisplay: "exceptZero",
});
const CENTS_SIGNED = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

/**
 * True when the value sits on a half dollar (x.50, to the cent). Rounding such a value to whole dollars is a coin
 * toss decided by float noise (−4,812.4999… vs −4,812.5000…), so a figure and its Δ vs a whole-dollar baseline could
 * be rounded in opposite directions and stop adding up (F20). Those values are shown with cents instead.
 */
export function isHalfDollar(n: number): boolean {
  const frac = Math.abs(n) % 1;
  return Math.abs(frac - 0.5) < 0.005;
}

/** Whole dollars, or cents when the value is on a half dollar (F20). Never renders "-$0". */
export function usd(n: number): string {
  if (isHalfDollar(n)) return CENTS.format(n);
  return WHOLE.format(Math.round(n) || 0);
}

/** Same as `usd`, with an explicit sign (+ / −) for a Δ; zero is unsigned. */
export function usdDelta(n: number): string {
  if (isHalfDollar(n)) return CENTS_SIGNED.format(n);
  return WHOLE_SIGNED.format(Math.round(n) || 0);
}

/** Dollars and cents, rounded DOWN to the cent: for a ceiling such as the highest feasible floor (F4). */
export function usdCentsFloor(n: number): string {
  // The 1e-9 guard keeps a value that is a whole number of cents up to float noise (2018749.9999999998) on its cent.
  return CENTS.format(Math.floor(n * 100 + 1e-9) / 100);
}

/** Week numbers served by the API as ranges, e.g. [20, …, 26] → "20–26", [3, 5, 6, 7] → "3, 5–7". */
export function weekRanges(weeks: readonly number[]): string {
  const parts: string[] = [];
  let i = 0;
  while (i < weeks.length) {
    let j = i;
    while (j + 1 < weeks.length && weeks[j + 1] === weeks[j]! + 1) j += 1;
    parts.push(j === i ? `${weeks[i]}` : `${weeks[i]}–${weeks[j]}`);
    i = j + 1;
  }
  return parts.join(", ");
}
