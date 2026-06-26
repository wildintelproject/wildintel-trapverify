import type { DetectionEvent, SpeciesStats, WorkflowConfig } from './types'

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const r = await fetch(url, options)
  if (!r.ok) {
    const text = await r.text().catch(() => r.statusText)
    throw new Error(text)
  }
  return r.json() as Promise<T>
}

function post<T>(url: string, body: unknown): Promise<T> {
  return req<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

function put<T>(url: string, body: unknown): Promise<T> {
  return req<T>(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const api = {
  getState: () =>
    req<{ ready: boolean; config?: WorkflowConfig; default_output_dir?: string }>('/api/state'),

  setup: (config: WorkflowConfig) =>
    post<{ ok: boolean; n_candidates: number; n_combos: number }>('/api/setup', config),

  getSpecies: () =>
    req<SpeciesStats[]>('/api/species'),

  getEvents: (species: string, iteration: number) =>
    req<DetectionEvent[]>(`/api/species/${species}/events?iteration=${iteration}`),

  getReview: (species: string) =>
    req<DetectionEvent[]>(`/api/species/${species}/review`),

  updateDecisions: (species: string, confirmedKeys: string[]) =>
    put<{ success: boolean; confirmed: number }>(
      `/api/species/${species}/decisions`,
      { confirmed_keys: confirmedKeys },
    ),

  getDecisions: (species: string, iteration: number) =>
    req<{ confirmed: string[] }>(`/api/decisions?species=${species}&iteration=${iteration}`),

  saveDecisions: (species: string, iteration: number, confirmed: string[]) =>
    post<{ success: boolean; done: boolean; next_iteration: number | null; remaining: number }>(
      '/api/decisions',
      { species, iteration, confirmed },
    ),

  rejectBurst: (mediaId: string) =>
    post<{ success: boolean; removed: string[] }>('/api/reject', { mediaId }),

  unreject: (media: string[]) =>
    post<{ success: boolean }>('/api/unreject', { media }),

  getRejected: () =>
    req<{ rejected: string[] }>('/api/rejected'),

  inspectDir: (path: string) =>
    req<{ species: string[]; study_start: string | null; study_end: string | null }>(
      `/api/fs/inspect?path=${encodeURIComponent(path)}`,
    ),

  getResults: () =>
    req<{
      session_dir: string
      output_dir: string
      total: number
      confirmed: number
      rejected: number
      unverified: number
      by_species: { species: string; confirmed: number; rejected: number; unverified: number }[]
    }>('/api/results'),

  openFolder: () =>
    req<{ ok: boolean; path: string }>('/api/open-folder', { method: 'POST' }),
}
