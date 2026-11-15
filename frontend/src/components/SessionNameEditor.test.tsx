import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18n from '../i18n'

const api = vi.hoisted(() => ({ renameSession: vi.fn() }))
vi.mock('../api', () => ({ api }))

import SessionNameEditor from './SessionNameEditor'

beforeAll(async () => { await i18n.changeLanguage('en') })
beforeEach(() => { vi.clearAllMocks() })

const rename = () => screen.getByRole('button', { name: 'Rename the session' })

describe('SessionNameEditor', () => {
  it('shows the name, or the fallback in italics when there is none', () => {
    const { rerender } = render(<SessionNameEditor sessionDir="" name="Spring" fallback="no name" />)
    expect(screen.getByText('Spring')).toBeInTheDocument()
    rerender(<SessionNameEditor sessionDir="" name="" fallback="no name" />)
    expect(screen.getByText('no name')).toHaveClass('italic')
  })

  it('turns into a text field with the current name when ✎ is pressed', async () => {
    render(<SessionNameEditor sessionDir="" name="Spring" fallback="no name" />)
    await userEvent.click(rename())
    expect(screen.getByRole('textbox')).toHaveValue('Spring')
  })

  it('saves with Enter, tells the parent the cleaned name and goes back to showing it', async () => {
    api.renameSession.mockResolvedValue({ session_dir: '/s/1', session_name: 'Autumn' })
    const onRenamed = vi.fn()
    const onDone = vi.fn()
    render(<SessionNameEditor sessionDir="/s/1" name="Spring" fallback="-" onRenamed={onRenamed} onDone={onDone} />)
    await userEvent.click(rename())
    const box = screen.getByRole('textbox')
    await userEvent.clear(box)
    await userEvent.type(box, '  Autumn  {Enter}')
    await waitFor(() => expect(onRenamed).toHaveBeenCalledWith('Autumn'))
    expect(api.renameSession).toHaveBeenCalledWith('/s/1', '  Autumn  ')           // the server cleans the spaces
    expect(onDone).toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('saves with the Save button and cancels with Escape or Cancel without calling the server', async () => {
    api.renameSession.mockResolvedValue({ session_dir: '', session_name: 'X' })
    render(<SessionNameEditor sessionDir="" name="Spring" fallback="-" />)
    await userEvent.click(rename())
    await userEvent.type(screen.getByRole('textbox'), '{Escape}')
    expect(api.renameSession).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).toBeNull()
    await userEvent.click(rename())
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.renameSession).not.toHaveBeenCalled()
    await userEvent.click(rename())
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.renameSession).toHaveBeenCalledWith('', 'Spring'))
  })

  it('can clear the name (an empty value is sent) ', async () => {
    api.renameSession.mockResolvedValue({ session_dir: '', session_name: '' })
    const onRenamed = vi.fn()
    render(<SessionNameEditor sessionDir="" name="Spring" fallback="-" onRenamed={onRenamed} />)
    await userEvent.click(rename())
    await userEvent.clear(screen.getByRole('textbox'))
    await userEvent.type(screen.getByRole('textbox'), '{Enter}')
    await waitFor(() => expect(onRenamed).toHaveBeenCalledWith(''))
    expect(api.renameSession).toHaveBeenCalledWith('', '')
  })

  it('shows the error and stays in the text field when saving fails', async () => {
    api.renameSession.mockRejectedValue(new Error('Not a known session'))
    const onRenamed = vi.fn()
    render(<SessionNameEditor sessionDir="/gone" name="" fallback="-" onRenamed={onRenamed} />)
    await userEvent.click(rename())
    await userEvent.type(screen.getByRole('textbox'), 'A{Enter}')
    expect(await screen.findByText('Not a known session')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toBeInTheDocument()
    expect(onRenamed).not.toHaveBeenCalled()
  })

  it('opens straight in the text field with startEditing', () => {
    render(<SessionNameEditor sessionDir="/s" name="" fallback="-" startEditing />)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('limits the name to 120 characters', async () => {
    render(<SessionNameEditor sessionDir="" name="" fallback="-" startEditing />)
    expect(screen.getByRole('textbox')).toHaveAttribute('maxlength', '120')
  })
})
