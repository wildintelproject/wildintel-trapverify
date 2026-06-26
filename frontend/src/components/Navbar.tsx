import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

interface Props { ready: boolean }

const LANGS = [
  { code: 'es', flag: '🇪🇸', label: 'Español' },
  { code: 'en', flag: '🇬🇧', label: 'English' },
]

export default function Navbar({ ready: _ready }: Props) {
  const { t, i18n } = useTranslation()
  const [dark, setDark] = useState(true)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    document.documentElement.setAttribute('data-bs-theme', dark ? 'dark' : 'light')
  }, [dark])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const current = LANGS.find(l => l.code === i18n.resolvedLanguage) ?? LANGS[0]

  return (
    <>
    <nav className="navbar navbar-expand-lg border-bottom" data-bs-theme={dark ? 'dark' : 'light'}>
      <div className="container-fluid">
        <Link className="navbar-brand fw-bold" to="/">
          🦌 {t('nav.brand')}
        </Link>
        <div className="ms-auto d-flex align-items-center gap-2">

          {/* Selector de idioma */}
          <div ref={ref} style={{ position: 'relative' }}>
            <button
              className="btn btn-sm btn-outline-secondary"
              onClick={() => setOpen(o => !o)}
            >
              {current.flag} {current.label}
            </button>
            {open && (
              <ul
                className="dropdown-menu show"
                style={{ position: 'absolute', right: 0, top: '110%', minWidth: 130 }}
              >
                {LANGS.map(l => (
                  <li key={l.code}>
                    <button
                      className={`dropdown-item ${i18n.resolvedLanguage === l.code ? 'active' : ''}`}
                      onClick={() => { i18n.changeLanguage(l.code); setOpen(false) }}
                    >
                      {l.flag} {l.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Ayuda */}
          <a
            className="btn btn-sm btn-outline-secondary"
            href="/docs/"
            target="_blank"
            rel="noopener noreferrer"
          >
            ? {t('help.open')}
          </a>

          {/* Tema */}
          <button
            className="btn btn-sm btn-outline-secondary"
            title={dark ? t('nav.theme_light') : t('nav.theme_dark')}
            onClick={() => setDark(d => !d)}
          >
            {dark ? '☀️' : '🌙'}
          </button>
        </div>
      </div>
    </nav>

    </>
  )
}
