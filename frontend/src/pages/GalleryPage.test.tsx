import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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
  getPending: vi.fn(), settlePending: vi.fn(),
  getCross: vi.fn(), addCross: vi.fn(), removeCross: vi.fn(),
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
      mode: 'rounds', iteration: 3, decisions: { a: 'confirmed' }, chosen_rep: {}, corrections: {}, decision_times: { a: 1700000000000 },
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

  it('restores the draft kept by this browser when it is newer than the server progress, and sends it', async () => {
    localStorage.clear()
    api.getState.mockResolvedValue({ ready: true, session_dir: '/sessions/s1', config: { total_iterations: 10, gap_seconds: 60, occasion_days: 5, min_score: 0.5 } })
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 3 })])
    api.getProgress.mockResolvedValue({ progress: {
      mode: 'rounds', iteration: 3, decisions: {}, chosen_rep: {}, corrections: {}, decision_times: {},
      saved_at: '2026-01-01T10:00:00+00:00',
    } })
    localStorage.setItem('camtrap-verify:draft:/sessions/s1|Vulpes_vulpes|rounds|3',
      JSON.stringify({ decisions: { a: 'confirmed' }, chosenRep: {}, savedAt: '2026-01-01T11:00:00+00:00' }))
    api.saveDecisions.mockResolvedValue({ success: true, done: true, next_iteration: null, remaining: 0 })
    renderGallery()
    await screen.findByText('Round 3')
    await userEvent.click(await screen.findByRole('button', { name: 'Finish round' }))
    await waitFor(() => expect(api.saveDecisions).toHaveBeenCalled())
    expect(api.saveDecisions.mock.calls[0][2]).toEqual(['obs-a'])               // the draft's decision, not the empty server one
    expect(localStorage.getItem('camtrap-verify:draft:/sessions/s1|Vulpes_vulpes|rounds|3')).toBeNull()   // dropped with the round
    localStorage.clear()
  })

  it('saves the progress with the button, by the cell key of each event', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 3 })])
    renderGallery()
    await userEvent.click(await screen.findByRole('button', { name: /Confirm all in this location/ }))
    await userEvent.click(screen.getByRole('button', { name: /Save progress/ }))
    await waitFor(() => expect(api.saveProgress).toHaveBeenCalled())
    const [sp, body] = api.saveProgress.mock.calls[0]
    expect(sp).toBe('Vulpes_vulpes')
    expect(body.mode).toBe('rounds')
    expect(body.iteration).toBe(3)
    expect(body.decisions).toEqual({ a: 'confirmed' })
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
    expect(await screen.findByText(/earliest detection event among those not yet reviewed/)).toBeInTheDocument()
  })

  it('keeps the confidence wording when reviewing by score', async () => {
    api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
    renderGallery()
    expect(await screen.findByText(/highest detection confidence among those not yet reviewed/)).toBeInTheDocument()
  })

  describe('pending expert review', () => {
    const pendingEvent = (key: string): DetectionEvent => ({
      ...event(key, 2), status: 'pending',
      frames: [
        { obsId: `obs-${key}-1`, mediaId: `m1-${key}`, img: `/api/image/m1-${key}`, ts: '2026-01-01 10:00:00', prob: 0.4, burstRepObsId: `rep-${key}-1` },
        { obsId: `obs-${key}-2`, mediaId: `m2-${key}`, img: `/api/image/m2-${key}`, ts: '2026-01-01 11:00:00', prob: 0.7, burstRepObsId: `rep-${key}-2` },
      ],
    })

    beforeEach(() => {
      api.getSpecies.mockResolvedValue([stats({ phase: 'pending', n_pending: 2, n_resolved: 2, current_iteration: 4 })])
      api.getPending.mockResolvedValue([pendingEvent('a'), pendingEvent('b')])
    })

    it('says which unsure event of the cell is shown and in which pending round', async () => {
      api.getPending.mockResolvedValue([
        { ...pendingEvent('a'), pendingIndex: 2, pendingTotal: 3 },
        { ...pendingEvent('b'), pendingIndex: 1, pendingTotal: 1 },
      ])
      renderGallery()
      expect(await screen.findByText(/Pending expert review · Round 1/)).toBeInTheDocument()   // the earliest round still open
      expect(screen.getByText('unsure event 2 of 3')).toBeInTheDocument()
      expect(screen.getAllByTestId('pending-pos')).toHaveLength(1)                           // a cell with one unsure event shows no position
    })

    it('shows the pending cells instead of a round, and saves without deciding every one', async () => {
      api.settlePending.mockResolvedValue({ success: true, confirmed: 1, rejected: 0 })
      renderGallery()
      expect(await screen.findByText(/Pending expert review/)).toBeInTheDocument()
      expect(api.getEvents).not.toHaveBeenCalledWith('Vulpes_vulpes', 4)
      expect(screen.getByRole('button', { name: /Save progress/ })).toBeInTheDocument()   // the pending verdicts are autosaved too
      await userEvent.click(screen.getAllByRole('button', { name: /Confirmed/ })[0])
      await userEvent.click(screen.getByRole('button', { name: 'Save verdicts' }))
      await waitFor(() => expect(api.settlePending).toHaveBeenCalled())
      // the second cell was left alone: it is not sent, so it stays pending
      expect(api.settlePending).toHaveBeenCalledWith('Vulpes_vulpes', ['rep-a-2'], [])
    })

    it('records the event of the photo being looked at when confirming', async () => {
      api.settlePending.mockResolvedValue({ success: true, confirmed: 1, rejected: 0 })
      renderGallery()
      await screen.findByText(/Pending expert review/)
      const card = document.querySelector('[data-key="a"]') as HTMLElement
      await userEvent.click(within(card).getByRole('button', { name: /previous photo/i }))        // best frame is #2: go to #1
      await userEvent.click(within(card).getByRole('button', { name: /Confirmed/ }))
      await userEvent.click(screen.getByRole('button', { name: 'Save verdicts' }))
      await waitFor(() => expect(api.settlePending).toHaveBeenCalledWith('Vulpes_vulpes', ['rep-a-1'], []))
    })

    it('saves the pending verdicts as progress, with the photo being looked at, and restores them', async () => {
      renderGallery()
      await screen.findByText(/Pending expert review/)
      const card = document.querySelector('[data-key="a"]') as HTMLElement
      await userEvent.click(within(card).getByRole('button', { name: /previous photo/i }))
      await userEvent.click(within(card).getByRole('button', { name: /Confirmed/ }))
      await userEvent.click(screen.getByRole('button', { name: /Save progress/ }))
      await waitFor(() => expect(api.saveProgress).toHaveBeenCalled())
      const [, body] = api.saveProgress.mock.calls[0]
      expect(body).toMatchObject({ mode: 'pending', iteration: 0, decisions: { a: 'confirmed' }, chosen_rep: { a: 'rep-a-1' } })
    })

    it('restores unsaved pending verdicts when the view is opened again', async () => {
      api.getProgress.mockResolvedValue({ progress: {
        mode: 'pending', iteration: 0, decisions: { b: 'rejected' }, chosen_rep: {}, corrections: {}, decision_times: {},
        saved_at: '2026-01-01T10:00:00+00:00',
      } })
      api.settlePending.mockResolvedValue({ success: true, confirmed: 0, rejected: 1 })
      renderGallery()
      await screen.findByText(/Pending expert review/)
      expect(api.getProgress).toHaveBeenCalledWith('Vulpes_vulpes', 'pending', 0)
      await userEvent.click(screen.getByRole('button', { name: 'Save verdicts' }))
      await waitFor(() => expect(api.settlePending).toHaveBeenCalledWith('Vulpes_vulpes', [], ['b']))
      expect(api.saveProgress).not.toHaveBeenCalled()
    })

    it('shows how many occasions are pending expert review in the header', async () => {
      renderGallery()
      expect(await screen.findByText('2 pending expert review')).toBeInTheDocument()
    })

    it('settles a cell as not detected when it is rejected', async () => {
      api.settlePending.mockResolvedValue({ success: true, confirmed: 0, rejected: 1 })
      renderGallery()
      await screen.findByText(/Pending expert review/)
      await userEvent.click(screen.getAllByRole('button', { name: /Rejected/ })[1])
      await userEvent.click(screen.getByRole('button', { name: 'Save verdicts' }))
      await waitFor(() => expect(api.settlePending).toHaveBeenCalledWith('Vulpes_vulpes', [], ['b']))
    })
  })

  describe('another species in the photo', () => {
    const cell = (status: 'none' | 'cross' | 'confirmed', mediaID?: string) => [
      { scientificName: 'Vulpes vulpes', species_safe: 'Vulpes_vulpes', status: 'none' },
      { scientificName: 'Sus scrofa', species_safe: 'Sus_scrofa', status, mediaID },
    ]
    const setup = async (status: 'none' | 'cross' | 'confirmed' = 'none', mediaID?: string) => {
      api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
      api.getState.mockResolvedValue({ ready: true, config: { total_iterations: 10, gap_seconds: 60, occasion_days: 5, min_score: 0.5, target_species: ['Vulpes vulpes', 'Sus scrofa'] } })
      api.getEvents.mockResolvedValue([event('a', 2), event('b', 2)])
      api.getCross.mockResolvedValue({ species: cell(status, mediaID) })
      api.addCross.mockResolvedValue({ success: true, key: 'k' })
      api.removeCross.mockResolvedValue({ success: true, removed: 1 })
      renderGallery()
      await userEvent.click(await screen.findByRole('button', { name: 'Large view' }))
      return await screen.findByTestId('lb-cross')
    }

    it('lists the other target species in the large view, not the one being reviewed', async () => {
      const panel = await setup()
      expect(within(panel).getByRole('button', { name: /Sus scrofa/ })).toBeInTheDocument()
      expect(within(panel).queryByRole('button', { name: /Vulpes vulpes/ })).toBeNull()
    })

    it('confirms the other species from the photo being viewed', async () => {
      const panel = await setup()
      await userEvent.click(within(panel).getByRole('button', { name: /Sus scrofa/ }))
      await waitFor(() => expect(api.addCross).toHaveBeenCalled())
      expect(api.addCross).toHaveBeenCalledWith({
        species: 'Sus scrofa', site_id: 'S1', occasion: 1, media_id: 'm-a', observation_id: 'obs-a', source_species: 'Vulpes vulpes',
      })
    })

    it('undoes it with a second click when it was confirmed from this event', async () => {
      const panel = await setup('cross', 'm-a')
      await userEvent.click(within(panel).getByRole('button', { name: /Sus scrofa/ }))
      await waitFor(() => expect(api.removeCross).toHaveBeenCalledWith('Sus scrofa', 'S1', 1))
      expect(api.addCross).not.toHaveBeenCalled()
    })

    it('does not offer to change a species already confirmed in this occasion', async () => {
      const panel = await setup('confirmed')
      expect(within(panel).getByRole('button', { name: /Sus scrofa/ })).toBeDisabled()
    })

    it('treats a species confirmed from another detection event of the occasion the same way', async () => {
      const panel = await setup('cross', 'some-other-photo')
      expect(within(panel).getByRole('button', { name: /Sus scrofa/ })).toBeDisabled()
      expect(within(panel).getByText(/already confirmed in this occasion/)).toBeInTheDocument()
    })

    it('reminds that Confirmed here is right only with animals of both species, and stays on the card once', async () => {
      await setup('cross', 'm-a')
      await userEvent.keyboard('y')
      expect(await screen.findByRole('note')).toHaveTextContent(/right only if there are animals of both/)
      expect(screen.getByText(/Image 1\/1/)).toBeInTheDocument()
    })
  })

  describe('messages and hints', () => {
    it('tells how many detection events still need a decision when finishing a round', async () => {
      api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
      api.getEvents.mockResolvedValue([event('a', 2), event('b', 2), event('c', 2)])
      renderGallery()
      await userEvent.click(await screen.findByRole('button', { name: 'Finish round' }))
      expect(await screen.findByText(/3 detection events still need a decision/)).toBeInTheDocument()
      expect(api.saveDecisions).not.toHaveBeenCalled()
    })

    it('says so in the user\'s language when a round has no events', async () => {
      api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
      api.getEvents.mockResolvedValue([])
      renderGallery()
      expect(await screen.findByText('No pending detection events for this species in this round.')).toBeInTheDocument()
    })

    it('points at the large view and its keys while a round is under review', async () => {
      api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
      renderGallery()
      expect(await screen.findByText('Tip:')).toBeInTheDocument()
      expect(screen.getByText(/Y confirmed, U unsure, N rejected/)).toBeInTheDocument()
    })

    it('names the species being reviewed in the large view', async () => {
      api.getSpecies.mockResolvedValue([stats({ current_iteration: 2 })])
      renderGallery()
      await userEvent.click(await screen.findByRole('button', { name: 'Large view' }))
      expect(await screen.findByTestId('lb-panel')).toHaveTextContent('Reviewing: Vulpes vulpes')
    })

    it('does not save pending verdicts when none was decided', async () => {
      api.getSpecies.mockResolvedValue([stats({ phase: 'pending', n_pending: 1, n_resolved: 3, current_iteration: 4 })])
      api.getPending.mockResolvedValue([{ ...event('a', 2), status: 'pending' }])
      renderGallery()
      await userEvent.click(await screen.findByRole('button', { name: 'Save verdicts' }))
      expect(await screen.findByText('You have not confirmed or rejected any pending occasion.')).toBeInTheDocument()
      expect(api.settlePending).not.toHaveBeenCalled()
    })
  })
})
