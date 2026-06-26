import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import DirectoryPicker from '../components/DirectoryPicker'
import type { WorkflowConfig } from '../types'

interface Props { onSetup: () => void; ready: boolean }

const DEFAULT: WorkflowConfig = {
  camtrap_dir: '',
  output_dir: '',
  target_species: [],
  study_start: '',
  study_end: '',
  occasion_days: 5,
  total_iterations: 100000,
  gap_seconds: 60,
  min_score: 0.5,
}

export default function SetupPage({ onSetup, ready }: Props) {
  const navigate = useNavigate()
  const { t } = useTranslation()

  const STEP_LABELS: string[] = t('setup.steps', { returnObjects: true }) as string[]

  const [step, setStep] = useState(-1)
  const [form, setForm] = useState<WorkflowConfig>(DEFAULT)
  const [availableSpecies, setAvailableSpecies] = useState<string[]>([])
  const [selectedSpecies, setSelectedSpecies] = useState<Set<string>>(new Set())
  const [dataRange, setDataRange] = useState<{ min: string; max: string } | null>(null)
  const [picker, setPicker] = useState<'camtrap_dir' | 'output_dir' | null>(null)
  const [inspecting, setInspecting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [stepError, setStepError] = useState<string | null>(null)

  useEffect(() => {
    api.getState().then((s) => {
      if (s.config) {
        setForm(s.config)
        setSelectedSpecies(new Set(s.config.target_species))
        setAvailableSpecies(s.config.target_species)
      } else if (s.default_output_dir) {
        setForm((f) => ({ ...f, output_dir: s.default_output_dir! }))
      }
    }).catch(() => {})
  }, [])

  function set<K extends keyof WorkflowConfig>(key: K, value: WorkflowConfig[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function handleDirSelected(path: string) {
    if (picker === 'camtrap_dir') {
      set('camtrap_dir', path)
      setPicker(null)
      setInspecting(true)
      try {
        const info = await api.inspectDir(path)
        setAvailableSpecies(info.species)
        setSelectedSpecies(new Set(info.species))
        if (info.study_start && info.study_end) {
          set('study_start', info.study_start)
          set('study_end', info.study_end)
          setDataRange({ min: info.study_start, max: info.study_end })
        }
      } catch { /* el usuario puede continuar manualmente */ }
      finally { setInspecting(false) }
    } else {
      set('output_dir', path)
      setPicker(null)
    }
  }

  function validate(currentDataRange: { min: string; max: string } | null): string | null {
    if (step === 0 && !form.camtrap_dir.trim()) return t('setup.err_no_dir')
    if (step === 1 && selectedSpecies.size === 0) return t('setup.err_no_species')
    if (step === 2) {
      if (!form.study_start) return t('setup.err_no_start')
      if (!form.study_end)   return t('setup.err_no_end')
      if (form.study_start > form.study_end) return t('setup.err_dates_order')
      if (currentDataRange) {
        if (form.study_start < currentDataRange.min)
          return t('setup.err_start_too_early', { date: form.study_start, min: currentDataRange.min })
        if (form.study_end > currentDataRange.max)
          return t('setup.err_end_too_late', { date: form.study_end, max: currentDataRange.max })
      }
    }
    return null
  }

  async function goNext() {
    let currentDataRange = dataRange
    if (step === 0 && !dataRange && form.camtrap_dir.trim()) {
      setInspecting(true)
      try {
        const info = await api.inspectDir(form.camtrap_dir)
        if (info.species.length) {
          setAvailableSpecies(info.species)
          setSelectedSpecies(new Set(info.species))
        }
        if (info.study_start && info.study_end) {
          set('study_start', info.study_start)
          set('study_end', info.study_end)
          currentDataRange = { min: info.study_start, max: info.study_end }
          setDataRange(currentDataRange)
        }
      } catch { /* el usuario puede continuar manualmente */ }
      finally { setInspecting(false) }
    }
    const err = validate(currentDataRange)
    if (err) { setStepError(err); return }
    setStepError(null)
    setStep((s) => s + 1)
  }

  function goBack() {
    setStepError(null)
    setStep((s) => s - 1)
  }

  async function handleSubmit() {
    setSubmitting(true)
    setStepError(null)
    try {
      await api.setup({ ...form, target_species: [...selectedSpecies] })
      onSetup()
      navigate('/species')
    } catch (e) {
      setStepError(e instanceof Error ? e.message : t('setup.err_unknown'))
    } finally {
      setSubmitting(false)
    }
  }

  function toggleSpecies(sp: string) {
    setSelectedSpecies((prev) => {
      const next = new Set(prev)
      next.has(sp) ? next.delete(sp) : next.add(sp)
      return next
    })
  }

  // ── Pantalla de bienvenida ─────────────────────────────────────────────────
  if (step === -1) return (
    <div className="d-flex flex-column align-items-center justify-content-center"
      style={{ minHeight: 'calc(100vh - 56px)' }}>
      <div className="text-center" style={{ maxWidth: 580 }}>
        <div className="mb-3" style={{ fontSize: '4rem' }}>🦌</div>
        <h1 className="fw-bold mb-3">{t('welcome.title')}</h1>
        <p className="text-body-secondary mb-4 fs-5">{t('welcome.subtitle')}</p>
        <ul className="list-unstyled text-start text-body-secondary mb-4 mx-auto" style={{ maxWidth: 420 }}>
          <li className="mb-2">📁 <strong className="text-body">{t('welcome.feat_dir')}</strong> — {t('welcome.feat_dir_desc')}</li>
          <li className="mb-2">🐾 <strong className="text-body">{t('welcome.feat_species')}</strong> — {t('welcome.feat_species_desc')}</li>
          <li className="mb-2">📅 <strong className="text-body">{t('welcome.feat_period')}</strong> — {t('welcome.feat_period_desc')}</li>
          <li className="mb-2">⚙️ <strong className="text-body">{t('welcome.feat_params')}</strong> — {t('welcome.feat_params_desc')}</li>
        </ul>
        <div className="d-flex flex-column align-items-center gap-3">
          {ready && (
            <button className="btn btn-success btn-lg px-5" onClick={() => navigate('/species')}>
              {t('welcome.continue_session')}
            </button>
          )}
          <button className="btn btn-primary btn-lg px-5" onClick={() => setStep(0)}>
            {ready ? t('welcome.new_session') : t('welcome.start')}
          </button>
        </div>
      </div>
    </div>
  )

  // ── Wizard ─────────────────────────────────────────────────────────────────
  return (
    <div className="container py-4" style={{ maxWidth: 700 }}>

      {/* Indicador de pasos */}
      <div className="d-flex align-items-center mb-5">
        {STEP_LABELS.map((label, i) => (
          <div key={i} className="d-flex align-items-center flex-grow-1">
            <div className="d-flex flex-column align-items-center" style={{ minWidth: 56 }}>
              <div
                className={`rounded-circle d-flex align-items-center justify-content-center fw-bold mb-1
                  ${i < step ? 'bg-success text-white' : i === step ? 'bg-primary text-white' : 'bg-secondary text-dark'}`}
                style={{ width: 36, height: 36, fontSize: 14 }}
              >
                {i < step ? '✓' : i + 1}
              </div>
              <small className={`text-nowrap ${i === step ? 'text-body' : 'text-body-secondary'}`}
                style={{ fontSize: 11 }}>{label}</small>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <div className={`flex-grow-1 border-top mb-3 mx-1 ${i < step ? 'border-success' : 'border-secondary'}`} />
            )}
          </div>
        ))}
      </div>

      {stepError && <div className="alert alert-danger py-2">{stepError}</div>}

      {/* ── PASO 0 ── */}
      {step === 0 && (
        <div>
          <h4 className="mb-1">{t('setup.step0_title')}</h4>
          <p className="text-body-secondary mb-4">{t('setup.step0_desc')}</p>

          <div className="mb-4">
            <label className="form-label fw-semibold">{t('setup.label_data_dir')}</label>
            <div className="input-group">
              <input className="form-control font-monospace"
                placeholder={t('setup.placeholder_data_dir')}
                value={form.camtrap_dir}
                onChange={(e) => set('camtrap_dir', e.target.value)} />
              <button type="button" className="btn btn-outline-secondary"
                onClick={() => setPicker('camtrap_dir')} disabled={inspecting}>
                {inspecting ? <span className="spinner-border spinner-border-sm" /> : t('setup.browse')}
              </button>
            </div>
          </div>

          <div className="mb-4">
            <label className="form-label fw-semibold">
              {t('setup.label_output_dir')}{' '}
              <span className="text-body-secondary fw-normal">{t('setup.label_output_optional')}</span>
            </label>
            <div className="input-group">
              <input className="form-control font-monospace"
                placeholder={t('setup.placeholder_output_dir')}
                value={form.output_dir}
                onChange={(e) => set('output_dir', e.target.value)} />
              <button type="button" className="btn btn-outline-secondary"
                onClick={() => setPicker('output_dir')}>
                {t('setup.browse')}
              </button>
            </div>
            <div className="form-text text-body-secondary">{t('setup.hint_output_dir')}</div>
          </div>
        </div>
      )}

      {/* ── PASO 1 ── */}
      {step === 1 && (
        <div>
          <h4 className="mb-1">{t('setup.step1_title')}</h4>
          <p className="text-body-secondary mb-1">{t('setup.step1_desc')}</p>

          {availableSpecies.length > 0 && (
            <div className="d-flex gap-2 mb-3">
              <button type="button" className="btn btn-outline-secondary btn-sm"
                onClick={() => setSelectedSpecies(new Set(availableSpecies))}>
                {t('setup.select_all')}
              </button>
              <button type="button" className="btn btn-outline-secondary btn-sm"
                onClick={() => setSelectedSpecies(new Set())}>
                {t('setup.deselect_all')}
              </button>
            </div>
          )}

          <div className="border border-secondary rounded p-3 mb-3"
            style={{ maxHeight: 280, overflowY: 'auto' }}>
            {availableSpecies.length === 0 && (
              <p className="text-body-secondary mb-0 small">{t('setup.no_species')}</p>
            )}
            {availableSpecies.map((sp) => (
              <div key={sp} className="form-check mb-1">
                <input className="form-check-input" type="checkbox" id={`sp-${sp}`}
                  checked={selectedSpecies.has(sp)} onChange={() => toggleSpecies(sp)} />
                <label className="form-check-label font-monospace" htmlFor={`sp-${sp}`}>{sp}</label>
              </div>
            ))}
          </div>

          <div className="text-body-secondary small mt-1">
            {t(selectedSpecies.size === 1 ? 'setup.species_count_one' : 'setup.species_count_other',
              { count: selectedSpecies.size })}
          </div>
        </div>
      )}

      {/* ── PASO 2 ── */}
      {step === 2 && (
        <div>
          <h4 className="mb-1">{t('setup.step2_title')}</h4>
          <p className="text-body-secondary mb-4">
            {t('setup.step2_desc')}
            {dataRange && (
              <> {t('setup.data_range', { min: dataRange.min, max: dataRange.max })}</>
            )}
          </p>
          <div className="row g-3">
            <div className="col-md-6">
              <label className="form-label fw-semibold">{t('setup.label_start')}</label>
              <input type="date" className="form-control" value={form.study_start}
                min={dataRange?.min} max={dataRange?.max}
                onChange={(e) => set('study_start', e.target.value)} />
            </div>
            <div className="col-md-6">
              <label className="form-label fw-semibold">{t('setup.label_end')}</label>
              <input type="date" className="form-control" value={form.study_end}
                min={dataRange?.min} max={dataRange?.max}
                onChange={(e) => set('study_end', e.target.value)} />
            </div>
          </div>
        </div>
      )}

      {/* ── PASO 3 ── */}
      {step === 3 && (
        <div>
          <h4 className="mb-1">{t('setup.step3_title')}</h4>
          <p className="text-body-secondary mb-4"
            dangerouslySetInnerHTML={{ __html: t('setup.step3_desc') }} />

          <div className="mb-4">
            <label className="form-label fw-semibold">{t('setup.label_occasion_days')}</label>
            <input type="number" className="form-control" min={1} value={form.occasion_days}
              onChange={(e) => set('occasion_days', Number(e.target.value))} />
            <div className="form-text text-body-secondary">{t('setup.hint_occasion_days')}</div>
          </div>

          <div className="mb-4">
            <label className="form-label fw-semibold">{t('setup.label_gap')}</label>
            <input type="number" className="form-control" min={1} value={form.gap_seconds}
              onChange={(e) => set('gap_seconds', Number(e.target.value))} />
            <div className="form-text text-body-secondary">{t('setup.hint_gap')}</div>
          </div>

          <div className="mb-4">
            <label className="form-label fw-semibold">{t('setup.label_min_score')}</label>
            <div className="d-flex align-items-center gap-3">
              <input type="range" className="form-range flex-grow-1"
                min={0} max={1} step={0.05} value={form.min_score}
                onChange={(e) => set('min_score', Number(e.target.value))} />
              <span className="badge bg-secondary fs-6" style={{ minWidth: 48 }}>
                {form.min_score.toFixed(2)}
              </span>
            </div>
            <div className="form-text text-body-secondary">{t('setup.hint_min_score')}</div>
          </div>
        </div>
      )}

      {/* Navegación */}
      <div className="d-flex justify-content-between mt-5">
        <button type="button" className="btn btn-outline-secondary"
          onClick={step === 0 ? () => setStep(-1) : goBack}>
          {step === 0 ? t('setup.back_welcome') : t('setup.back')}
        </button>
        {step < STEP_LABELS.length - 1 ? (
          <button type="button" className="btn btn-primary px-4" onClick={goNext}>
            {t('setup.next')}
          </button>
        ) : (
          <button type="button" className="btn btn-success px-4"
            onClick={handleSubmit} disabled={submitting}>
            {submitting
              ? <><span className="spinner-border spinner-border-sm me-2" />{t('setup.submitting')}</>
              : t('setup.submit')}
          </button>
        )}
      </div>

      {picker && (
        <DirectoryPicker
          initialPath={picker === 'camtrap_dir' ? form.camtrap_dir || undefined : form.output_dir || undefined}
          onSelect={handleDirSelected}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  )
}
