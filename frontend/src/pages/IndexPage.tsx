import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import type { SpeciesStats } from '../types'

export default function IndexPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [species, setSpecies] = useState<SpeciesStats[]>([])
  const [dateRange, setDateRange] = useState<{ start: string; end: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.getSpecies(), api.getState()])
      .then(([sp, state]) => {
        setSpecies(sp)
        if (state.config) setDateRange({ start: state.config.study_start, end: state.config.study_end })
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="d-flex justify-content-center align-items-center" style={{ minHeight: 300 }}>
      <div className="spinner-border text-primary" role="status" />
    </div>
  )

  if (error) return (
    <div className="container py-4">
      <div className="alert alert-danger">{error}</div>
    </div>
  )

  const totalCombos    = species.reduce((s, sp) => s + sp.n_total_combos, 0)
  const totalResolved  = species.reduce((s, sp) => s + sp.n_resolved, 0)
  const totalDetected  = species.reduce((s, sp) => s + sp.n_confirmed_combos, 0)
  const overallPct     = totalCombos > 0 ? Math.round(totalResolved / totalCombos * 100) : 0

  return (
    <div className="container py-4">
      <div className="d-flex align-items-center justify-content-between mb-1">
        <div className="d-flex align-items-baseline gap-3">
          <h2 className="mb-0">{t('index.title')}</h2>
          <span className="text-body-secondary small">
            {t('index.periods_reviewed', { resolved: totalResolved, total: totalCombos })}
            &nbsp;·&nbsp;
            <span className="text-success fw-semibold">{t('index.confirmed', { n: totalDetected })}</span>
            &nbsp;·&nbsp;
            <span className={overallPct === 100 ? 'text-success fw-bold' : 'text-warning fw-semibold'}>
              {overallPct}%
            </span>
          </span>
        </div>
        <button
          className={`btn ${overallPct === 100 ? 'btn-success' : 'btn-secondary'}`}
          disabled={overallPct < 100}
          onClick={() => navigate('/results')}
          title={overallPct < 100
            ? `${t('index.see_results')} (${overallPct}%)`
            : t('index.see_results')}
        >
          {t('index.see_results')}
        </button>
      </div>

      <p className="text-body-secondary mb-3">
        {t('index.subtitle')}
        {dateRange && (
          <> {t('index.date_range', { start: dateRange.start, end: dateRange.end })}</>
        )}
      </p>

      <div className="progress mb-4" style={{ height: 8 }}>
        <div className="progress-bar bg-success" style={{ width: `${overallPct}%` }}
          role="progressbar" aria-valuenow={overallPct} aria-valuemin={0} aria-valuemax={100} />
      </div>

      <div className="row g-3">
        {species.map((sp) => {
          const pct  = sp.n_total_combos > 0 ? Math.round(sp.n_resolved / sp.n_total_combos * 100) : 0
          const done = sp.n_resolved >= sp.n_total_combos

          return (
            <div className="col-md-6 col-lg-4" key={sp.species_safe}>
              <Link
                to={`/gallery/${sp.species_safe}`}
                className="card h-100 text-decoration-none text-body border-secondary"
                style={{ transition: 'transform .15s', display: 'block' }}
                onMouseEnter={(e) => (e.currentTarget.style.transform = 'translateY(-3px)')}
                onMouseLeave={(e) => (e.currentTarget.style.transform = '')}
              >
                {sp.thumbnails?.length > 0 && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 2, height: 80 }}>
                    {sp.thumbnails.slice(0, 4).map((src, i) => (
                      <img key={i} src={src} alt="" loading="lazy"
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ))}
                    {Array.from({ length: Math.max(0, 4 - sp.thumbnails.length) }).map((_, i) => (
                      <div key={`empty-${i}`} style={{ background: '#222' }} />
                    ))}
                  </div>
                )}
                <div className="card-body">
                  <h5 className="card-title fst-italic">{sp.species_name}</h5>
                  <p className="text-muted small mb-1">
                    {t('index.confirmed_periods', { n: sp.n_confirmed_combos })}
                  </p>
                  <p className="text-muted small mb-2">
                    {t('index.reviewed_periods', { resolved: sp.n_resolved, total: sp.n_total_combos, pct })}
                  </p>
                  <div className="progress mb-3" style={{ height: 6 }}>
                    <div className={`progress-bar ${done ? 'bg-success' : 'bg-primary'}`}
                      style={{ width: `${pct}%` }} />
                  </div>
                  <span className={`badge ${done ? 'bg-success' : 'bg-secondary'}`}>
                    {done ? t('index.complete') : t('index.round', { n: sp.current_iteration })}
                  </span>
                </div>
              </Link>
            </div>
          )
        })}
      </div>

      {species.length === 0 && (
        <div className="alert alert-info mt-3">{t('index.no_species')}</div>
      )}
    </div>
  )
}
