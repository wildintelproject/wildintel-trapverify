import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

interface Props { ready: boolean; version: string | null }

const LANGS = [
  { code: 'es', flag: '🇪🇸', label: 'Español' },
  { code: 'en', flag: '🇬🇧', label: 'English' },
  { code: 'de', flag: '🇩🇪', label: 'Deutsch' },
  { code: 'pl', flag: '🇵🇱', label: 'Polski' },
]

const btnOutline = 'px-3 py-1.5 text-sm border border-zinc-300 dark:border-zinc-600 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 transition-colors'

export default function Navbar({ ready: _ready, version }: Props) {
  const { t, i18n } = useTranslation()
  const [dark, setDark] = useState(true)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
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
    <nav className="border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
      <div className="max-w-screen-2xl mx-auto px-4 h-14 flex items-center">
        <Link className="font-bold text-zinc-900 dark:text-zinc-100 text-base no-underline" to="/">
          🦌 {t('nav.brand')}
        </Link>
        {version && (
          <span className="ml-2 text-xs text-zinc-400 dark:text-zinc-500 font-mono">
            v{version}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">

          {/* Language selector */}
          <div ref={ref} className="relative">
            <button className={btnOutline} onClick={() => setOpen(o => !o)}>
              {current.flag} {current.label}
            </button>
            {open && (
              <ul className="absolute right-0 top-[110%] min-w-32 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-lg z-50 py-1 list-none m-0 p-0">
                {LANGS.map(l => (
                  <li key={l.code}>
                    <button
                      className={`w-full text-left px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors ${
                        i18n.resolvedLanguage === l.code
                          ? 'text-blue-600 dark:text-blue-400 font-medium'
                          : 'text-zinc-700 dark:text-zinc-300'
                      }`}
                      onClick={() => { i18n.changeLanguage(l.code); setOpen(false) }}
                    >
                      {l.flag} {l.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Help */}
          <a
            className={`${btnOutline} no-underline`}
            href="https://wildintelproject.github.io/wildintel-trapverify/"
            target="_blank"
            rel="noopener noreferrer"
          >
            ? {t('help.open')}
          </a>

          {/* Theme toggle */}
          <button
            className={btnOutline}
            title={dark ? t('nav.theme_light') : t('nav.theme_dark')}
            onClick={() => setDark(d => !d)}
          >
            {dark ? '☀️' : '🌙'}
          </button>
        </div>
      </div>
    </nav>
  )
}
