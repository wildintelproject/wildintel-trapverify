import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18n from '../i18n'

const api = vi.hoisted(() => ({ relinkSession: vi.fn() }))
vi.mock('../api', () => ({ api }))

import RelinkDialog from './RelinkDialog'

beforeAll(async () => { await i18n.changeLanguage('en') })
beforeEach(() => { vi.clearAllMocks() })

const status = {
  camtrap_dir_ok: false, images_ok: false, needs_relink: true,
  camtrap_dir: 'C:\\data\\dp', image_base_dir: 'D:\\photos', flat_search: false,
}

describe('RelinkDialog', () => {
  it('shows where the folders were and cannot be saved without a data folder', () => {
    render(<RelinkDialog status={status} onDone={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByText('Was: C:\\data\\dp')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Link folders' })).toBeDisabled()
  })

  it('sends the chosen folders and reports the new status', async () => {
    const fresh = { ...status, camtrap_dir_ok: true, images_ok: true, needs_relink: false }
    api.relinkSession.mockResolvedValue({ ok: true, relink: fresh })
    const onDone = vi.fn()
    render(<RelinkDialog status={status} onDone={onDone} onClose={vi.fn()} />)
    await userEvent.type(screen.getAllByRole('textbox')[0], '/home/me/dp')
    await userEvent.click(screen.getByRole('button', { name: 'Link folders' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(fresh))
    expect(api.relinkSession).toHaveBeenCalledWith('/home/me/dp', '', false)
  })

  it('shows the server error and stays open', async () => {
    api.relinkSession.mockRejectedValue(new Error('Different dataset'))
    const onDone = vi.fn()
    render(<RelinkDialog status={status} onDone={onDone} onClose={vi.fn()} />)
    await userEvent.type(screen.getAllByRole('textbox')[0], '/x')
    await userEvent.click(screen.getByRole('button', { name: 'Link folders' }))
    expect(await screen.findByText('Different dataset')).toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()
  })
})
