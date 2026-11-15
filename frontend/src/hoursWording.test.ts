import { afterAll, describe, expect, it } from 'vitest'
import i18n from './i18n'

describe('sampling occasions in hours', () => {
  afterAll(() => i18n.changeLanguage('es'))

  it.each([
    ['en', 1, '1 hour'], ['en', 6, '6 hours'],
    ['es', 1, '1 hora'], ['es', 3, '3 horas'],
    ['de', 1, '1 Stunde'], ['de', 2, '2 Stunden'],
  ])('%s: %i -> %s', async (lng, n, text) => {
    await i18n.changeLanguage(lng)
    expect(i18n.t('index.subtitle_hours', { count: n, start: 'a', end: 'b' })).toContain(text)
    expect(i18n.t('gallery.intro_hint_hours', { count: n, gap: 60, minScore: 0.5, species: 'x' })).toContain(text)
  })

  it('uses the Polish plural forms', async () => {
    await i18n.changeLanguage('pl')
    const sub = (n: number) => i18n.t('index.subtitle_hours', { count: n, start: 'a', end: 'b' })
    expect(sub(1)).toContain('trwa') && expect(sub(1)).toContain('1 godzina')
    expect(sub(2)).toContain('2 godziny')
    expect(sub(5)).toContain('5 godzin')
    expect(sub(22)).toContain('22 godziny')
  })

  it('keeps the day wording for day sessions', async () => {
    await i18n.changeLanguage('en')
    expect(i18n.t('index.subtitle', { start: 'a', end: 'b', days: 5 })).toContain('5 days')
  })
})
