import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

function mockFetchOnce(response: Partial<Response> & { json?: () => unknown }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
    ...response,
  } as Response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api', () => {
  it('encodes special characters in path query params', async () => {
    const fetchMock = mockFetchOnce({ json: async () => ({ species: [], study_start: null, study_end: null }) })

    await api.inspectDir('C:/Users/María Perez/datos & fotos')

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(
      '/api/fs/inspect?path=C%3A%2FUsers%2FMar%C3%ADa%20Perez%2Fdatos%20%26%20fotos',
    )
  })

  it('sends POST requests with a JSON body and content-type header', async () => {
    const fetchMock = mockFetchOnce({ json: async () => ({ ok: true, removed: ['m1'] }) })

    await api.rejectBurst('media-123')

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/reject')
    expect(options).toMatchObject({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    expect(JSON.parse(options.body as string)).toEqual({ mediaId: 'media-123' })
  })

  it('sends PUT requests with a JSON body', async () => {
    const fetchMock = mockFetchOnce({ json: async () => ({ success: true, confirmed: 2 }) })

    await api.updateDecisions('lynx', ['k1', 'k2'])

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/species/lynx/decisions')
    expect(options.method).toBe('PUT')
    expect(JSON.parse(options.body as string)).toEqual({ confirmed_keys: ['k1', 'k2'] })
  })

  it('throws with the response body text when the request fails', async () => {
    mockFetchOnce({ ok: false, status: 400, text: async () => 'No hay sesión activa.' })

    await expect(api.getResults()).rejects.toThrow('No hay sesión activa.')
  })

  it('falls back to statusText when reading the error body fails', async () => {
    mockFetchOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: async () => {
        throw new Error('body already consumed')
      },
    })

    await expect(api.getResults()).rejects.toThrow('Internal Server Error')
  })
})
