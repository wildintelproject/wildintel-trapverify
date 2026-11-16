/**
 * A whole number from what a number box holds: decimals are cut off, anything unreadable (an empty
 * box, text) gives ``fallback``, and the result is never below ``min``. The API takes integers for
 * lengths, gaps and seconds and answers a decimal with an unclear 422.
 */
export function wholeNumber(raw: string | number, min: number, fallback: number = min): number {
  const n = Math.trunc(Number(raw))
  if (!Number.isFinite(n) || (typeof raw === 'string' && raw.trim() === '')) return Math.max(min, fallback)
  return Math.max(min, n)
}
