import { describe, expect, it } from 'vitest'
import { crossButtonState, crossConfirmedHere } from './crossState'

const frames = [{ mediaId: 'm1' }, { mediaId: 'm2' }]

describe('crossButtonState', () => {
  it('is blue only when confirmed from a photo of this detection event', () => {
    expect(crossButtonState({ status: 'cross', mediaID: 'm2' }, frames)).toBe('cross')
  })
  it('is "elsewhere" when confirmed from another detection event of the occasion', () => {
    // round 2 of fallow deer: red deer was confirmed from the round-1 photo
    expect(crossButtonState({ status: 'cross', mediaID: 'm9' }, frames)).toBe('elsewhere')
  })
  it('keeps own-review confirmations and empty states', () => {
    expect(crossButtonState({ status: 'confirmed' }, frames)).toBe('confirmed')
    expect(crossButtonState({ status: 'none' }, frames)).toBe('none')
    expect(crossButtonState(undefined, frames)).toBe('none')
  })
  it('is grey when confirmed from this photo while another species was reviewed', () => {
    // multi-classifier CamtrapDP: the same photo is a candidate of fallow deer and of rabbit;
    // hare was confirmed from it in the fallow-deer review, now rabbit is being reviewed
    const entry = { status: 'cross', mediaID: 'm1', source: 'Dama dama' }
    expect(crossButtonState(entry, frames, 'Oryctolagus cuniculus')).toBe('elsewhere')
    expect(crossButtonState(entry, frames, 'Dama dama')).toBe('cross')
  })
  it('falls back to the photo alone when the source species is unknown', () => {
    expect(crossButtonState({ status: 'cross', mediaID: 'm1' }, frames, 'Oryctolagus cuniculus')).toBe('cross')
    expect(crossButtonState({ status: 'cross', mediaID: 'm1', source: '' }, frames, 'Dama dama')).toBe('cross')
  })
})

describe('crossConfirmedHere', () => {
  it('lists only the species confirmed from this event in the current review', () => {
    const entries = [
      { scientificName: 'Lepus granatensis', status: 'cross', mediaID: 'm1', source: 'Dama dama' },
      { scientificName: 'Sus scrofa', status: 'cross', mediaID: 'm2', source: 'Oryctolagus cuniculus' },
      { scientificName: 'Cervus elaphus', status: 'cross', mediaID: 'm9', source: 'Oryctolagus cuniculus' },
      { scientificName: 'Bos taurus', status: 'confirmed' },
    ]
    expect(crossConfirmedHere(entries, frames, 'Oryctolagus cuniculus')).toEqual(['Sus scrofa'])
    expect(crossConfirmedHere(undefined, frames, 'Oryctolagus cuniculus')).toEqual([])
  })
})
