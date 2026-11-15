import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import i18n from '../i18n'
import type { DetectionEvent, SpeciesStats } from '../types'

const stats = (over: Partial<SpeciesStats> = {}): SpeciesStats => ({
  species_name: 'Vulpes vulpes', species_safe: 'Vulpes_vulpes', n_total_combos: 4, n_confirmed_combos: 1,
  n_resolved: 2, current_iteration: 3, ...over,
} as SpeciesStats)

const event = (key: string, rank: number): DetectionEvent => ({
  key, siteId: 'S1', occasion: 1, rank, totalSeqs: 3, repObsId: `obs-${key}`, maxProb: 0.8,
  frames: [{ obsId: `obs-${key}`, mediaId: `m-${key}`, img: `/api/image/m-${key}`, ts: '2026-01-01 10:00:00', prob: 0.8 }],
})

const api = vi.hoisted(() => ({
  getSpecies: vi.fn(), getState: vi.fn(), getEvents: vi.fn(), getDecisions: vi.fn(), getReview: vi.fn(),
  getTaxa: vi.fn(), saveDecisions: vi.fn(), updateDecisions: vi.fn(),
}))
vi.mock('../api', () => ({ api }))

import GalleryPage from './GalleryPage'

function renderGallery() {
  return render(
    <MemoryRouter initialEntries={['/gallery/Vulpes_vulpes']}>
      <Routes><Route path="/gallery/:species" element={<GalleryPage />} /></Routes>
    </MemoryRouter>,
  )
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
  vi.clearAllMocks()
  api.getState.mockResolvedValue({ ready: true, config: { total_iterations: 10, gap_seconds: 60, occasion_days: 5, min_score: 0.5 } })
  api.getDecisions.mockResolvedValue({ confirmed: [], uncertain: [], corrections: {} })
  api.getEvents.mockResolvedValue([event('a', 3)])
  api.getReview.mockResolvedValue([])
  api.getTaxa.mockResolvedValue({ taxa: [], extra: [] })
})

describe('GalleryPage', () => {
  it('opens a species at its current round, not at round 1', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 3 })])
    renderGallery()
    await waitFor(() => expect(api.getEvents).toHaveBeenCalled())
    expect(api.getEvents).toHaveBeenCalledTimes(1)                       // no wasted load of round 1
    expect(api.getEvents).toHaveBeenCalledWith('Vulpes_vulpes', 3)
    expect(api.getDecisions).toHaveBeenCalledWith('Vulpes_vulpes', 3)
    expect(await screen.findByText('Round 3')).toBeInTheDocument()
  })

  it('opens a species that has no round done yet at round 1', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 1, n_resolved: 0, n_confirmed_combos: 0 })])
    renderGallery()
    await waitFor(() => expect(api.getEvents).toHaveBeenCalledWith('Vulpes_vulpes', 1))
  })

  it('falls back to round 1 when the species list cannot be read', async () => {
    api.getSpecies.mockRejectedValue(new Error('offline'))
    renderGallery()
    await waitFor(() => expect(api.getEvents).toHaveBeenCalledWith('Vulpes_vulpes', 1))
  })

  it('shows the confirmed event of a completed species with its real rank', async () => {
    api.getSpecies.mockResolvedValue([stats({ n_resolved: 4, n_total_combos: 4, current_iteration: 4 })])
    api.getReview.mockResolvedValue([{ ...event('c', 2), status: 'confirmed' }])
    renderGallery()
    expect(await screen.findByText(/Detection event 2\/3/)).toBeInTheDocument()
  })

  it('shows the cut-off of the species being reviewed, not the general one', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 1, n_resolved: 0, n_confirmed_combos: 0 })])
    api.getState.mockResolvedValue({ ready: true, config: {
      total_iterations: 10, gap_seconds: 60, occasion_days: 5, min_score: 0.5, min_score_by_species: { 'Vulpes vulpes': 0.8 },
    } })
    const { container } = renderGallery()
    await waitFor(() => expect(container.textContent).toContain('detection confidence of 0.8'))
    expect(container.textContent).not.toContain('detection confidence of 0.5')
  })

  it('shows the general cut-off for a species without its own', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 1, n_resolved: 0, n_confirmed_combos: 0 })])
    api.getState.mockResolvedValue({ ready: true, config: {
      total_iterations: 10, gap_seconds: 60, occasion_days: 5, min_score: 0.5, min_score_by_species: { 'Sus scrofa': 0.9 },
    } })
    const { container } = renderGallery()
    await waitFor(() => expect(container.textContent).toContain('detection confidence of 0.5'))
  })
})
