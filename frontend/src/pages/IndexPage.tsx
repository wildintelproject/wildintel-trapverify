import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import type { SpeciesStats } from '../types'

function Spinner() {
  return <div className="w-8 h-8 border-2 border-zinc-600 border-t-blue-500 rounded-full animate-spin" />
}

export default function IndexPage() {
  const navigate = useNavigate()
  const { t, i18n } = useTranslation()
  const imgError = i18n.language.startsWith('es') ? '/img-error-es.svg' : '/img-error-en.svg'
  const [species, setSpecies] = useState<SpeciesStats[]>([])
  const [sessionInfo, setSessionInfo] = useState<{
    start: string; end: string
    occasion_days: number; gap_seconds: number; min_score: number
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.getSpecies(), api.getState()])
      .then(([sp, state]) => {
        setSpecies(sp)
        if (state.config) setSessionInfo({
          start: state.config.study_start,
          end: state.config.study_end,
          occasion_days: state.config.occasion_days,
          gap_seconds: state.config.gap_seconds,
          min_score: state.config.min_score,
        })
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="flex justify-center items-center" style={{ minHeight: 300 }}>
      <Spinner />
    </div>
  )

  if (error) return (
    <div className="max-w-screen-xl mx-auto px-4 py-4">
      <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300">
        {error}
      </div>
    </div>
  )

  const totalCombos   = species.reduce((s, sp) => s + sp.n_total_combos, 0)
  const totalResolved = species.reduce((s, sp) => s + sp.n_resolved, 0)
  const totalDetected = species.reduce((s, sp) => s + sp.n_confirmed_combos, 0)
  const overallPct    = totalCombos > 0 ? Math.round(totalResolved / totalCombos * 100) : 0

  return (
    <div className="max-w-screen-xl mx-auto px-4 py-4">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-baseline gap-3">
          <h2 className="text-2xl font-semibold mb-0">{t('index.title')}</h2>
          <span className="text-zinc-500 dark:text-zinc-400 text-sm">
            {t('index.periods_reviewed', { resolved: totalResolved, total: totalCombos })}
            {' · '}
            <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
              {t('index.confirmed', { n: totalDetected })}
            </span>
            {' · '}
            <span className={overallPct === 100
              ? 'text-emerald-600 dark:text-emerald-400 font-bold'
              : 'text-amber-500 dark:text-amber-400 font-semibold'}>
              {overallPct}%
            </span>
          </span>
        </div>
        <div className="flex gap-2">
          <button
            className="px-4 py-1.5 text-sm rounded transition-colors bg-zinc-700 text-white hover:bg-zinc-600 flex items-center gap-1.5"
            onClick={() => navigate(-1)}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M10 3L5 8l5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            {t('gallery.back')}
          </button>
          <button
            className={`px-4 py-1.5 text-sm rounded transition-colors ${
              overallPct === 100
                ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                : 'bg-zinc-700 text-zinc-400 cursor-not-allowed opacity-60'
            }`}
            disabled={overallPct < 100}
            onClick={() => navigate('/results')}
            title={overallPct < 100
              ? `${t('index.see_results')} (${overallPct}%)`
              : t('index.see_results')}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true" style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }}>
              <path d="M9 17H7A5 5 0 0 1 7 7h2M15 7h2a5 5 0 0 1 0 10h-2M8 12h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            {t('index.see_results')}
          </button>
        </div>
      </div>

      <p className="text-zinc-500 dark:text-zinc-400 mb-2 text-sm">{t('index.subtitle')}</p>
      {sessionInfo && (
        <div className="flex items-start gap-2.5 px-3.5 py-2.5 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 text-sm mb-3">
          <svg className="flex-shrink-0 mt-0.5" width="15" height="15" viewBox="0 0 15 15" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M7.5 1C3.91 1 1 3.91 1 7.5S3.91 14 7.5 14 14 11.09 14 7.5 11.09 1 7.5 1zm.75 10.5h-1.5V7h1.5v4.5zm0-6h-1.5V4h1.5v1.5z" fill="currentColor"/>
          </svg>
          <span className="flex flex-wrap gap-x-3 gap-y-0.5">
            <span>{t('index.date_range', { start: sessionInfo.start, end: sessionInfo.end })}</span>
            <span className="text-blue-400 dark:text-blue-600">·</span>
            <span>{t('index.param_occasion', { n: sessionInfo.occasion_days })}</span>
            <span className="text-blue-400 dark:text-blue-600">·</span>
            <span>{t('index.param_gap', { n: sessionInfo.gap_seconds })}</span>
            <span className="text-blue-400 dark:text-blue-600">·</span>
            <span>{t('index.param_score', { n: sessionInfo.min_score })}</span>
          </span>
        </div>
      )}

      <div className="w-full bg-zinc-200 dark:bg-zinc-700 rounded-full mb-4" style={{ height: 8 }}>
        <div
          className="bg-emerald-500 rounded-full h-full transition-all"
          style={{ width: `${overallPct}%` }}
          role="progressbar"
          aria-valuenow={overallPct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {species.map((sp) => {
          const pct  = sp.n_total_combos > 0 ? Math.round(sp.n_resolved / sp.n_total_combos * 100) : 0
          const done = sp.n_resolved >= sp.n_total_combos

          return (
            <Link
              key={sp.species_safe}
              to={`/gallery/${sp.species_safe}`}
              className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 no-underline text-zinc-900 dark:text-zinc-100 block transition-transform hover:-translate-y-0.5"
            >
              {sp.thumbnails?.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 2, height: 80 }}>
                  {sp.thumbnails.slice(0, 4).map((src, i) => (
                    <img key={i} src={src} alt="" loading="lazy"
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      onError={(e) => {
                        e.currentTarget.onerror = null
                        e.currentTarget.src = imgError
                        e.currentTarget.style.objectFit = 'contain'
                        e.currentTarget.style.background = '#18181b'
                      }} />
                  ))}
                  {Array.from({ length: Math.max(0, 4 - sp.thumbnails.length) }).map((_, i) => (
                    <div key={`empty-${i}`} style={{ background: '#222' }} />
                  ))}
                </div>
              )}
              <div className="p-4">
                <h5 className="italic font-medium text-base mb-1">{sp.species_name}</h5>
                <p className="text-zinc-500 dark:text-zinc-400 text-xs mb-1">
                  {t('index.confirmed_periods', { n: sp.n_confirmed_combos })}
                </p>
                <p className="text-zinc-500 dark:text-zinc-400 text-xs mb-2">
                  {t('index.reviewed_periods', { resolved: sp.n_resolved, total: sp.n_total_combos, pct })}
                </p>
                <div className="w-full bg-zinc-200 dark:bg-zinc-700 rounded-full mb-3" style={{ height: 6 }}>
                  <div
                    className={`h-full rounded-full ${done ? 'bg-emerald-500' : 'bg-blue-500'}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${
                  done ? 'bg-emerald-600 text-white' : 'bg-zinc-600 text-zinc-200'
                }`}>
                  {done ? t('index.complete') : t('index.round', { n: sp.current_iteration })}
                </span>
              </div>
            </Link>
          )
        })}
      </div>

      {species.length === 0 && (
        <div className="mt-3 px-4 py-3 rounded-lg bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300">
          {t('index.no_species')}
        </div>
      )}
    </div>
  )
}
