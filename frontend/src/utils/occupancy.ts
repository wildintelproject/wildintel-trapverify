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

export function formatP(p: number | null, lo?: number | null, hi?: number | null): string {
  if (p == null) return '—'
  if (lo == null || hi == null) return p.toFixed(3)
  return `${p.toFixed(3)} [${lo.toFixed(3)}, ${hi.toFixed(3)}]`
}
