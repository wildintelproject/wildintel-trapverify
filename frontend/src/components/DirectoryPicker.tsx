import { useEffect, useRef, useState } from 'react'

interface DirEntry {
  name: string
  path: string
}

interface BrowseResult {
  current: string
  parent: string | null
  dirs: DirEntry[]
}

interface Props {
  onSelect: (path: string) => void
  onClose: () => void
  initialPath?: string
}

export default function DirectoryPicker({ onSelect, onClose, initialPath }: Props) {
  const [data, setData] = useState<BrowseResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [manualPath, setManualPath] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  async function browse(path?: string) {
    setLoading(true)
    setError(null)
    const qs = path ? `?path=${encodeURIComponent(path)}` : ''
    const url = `/api/fs/browse${qs}`
    try {
      const r = await fetch(url)
      const text = await r.text()
      if (!r.ok) {
        let detail = r.statusText
        try { detail = JSON.parse(text).detail ?? r.statusText } catch { /* */ }
        throw new Error(`HTTP ${r.status} — ${detail}\n(URL: ${url})`)
      }
      const result: BrowseResult = JSON.parse(text)
      setData(result)
      setManualPath(result.current)
    } catch (e) {
      // Si la ruta inicial falla, reintentar desde home
      if (path !== undefined) {
        await browse(undefined)
        return
      }
      setError(e instanceof Error ? e.message : 'Error al leer el directorio')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    browse(initialPath)
  }, [])

  function handleManualGo(e: React.FormEvent) {
    e.preventDefault()
    browse(manualPath)
  }

  // Breadcrumbs from current path
  const parts = data
    ? data.current.split('/').filter(Boolean).map((part, i, arr) => ({
        label: part || '/',
        path: '/' + arr.slice(0, i + 1).join('/'),
      }))
    : []

  return (
    <div
      className="position-fixed top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center"
      style={{ background: 'rgba(0,0,0,.6)', zIndex: 1060 }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="bg-dark border border-secondary rounded-3 d-flex flex-column"
        style={{ width: 560, maxHeight: '80vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="d-flex align-items-center justify-content-between px-3 py-2 border-bottom border-secondary">
          <span className="fw-semibold">Seleccionar directorio</span>
          <button className="btn-close btn-close-white" onClick={onClose} />
        </div>

        {/* Manual path input */}
        <form onSubmit={handleManualGo} className="px-3 pt-2 pb-1 d-flex gap-2">
          <input
            ref={inputRef}
            className="form-control form-control-sm font-monospace bg-dark text-light border-secondary"
            value={manualPath}
            onChange={(e) => setManualPath(e.target.value)}
            placeholder="/ruta/del/directorio"
            spellCheck={false}
          />
          <button type="submit" className="btn btn-sm btn-outline-secondary" disabled={loading}>
            Ir
          </button>
        </form>

        {/* Breadcrumbs */}
        {data && (
          <nav className="px-3 pb-1" aria-label="breadcrumb">
            <ol className="breadcrumb mb-0" style={{ fontSize: 12 }}>
              <li className="breadcrumb-item">
                <button
                  className="btn btn-link btn-sm p-0 text-info"
                  style={{ fontSize: 12 }}
                  onClick={() => browse('/')}
                >
                  /
                </button>
              </li>
              {parts.map((part, i) => (
                <li
                  key={part.path}
                  className={`breadcrumb-item ${i === parts.length - 1 ? 'active text-light' : ''}`}
                >
                  {i < parts.length - 1 ? (
                    <button
                      className="btn btn-link btn-sm p-0 text-info"
                      style={{ fontSize: 12 }}
                      onClick={() => browse(part.path)}
                    >
                      {part.label}
                    </button>
                  ) : (
                    part.label
                  )}
                </li>
              ))}
            </ol>
          </nav>
        )}

        {/* Directory listing */}
        <div className="overflow-auto flex-grow-1 px-2 pb-2" style={{ minHeight: 0 }}>
          {loading && (
            <div className="text-center py-4 text-muted">
              <div className="spinner-border spinner-border-sm me-2" />
              Cargando…
            </div>
          )}

          {error && (
            <div className="alert alert-danger alert-sm py-2 mx-1 mt-2">{error}</div>
          )}

          {!loading && !error && data && (
            <ul className="list-group list-group-flush">
              {/* Parent directory */}
              {data.parent && (
                <li
                  className="list-group-item list-group-item-action bg-dark border-secondary text-secondary d-flex align-items-center gap-2 py-1 px-2"
                  style={{ cursor: 'pointer', fontSize: 14 }}
                  onClick={() => browse(data.parent!)}
                >
                  <span style={{ fontSize: 16 }}>↩</span>
                  <span className="font-monospace">..</span>
                </li>
              )}

              {data.dirs.length === 0 && (
                <li className="list-group-item bg-dark border-0 text-muted py-1 px-2" style={{ fontSize: 13 }}>
                  Sin subdirectorios
                </li>
              )}

              {data.dirs.map((dir) => (
                <li
                  key={dir.path}
                  className="list-group-item list-group-item-action bg-dark border-secondary text-light d-flex align-items-center gap-2 py-1 px-2"
                  style={{ cursor: 'pointer', fontSize: 14 }}
                  onDoubleClick={() => browse(dir.path)}
                  onClick={() => setManualPath(dir.path)}
                >
                  <span className="text-warning" style={{ fontSize: 15 }}>📁</span>
                  <span className="font-monospace text-truncate">{dir.name}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div className="px-3 py-2 border-top border-secondary d-flex align-items-center justify-content-between gap-2">
          <span className="font-monospace text-muted text-truncate small" style={{ maxWidth: 340 }}>
            {manualPath || '—'}
          </span>
          <div className="d-flex gap-2 flex-shrink-0">
            <button className="btn btn-sm btn-outline-secondary" onClick={onClose}>
              Cancelar
            </button>
            <button
              className="btn btn-sm btn-primary"
              onClick={() => { onSelect(manualPath); onClose() }}
              disabled={!manualPath}
            >
              Seleccionar
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
