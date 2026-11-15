/** Cut-off that applies to a species: its own value if it has one, else the general one. */
export function effectiveMinScore(
  general: number,
  bySpecies: Record<string, number> | undefined,
  species: string | undefined,
): number {
  const own = species ? bySpecies?.[species] : undefined
  return typeof own === 'number' && Number.isFinite(own) ? own : general
}

/** The per-species cut-offs to send: only selected species, only finite values within 0 to 1. */
export function cleanSpeciesCutoffs(
  bySpecies: Record<string, number> | undefined,
  selected: Iterable<string>,
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const sp of selected) {
    const v = bySpecies?.[sp]
    if (typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1) out[sp] = v
  }
  return out
}

/** True when any cut-off (the general one or a species') is above 0, i.e. photos can be left out. */
export function anyCutoff(general: number, bySpecies: Record<string, number> | undefined): boolean {
  return general > 0 || Object.values(bySpecies ?? {}).some((v) => v > 0)
}
