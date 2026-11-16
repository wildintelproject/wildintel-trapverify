import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '../i18n'

const api = vi.hoisted(() => ({ getResults: vi.fn(), getOccupancy: vi.fn(), openFolder: vi.fn() }))
vi.mock('../api', () => ({ api }))

import ResultsPage from './ResultsPage'

const results = (pending: number) => ({
  session_dir: '/s', output_dir: '/s/o', total: 10, confirmed: 4, rejected: 6 - pending, unverified: 0, pending,
  by_species: [
    { species: 'Vulpes vulpes', confirmed: 3, rejected: 3 - pending, pending, unverified: 0 },
    { species: 'Sus scrofa', confirmed: 1, rejected: 3, pending: 0, unverified: 0 },
  ],
  seq_total: 12, seq_confirmed: 4, seq_rejected: 8, seq_unverified: 0, by_species_seqs: [],
  effort_by_species: [], min_score: 0.5, record_rejection_species: false, false_positive_sources: [],
  datapackage_generated: false, datapackage_fabricated_fields: [],
})

beforeEach(async () => {
  await i18n.changeLanguage('en')
  vi.clearAllMocks()
  api.getOccupancy.mockResolvedValue([])
})

const renderResults = () => render(<MemoryRouter><ResultsPage /></MemoryRouter>)

describe('ResultsPage pending cells', () => {
  it('says how many occasions are still pending expert review, and which species', async () => {
    api.getResults.mockResolvedValue(results(2))
    renderResults()
    const banner = await screen.findByTestId('pending-banner')
    expect(banner).toHaveTextContent('2 occasions are still pending expert review')
    expect(within(banner).getByText('Vulpes vulpes')).toBeInTheDocument()
    expect(within(banner).queryByText('Sus scrofa')).toBeNull()                   // none pending
    expect(banner).toHaveTextContent('dethist_verified_*.csv')
  })

  it('shows no banner without pending cells', async () => {
    api.getResults.mockResolvedValue(results(0))
    renderResults()
    await screen.findByText('Sus scrofa', { exact: false })
    expect(screen.queryByTestId('pending-banner')).toBeNull()
  })

  it('keeps the tooltip of the pending card free of HTML tags', async () => {
    api.getResults.mockResolvedValue(results(2))
    const { container } = renderResults()
    await screen.findByTestId('pending-banner')
    const card = container.querySelector('[title*="dethist_verified"]') as HTMLElement
    expect(card.getAttribute('title')).not.toMatch(/<code>/)
  })
})
