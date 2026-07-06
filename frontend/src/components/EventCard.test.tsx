import { beforeAll, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18n from '../i18n'
import EventCard from './EventCard'
import type { DetectionEvent } from '../types'

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

function makeEvent(overrides: Partial<DetectionEvent> = {}): DetectionEvent {
  return {
    key: 'site1|1',
    siteId: 'site1',
    occasion: 1,
    rank: 1,
    totalSeqs: 2,
    repObsId: 'obs-1',
    maxProb: 0.9,
    frames: [
      { obsId: 'obs-1', mediaId: 'media-1', img: '/img1.jpg', ts: '2026-01-01 10:00', prob: 0.9 },
    ],
    ...overrides,
  }
}

describe('EventCard', () => {
  it('marks pending events that need a decision', () => {
    const { container } = render(
      <EventCard
        event={makeEvent()}
        decision={null}
        needsDecision
        onDecide={vi.fn()}
        onOpenLightbox={vi.fn()}
        eventIdx={0}
      />,
    )
    expect(container.firstChild).toHaveClass('border-amber-400')
  })

  it('highlights confirmed events and marks the confirm button active', () => {
    const { container } = render(
      <EventCard
        event={makeEvent()}
        decision="confirmed"
        needsDecision={false}
        onDecide={vi.fn()}
        onOpenLightbox={vi.fn()}
        eventIdx={0}
      />,
    )
    expect(container.firstChild).toHaveClass('border-emerald-500')
    expect(screen.getByRole('button', { name: /^✓/ })).toHaveClass('bg-emerald-600')
  })

  it('calls onDecide with the event key and repObsId when confirming', async () => {
    const onDecide = vi.fn()
    render(
      <EventCard
        event={makeEvent()}
        decision={null}
        needsDecision
        onDecide={onDecide}
        onOpenLightbox={vi.fn()}
        eventIdx={0}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /^✓/ }))
    expect(onDecide).toHaveBeenCalledWith('site1|1', 'obs-1', 'confirmed')
  })

  it('disables decision buttons in read-only mode', () => {
    render(
      <EventCard
        event={makeEvent()}
        decision={null}
        needsDecision
        onDecide={vi.fn()}
        onOpenLightbox={vi.fn()}
        eventIdx={0}
        readOnly
      />,
    )
    expect(screen.getByRole('button', { name: /^✓/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /no confirmada/i })).toBeDisabled()
  })

  it('opens the lightbox at the highest-confidence frame via the zoom button', async () => {
    const onOpenLightbox = vi.fn()
    render(
      <EventCard
        event={makeEvent({
          frames: [
            { obsId: 'obs-1', mediaId: 'media-1', img: '/img1.jpg', ts: '10:00', prob: 0.4 },
            { obsId: 'obs-2', mediaId: 'media-2', img: '/img2.jpg', ts: '10:01', prob: 0.95 },
            { obsId: 'obs-3', mediaId: 'media-3', img: '/img3.jpg', ts: '10:02', prob: 0.7 },
          ],
        })}
        decision={null}
        needsDecision={false}
        onDecide={vi.fn()}
        onOpenLightbox={onOpenLightbox}
        eventIdx={2}
      />,
    )

    await userEvent.click(screen.getByTitle('Abrir en pantalla completa'))
    expect(onOpenLightbox).toHaveBeenCalledWith(2, 1)
  })

  it('shows the context-frame badge only on context frames', () => {
    render(
      <EventCard
        event={makeEvent({
          frames: [
            { obsId: 'obs-1', mediaId: 'media-1', img: '/img1.jpg', ts: '10:00', prob: 0.9, isContext: true },
          ],
        })}
        decision={null}
        needsDecision={false}
        onDecide={vi.fn()}
        onOpenLightbox={vi.fn()}
        eventIdx={0}
      />,
    )
    expect(screen.getByText('Contexto')).toBeInTheDocument()
  })
})
