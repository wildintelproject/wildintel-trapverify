export function formatPsi(
  psi: number | null,
  lo: number | null,
  hi: number | null,
  degenerate: boolean,
): string {
  if (degenerate || psi == null) return '—'
  const ciLo = lo != null ? lo.toFixed(3) : '?'
  const ciHi = hi != null ? hi.toFixed(3) : '?'
  return `${psi.toFixed(3)} [${ciLo}, ${ciHi}]`
}

export function formatP(p: number | null): string {
  return p != null ? p.toFixed(3) : '—'
}
