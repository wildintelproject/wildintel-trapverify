import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18n from '../i18n'

const api = vi.hoisted(() => ({ setClassifiedBy: vi.fn() }))
vi.mock('../api', () => ({ api }))

import ClassifiedByEditor from './ClassifiedByEditor'

beforeAll(async () => { await i18n.changeLanguage('en') })
beforeEach(() => { vi.clearAllMocks() })

const edit = () => screen.getByRole('button', { name: 'Change who is credited as classifiedBy' })

describe('ClassifiedByEditor', () => {
  it('saves with Enter and shows the value the server kept', async () => {
    api.setClassifiedBy.mockResolvedValue({ classified_by: 'Jennifer R.; Santiago G.' })
    const onChanged = vi.fn()
    render(<ClassifiedByEditor value="Jennifer R." onChanged={onChanged} />)
    expect(screen.getByTestId('classified-by')).toHaveTextContent('Jennifer R.')
    await userEvent.click(edit())
    const box = screen.getByRole('textbox')
    expect(box).toHaveValue('Jennifer R.')
    await userEvent.type(box, ';  Santiago G.{Enter}')
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('Jennifer R.; Santiago G.'))
    expect(api.setClassifiedBy).toHaveBeenCalledWith('Jennifer R.;  Santiago G.')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('Escape cancels without saving', async () => {
    render(<ClassifiedByEditor value="expert_review" onChanged={vi.fn()} />)
    await userEvent.click(edit())
    await userEvent.type(screen.getByRole('textbox'), 'x{Escape}')
    expect(api.setClassifiedBy).not.toHaveBeenCalled()
    expect(screen.getByTestId('classified-by')).toHaveTextContent('expert_review')
  })

  it('keeps the field open and shows the error when saving fails', async () => {
    api.setClassifiedBy.mockRejectedValue(new Error('No hay sesión activa.'))
    render(<ClassifiedByEditor value="expert_review" onChanged={vi.fn()} />)
    await userEvent.click(edit())
    await userEvent.type(screen.getByRole('textbox'), '{Enter}')
    expect(await screen.findByText('No hay sesión activa.')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })
})
