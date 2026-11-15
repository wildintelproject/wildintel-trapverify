import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
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

  it('offers an Unsure button that reports the decision', async () => {
    const onDecide = vi.fn()
    render(
      <EventCard
        event={makeEvent()}
        decision={null}
        needsDecision={false}
        onDecide={onDecide}
        onOpenLightbox={vi.fn()}
        eventIdx={0}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /^\?/ }))
    expect(onDecide).toHaveBeenCalledWith('site1|1', 'obs-1', 'unsure')
  })

  it('highlights unsure events and can hide the Unsure button', () => {
    const { container, rerender } = render(
      <EventCard
        event={makeEvent()}
        decision="unsure"
        needsDecision={false}
        onDecide={vi.fn()}
        onOpenLightbox={vi.fn()}
        eventIdx={0}
      />,
    )
    expect(container.firstChild).toHaveClass('border-amber-500')
    expect(screen.getByRole('button', { name: /^\?/ })).toHaveClass('bg-amber-600')
    rerender(
      <EventCard
        event={makeEvent()}
        decision={null}
        needsDecision={false}
        onDecide={vi.fn()}
        onOpenLightbox={vi.fn()}
        eventIdx={0}
        allowUnsure={false}
      />,
    )
    expect(screen.queryByRole('button', { name: /^\?/ })).toBeNull()
  })

  it('shows the optional actual-species field only for rejected events when recording is on', async () => {
    const onCorrect = vi.fn()
    const props = { event: makeEvent(), needsDecision: false, onDecide: vi.fn(), onOpenLightbox: vi.fn(), eventIdx: 0 }
    const { rerender } = render(<EventCard {...props} decision="rejected" onCorrect={onCorrect} />)
    expect(screen.queryByRole('combobox')).toBeNull()           // option off by default
    rerender(<EventCard {...props} decision="rejected" recordCorrection onCorrect={onCorrect} />)
    await userEvent.type(screen.getByRole('combobox'), 'D')
    expect(onCorrect).toHaveBeenCalledWith('site1|1', 'D')
    rerender(<EventCard {...props} decision="confirmed" recordCorrection onCorrect={onCorrect} />)
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('asks the server to draw the box of the observation only when boxes are on', () => {
    const event = makeEvent({
      frames: [{ obsId: 'obs-1', mediaId: 'media-1', img: '/api/image/media-1', ts: '2026-01-01 10:00', prob: 0.9, boxes: 1 }],
    })
    const props = { event, decision: null, needsDecision: false, onDecide: vi.fn(), onOpenLightbox: vi.fn(), eventIdx: 0 }
    const { container, rerender } = render(<EventCard {...props} />)
    expect(container.querySelector('img')).toHaveAttribute('src', '/api/image/media-1')
    rerender(<EventCard {...props} showBoxes />)
    expect(container.querySelector('img')).toHaveAttribute('src', '/api/image/media-1?boxes=true&obs=obs-1')
  })

  describe('preloading the neighbouring frames', () => {
    afterEach(() => { vi.unstubAllGlobals() })

    const threeFrames = makeEvent({
      frames: ['a', 'b', 'c'].map((id, k) => ({
        obsId: `obs-${id}`, mediaId: `media-${id}`, img: `/api/image/media-${id}`, ts: `2026-01-01 10:00:0${k}`, prob: 0.9, boxes: 1,
      })),
    })

    function renderCard(showBoxes = false) {
      const loaded: string[] = []
      class FakeImage { set src(v: string) { loaded.push(v) } }
      vi.stubGlobal('Image', FakeImage)
      const { container } = render(
        <EventCard event={threeFrames} decision={null} needsDecision={false} onDecide={vi.fn()}
          onOpenLightbox={vi.fn()} eventIdx={0} showBoxes={showBoxes} />,
      )
      return { loaded, card: container.firstChild as HTMLElement }
    }

    it('downloads nothing until the pointer is over the card', () => {
      expect(renderCard().loaded).toEqual([])
    })

    it('preloads the previous and next frames once the pointer enters', () => {
      const { loaded, card } = renderCard()
      fireEvent.pointerEnter(card)
      expect(loaded.sort()).toEqual(['/api/image/media-b', '/api/image/media-c'])    // frame 0 -> next (b) and wraps to previous (c)
    })

    it('preloads the same URLs the card will show, boxes included', () => {
      const { loaded, card } = renderCard(true)
      fireEvent.pointerEnter(card)
      expect(loaded.every((u) => u.includes('boxes=true&obs='))).toBe(true)
    })
  })

  describe('one image per card', () => {
    const threeFrames = makeEvent({
      frames: ['a', 'b', 'c'].map((id, k) => ({
        obsId: `obs-${id}`, mediaId: `media-${id}`, img: `/api/image/media-${id}`, ts: `2026-01-01 10:00:0${k}`, prob: 0.5 + k / 10,
      })),
    })
    const renderThree = () => render(
      <EventCard event={threeFrames} decision={null} needsDecision={false} onDecide={vi.fn()} onOpenLightbox={vi.fn()} eventIdx={0} />,
    )

    it('mounts a single image, the most confident frame, however many frames the event has', () => {
      const { container } = renderThree()
      const imgs = container.querySelectorAll('img')
      expect(imgs).toHaveLength(1)
      expect(imgs[0]).toHaveAttribute('src', '/api/image/media-c')
    })

    it('steps through the frames with the arrows, wrapping around', async () => {
      const { container } = renderThree()
      const next = screen.getByRole('button', { name: /siguiente/i })
      await userEvent.click(next)
      expect(container.querySelector('img')).toHaveAttribute('src', '/api/image/media-a')    // wraps from the last
      await userEvent.click(screen.getByRole('button', { name: /anterior/i }))
      expect(container.querySelector('img')).toHaveAttribute('src', '/api/image/media-c')
      expect(container.querySelectorAll('img')).toHaveLength(1)
    })

    it('has no arrows for a single frame', () => {
      render(<EventCard event={makeEvent()} decision={null} needsDecision={false} onDecide={vi.fn()} onOpenLightbox={vi.fn()} eventIdx={0} />)
      expect(screen.queryByRole('button', { name: /siguiente/i })).toBeNull()
    })

    it('opens the large view at the frame being looked at', async () => {
      const onOpen = vi.fn()
      const { container } = render(
        <EventCard event={threeFrames} decision={null} needsDecision={false} onDecide={vi.fn()} onOpenLightbox={onOpen} eventIdx={4} />,
      )
      await userEvent.click(screen.getByRole('button', { name: /siguiente/i }))
      await userEvent.click(container.querySelector('img')!)
      expect(onOpen).toHaveBeenCalledWith(4, 0)
    })
  })
})
