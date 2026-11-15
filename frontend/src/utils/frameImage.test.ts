import { describe, expect, it } from 'vitest'
import { frameSrc } from './frameImage'

const frame = { img: '/api/image/m1', obsId: 'obs 1', boxes: 2 }

describe('frameSrc', () => {
  it('asks for the boxes of the observation being verified when they are on', () => {
    expect(frameSrc(frame, true)).toBe('/api/image/m1?boxes=true&obs=obs%201')
  })

  it('returns the plain image when boxes are off', () => {
    expect(frameSrc(frame, false)).toBe('/api/image/m1')
  })

  it('returns the plain image when the frame has no box', () => {
    expect(frameSrc({ ...frame, boxes: 0 }, true)).toBe('/api/image/m1')
    expect(frameSrc({ img: '/api/image/m1', obsId: 'o' }, true)).toBe('/api/image/m1')
  })

  it('does not touch remote images, which the app cannot draw on', () => {
    const remote = { img: '/api/proxy-image?url=https%3A%2F%2Fx%2Fa.jpg', obsId: 'o', boxes: 1 }
    expect(frameSrc(remote, true)).toBe(remote.img)
  })

  it('appends to an existing query string', () => {
    expect(frameSrc({ img: '/api/image/m1?v=3', obsId: 'o', boxes: 1 }, true)).toBe('/api/image/m1?v=3&boxes=true&obs=o')
  })
})
