import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import i18n from '../i18n'

const api = vi.hoisted(() => ({
  getState: vi.fn(), getRecentSessions: vi.fn(), getSpecies: vi.fn(), renameSession: vi.fn(), loadSession: vi.fn(),
  mcDefaults: vi.fn(),
}))
vi.mock('../api', () => ({ api }))

import SetupPage from './SetupPage'

const recent = [
  { session_dir: '/s/a', last_opened: '2026-11-10T10:00:00', session_name: 'Doñana spring 2023', target_species: ['Cervus elaphus', 'Sus scrofa'], study_start: '2025-11-01', study_end: '2025-11-30' },
  { session_dir: '/s/b', last_opened: '2026-11-09T10:00:00', session_name: '', target_species: ['Vulpes vulpes'], study_start: null, study_end: null },
]

beforeEach(async () => {
  await i18n.changeLanguage('en')
  vi.clearAllMocks()
  api.getState.mockResolvedValue({ ready: false, default_output_dir: '/out' })
  api.getRecentSessions.mockResolvedValue(recent)
  api.getSpecies.mockResolvedValue([])
  api.mcDefaults.mockResolvedValue({ output_dir: '/out/conversions' })
})

function renderSetup() {
  return render(<MemoryRouter><SetupPage ready={false} onSetup={vi.fn()} /></MemoryRouter>)
}

describe('recent sessions on the welcome screen', () => {
  it('shows the name with the species below it, and the species alone for an unnamed session', async () => {
    renderSetup()
    const named = await screen.findByRole('button', { name: 'Open Doñana spring 2023' })
    expect(within(named).getByText('Doñana spring 2023')).toBeInTheDocument()
    expect(within(named).getByText('Cervus elaphus, Sus scrofa')).toBeInTheDocument()
    const unnamed = screen.getByRole('button', { name: 'Open Vulpes vulpes' })
    expect(within(unnamed).getByText('Vulpes vulpes')).toBeInTheDocument()
  })

  it('opens a session by its folder when its row is pressed', async () => {
    renderSetup()
    await userEvent.click(await screen.findByRole('button', { name: 'Open Doñana spring 2023' }))
    await waitFor(() => expect(api.loadSession).toHaveBeenCalledWith('/s/a'))
  })

  it('renames a session from the list and refreshes the list', async () => {
    api.renameSession.mockResolvedValue({ session_dir: '/s/b', session_name: 'Foxes' })
    renderSetup()
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Vulpes vulpes' }))
    const box = screen.getByRole('textbox')
    expect(box).toHaveValue('')
    await userEvent.type(box, 'Foxes{Enter}')
    await waitFor(() => expect(api.renameSession).toHaveBeenCalledWith('/s/b', 'Foxes'))
    await waitFor(() => expect(api.getRecentSessions).toHaveBeenCalledTimes(2))     // the list is read again
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('does not open the session while renaming it', async () => {
    renderSetup()
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Doñana spring 2023' }))
    expect(screen.getByRole('textbox')).toHaveValue('Doñana spring 2023')
    expect(api.loadSession).not.toHaveBeenCalled()
  })
})

describe('local data formats', () => {
  async function openFormats() {
    renderSetup()
    await userEvent.click(await screen.findByRole('button', { name: /Start verifying/ }))
    await userEvent.click(await screen.findByRole('button', { name: /Local filesystem/ }))
  }

  it('offers Classifiers and reference next to the CamtrapDP, DeepFaune and CSV formats', async () => {
    await openFormats()
    for (const name of [/CamtrapDP directory|CamtrapDP folder/, /DeepFaune/, /Custom CSV|CSV/, /Classifiers and reference/]) {
      expect(screen.getAllByRole('button', { name }).length).toBeGreaterThan(0)
    }
  })

  it('opens the combination form from that option', async () => {
    await openFormats()
    await userEvent.click(screen.getByRole('button', { name: /Classifiers and reference/ }))
    expect(await screen.findByRole('heading', { name: 'Classifiers and reference' })).toBeInTheDocument()
  })
})
