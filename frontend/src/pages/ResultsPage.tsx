import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'

interface SpeciesRow {
  species: string
  confirmed: number
  rejected: number
  unverified: number
}

interface Results {
  session_dir: string
  output_dir: string
  total: number
  confirmed: number
  rejected: number
  unverified: number
  by_species: SpeciesRow[]
  seq_total: number
  seq_confirmed: number
  seq_rejected: number
  seq_unverified: number
  by_species_seqs: SpeciesRow[]
}

export default function ResultsPage() {
  const { t } = useTranslation()
  const [results, setResults] = useState<Results | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [opening, setOpening] = useState(false)

  useEffect(() => {
    api.getResults().then(setResults).catch((e: Error) => setError(e.message))
  }, [])

  async function handleOpenFolder() {
    setOpening(true)
    try { await api.openFolder() } catch { /* ignora si no hay explorador */ }
    finally { setOpening(false) }
  }

  function handleCopy(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  if (error) return (
    <div className="container py-4">
      <div className="alert alert-danger">{error}</div>
    </div>
  )

  if (!results) return (
    <div className="d-flex justify-content-center align-items-center" style={{ minHeight: 300 }}>
      <div className="spinner-border text-primary" role="status" />
    </div>
  )

  const pctConfirmed  = results.total > 0 ? Math.round(results.confirmed  / results.total * 100) : 0
  const pctRejected   = results.total > 0 ? Math.round(results.rejected   / results.total * 100) : 0
  const pctUnverified = results.total > 0 ? Math.round(results.unverified / results.total * 100) : 0

  const sPctConfirmed  = results.seq_total > 0 ? Math.round(results.seq_confirmed  / results.seq_total * 100) : 0
  const sPctRejected   = results.seq_total > 0 ? Math.round(results.seq_rejected   / results.seq_total * 100) : 0
  const sPctUnverified = results.seq_total > 0 ? Math.round(results.seq_unverified / results.seq_total * 100) : 0

  function StatsCards({ confirmed, rejected, unverified, total }: { confirmed: number; rejected: number; unverified: number; total: number }) {
    const pC = total > 0 ? Math.round(confirmed  / total * 100) : 0
    const pR = total > 0 ? Math.round(rejected   / total * 100) : 0
    const pU = total > 0 ? Math.round(unverified / total * 100) : 0
    return (
      <>
        <div className="row g-3 mb-3">
          <div className="col-md-4">
            <div className="card text-center border-success">
              <div className="card-body">
                <div className="fs-1 fw-bold text-success">{confirmed}</div>
                <div className="text-body-secondary">{t('results.confirmed')}</div>
                <div className="text-success small">{t('results.pct_total', { pct: pC })}</div>
              </div>
            </div>
          </div>
          <div className="col-md-4">
            <div className="card text-center border-danger">
              <div className="card-body">
                <div className="fs-1 fw-bold text-danger">{rejected}</div>
                <div className="text-body-secondary">{t('results.rejected')}</div>
                <div className="text-danger small">{t('results.pct_total', { pct: pR })}</div>
              </div>
            </div>
          </div>
          <div className="col-md-4">
            <div className="card text-center border-secondary">
              <div className="card-body">
                <div className="fs-1 fw-bold text-secondary">{unverified}</div>
                <div className="text-body-secondary">{t('results.unverified')}</div>
                <div className="text-secondary small">{t('results.pct_total', { pct: pU })}</div>
              </div>
            </div>
          </div>
        </div>
        <div className="progress mb-4" style={{ height: 12 }}>
          <div className="progress-bar bg-success" style={{ width: `${pC}%` }} />
          <div className="progress-bar bg-danger"  style={{ width: `${pR}%` }} />
          <div className="progress-bar bg-secondary" style={{ width: `${pU}%` }} />
        </div>
      </>
    )
  }

  function BreakdownTable({ rows }: { rows: SpeciesRow[] }) {
    return (
      <div className="table-responsive">
        <table className="table table-hover table-sm mb-0">
          <thead>
            <tr>
              <th>{t('results.col_species')}</th>
              <th className="text-end text-success">{t('results.col_confirmed')}</th>
              <th className="text-end text-danger">{t('results.col_rejected')}</th>
              <th className="text-end text-body-secondary">{t('results.col_unverified')}</th>
              <th className="text-end">{t('results.col_total')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const tot = row.confirmed + row.rejected + row.unverified
              return (
                <tr key={row.species}>
                  <td className="font-monospace">{row.species}</td>
                  <td className="text-end text-success">{row.confirmed}</td>
                  <td className="text-end text-danger">{row.rejected}</td>
                  <td className="text-end text-body-secondary">{row.unverified}</td>
                  <td className="text-end">{tot}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div className="container py-4" style={{ maxWidth: 860 }}>
      <h2 className="mb-4">{t('results.title')}</h2>
      <p className="text-body-secondary mb-4"
        dangerouslySetInnerHTML={{ __html: t('results.subtitle') }} />

      <div className="card mb-4">
        <div className="card-header">{t('results.output_header')}</div>
        <div className="card-body">
          <div className="input-group">
            <input
              className="form-control font-monospace"
              readOnly
              value={results.output_dir}
            />
            <button className="btn btn-outline-secondary" onClick={() => handleCopy(results.output_dir)}>
              {copied ? t('results.copied') : t('results.copy')}
            </button>
            <button className="btn btn-outline-primary" onClick={handleOpenFolder} disabled={opening}>
              {opening
                ? <span className="spinner-border spinner-border-sm" role="status" />
                : t('results.open_folder')}
            </button>
          </div>
          <div className="form-text text-body-secondary"
            dangerouslySetInnerHTML={{ __html: t('results.output_hint') }} />
        </div>
      </div>

      <h5 className="mb-3">{t('results.periods_title')}</h5>
      <StatsCards
        confirmed={results.confirmed}
        rejected={results.rejected}
        unverified={results.unverified}
        total={results.total}
      />
      {results.by_species.length > 0 && (
        <div className="card mb-5">
          <div className="card-header">{t('results.by_species')}</div>
          <BreakdownTable rows={results.by_species} />
        </div>
      )}

      <h5 className="mb-3">{t('results.seq_title')}</h5>
      <StatsCards
        confirmed={results.seq_confirmed}
        rejected={results.seq_rejected}
        unverified={results.seq_unverified}
        total={results.seq_total}
      />
      {results.by_species_seqs.length > 0 && (
        <div className="card mb-4">
          <div className="card-header">{t('results.by_species')}</div>
          <BreakdownTable rows={results.by_species_seqs} />
        </div>
      )}
    </div>
  )
}
