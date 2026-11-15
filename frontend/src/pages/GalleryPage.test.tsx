import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
  getProgress: vi.fn(), saveProgress: vi.fn(), reopenRound: vi.fn(),
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
  api.getDecisions.mockResolvedValue({ confirmed: [], unsure: [], corrections: {} })
  api.getEvents.mockResolvedValue([event('a', 3)])
  api.getReview.mockResolvedValue([])
  api.getTaxa.mockResolvedValue({ taxa: [], extra: [] })
  api.getProgress.mockResolvedValue({ progress: null })
  api.saveProgress.mockResolvedValue({ success: true, saved_at: '2026-01-01T10:00:00+00:00', n: 1 })
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

  it('restores the progress saved in the session folder, so finishing the round uses it', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 3 })])
    api.getProgress.mockResolvedValue({ progress: {
      iteration: 3, decisions: { 'obs-a': 'confirmed' }, corrections: {}, decision_times: { 'obs-a': 1700000000000 },
      saved_at: '2026-01-01T10:00:00+00:00',
    } })
    api.saveDecisions.mockResolvedValue({ success: true, done: true, next_iteration: null, remaining: 0 })
    renderGallery()
    await screen.findByText('Round 3')
    await userEvent.click(await screen.findByRole('button', { name: 'Finish round' }))
    await waitFor(() => expect(api.saveDecisions).toHaveBeenCalled())
    expect(api.saveDecisions).toHaveBeenCalledWith('Vulpes_vulpes', 3, ['obs-a'], [], {}, { 'obs-a': 1700000000000 })
    expect(api.saveProgress).not.toHaveBeenCalled()                       // restoring is not a change to save
  })

  it('saves the progress with the button, by the event\'s representative observation', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 3 })])
    renderGallery()
    await userEvent.click(await screen.findByRole('button', { name: /Confirm all in this location/ }))
    await userEvent.click(screen.getByRole('button', { name: /Save progress/ }))
    await waitFor(() => expect(api.saveProgress).toHaveBeenCalled())
    const [sp, body] = api.saveProgress.mock.calls[0]
    expect(sp).toBe('Vulpes_vulpes')
    expect(body.iteration).toBe(3)
    expect(body.decisions).toEqual({ 'obs-a': 'confirmed' })
  })

  it('reopens the previous round and loads it', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 3 })])
    api.reopenRound.mockResolvedValue({ success: true, iteration: 2, restored: 1 })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderGallery()
    await userEvent.click(await screen.findByRole('button', { name: /Back to round 2/ }))
    await waitFor(() => expect(api.reopenRound).toHaveBeenCalledWith('Vulpes_vulpes'))
    await waitFor(() => expect(api.getEvents).toHaveBeenLastCalledWith('Vulpes_vulpes', 2))
  })

  it('offers no way back in the first round', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 1, n_resolved: 0, n_confirmed_combos: 0 })])
    renderGallery()
    await screen.findByText('Round 1')
    expect(screen.queryByRole('button', { name: /Back to round/ })).toBeNull()
  })

  describe('large view', () => {
    const open = async () => {
      api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
      api.getEvents.mockResolvedValue([event('a', 2), event('b', 2), event('c', 2)])
      renderGallery()
      await userEvent.click(await screen.findByRole('button', { name: 'Large view' }))
      return await screen.findByTestId('lb-panel')
    }

    it('shows the progress of the round, the location and the species beside the photo', async () => {
      const panel = await open()
      expect(panel).toHaveTextContent('Round 2')
      expect(panel).toHaveTextContent('0 of 3 cards decided')
      expect(panel).toHaveTextContent('Location S1: 0 of 3')
      expect(panel).toHaveTextContent('2 of 4 occasions resolved before this round')
    })

    it('moves to the next card after a decision and goes back with Backspace, keeping the decision', async () => {
      await open()
      const panel = () => screen.getByTestId('lb-panel')                   // the lightbox remounts per card
      await userEvent.keyboard('y')
      await waitFor(() => expect(panel()).toHaveTextContent('1 of 3 cards decided'))
      const prev = screen.getByRole('button', { name: /Previous card/ })
      expect(prev).toBeEnabled()
      await userEvent.keyboard('{Backspace}')
      // back on the card just decided, which still shows as confirmed
      const confirm = screen.getAllByRole('button', { name: /Confirmed/ }).find((b) => b.className.includes('bg-emerald-600'))
      expect(confirm).toBeTruthy()
      expect(panel()).toHaveTextContent('1 of 3 cards decided')               // nothing was undone
    })

    it('has nothing to go back to on the first card', async () => {
      await open()
      expect(screen.getByRole('button', { name: /Previous card/ })).toBeDisabled()
    })

    it('uses the strip at the bottom on a narrow screen', async () => {
      Object.defineProperty(window, 'innerWidth', { value: 500, configurable: true })
      api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
      api.getEvents.mockResolvedValue([event('a', 2), event('b', 2)])
      renderGallery()
      await userEvent.click(await screen.findByRole('button', { name: 'Large view' }))
      expect(await screen.findByRole('button', { name: 'Previous card' })).toBeInTheDocument()
      expect(screen.queryByTestId('lb-panel')).toBeNull()
      Object.defineProperty(window, 'innerWidth', { value: 1024, configurable: true })
    })
  })

  describe('one location at a time', () => {
    const two = () => [{ ...event('a', 2), siteId: 'S1' }, { ...event('b', 2), siteId: 'S1' }, { ...event('c', 2), siteId: 'S2' }]
    const setup = () => {
      api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
      api.getEvents.mockResolvedValue(two())
      return renderGallery()
    }

    it('shows only the cards of the current location', async () => {
      const { container } = setup()
      await screen.findByText('Location 1 of 2', { exact: false })
      expect(container.querySelectorAll('[data-key]')).toHaveLength(2)
      await userEvent.click(screen.getAllByRole('button', { name: /Next location/ })[0])
      await waitFor(() => expect(container.querySelectorAll('[data-key]')).toHaveLength(1))
      expect(container.querySelector('[data-key="c"]')).not.toBeNull()
    })

    it('lists the locations with their progress', async () => {
      setup()
      const select = await screen.findByRole('combobox')
      expect(select).toHaveTextContent('S1 · 0/2')
      expect(select).toHaveTextContent('S2 · 0/1')
    })

    it('confirms only the location being shown and still finishes the round with every decision', async () => {
      api.saveDecisions.mockResolvedValue({ success: true, done: true, next_iteration: null, remaining: 0 })
      setup()
      await userEvent.click(await screen.findByRole('button', { name: /Confirm all in this location/ }))
      // S2 still undecided: finishing is refused and jumps to it
      await userEvent.click(screen.getByRole('button', { name: 'Finish round' }))
      expect(api.saveDecisions).not.toHaveBeenCalled()
      await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue('1'))
      await userEvent.click(screen.getByRole('button', { name: /Confirm all in this location/ }))
      await userEvent.click(screen.getByRole('button', { name: 'Finish round' }))
      await waitFor(() => expect(api.saveDecisions).toHaveBeenCalled())
      expect(api.saveDecisions.mock.calls[0][2].sort()).toEqual(['obs-a', 'obs-b', 'obs-c'])
    })
  })

  it('explains that each occasion is represented by its earliest event when reviewing by time', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
    api.getState.mockResolvedValue({ ready: true, config: { total_iterations: 10, gap_seconds: 60, occasion_days: 5, min_score: 0.5, review_order: 'time' } })
    renderGallery()
    expect(await screen.findByText(/earliest detection event not yet reviewed/)).toBeInTheDocument()
  })

  it('keeps the confidence wording when reviewing by score', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
    renderGallery()
    expect(await screen.findByText(/highest detection confidence among those not yet reviewed/)).toBeInTheDocument()
  })
})
