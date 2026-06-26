import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import YARLightbox, { type SlideImage } from 'yet-another-react-lightbox'
import Zoom from 'yet-another-react-lightbox/plugins/zoom'
import Captions from 'yet-another-react-lightbox/plugins/captions'
import 'yet-another-react-lightbox/styles.css'
import 'yet-another-react-lightbox/plugins/captions.css'
import { api } from '../api'
import EventCard from '../components/EventCard'
import type { DetectionEvent } from '../types'

interface EventSlide extends SlideImage {
  eventKey: string
  repObsId: string
  siteId: string
  occasion: number
  prob: number
  frameTs: string
}

export default function GalleryPage() {
  const { species } = useParams<{ species: string }>()
  const navigate = useNavigate()
  const { t } = useTranslation()

  const [events, setEvents] = useState<DetectionEvent[]>([])
  const [spStats, setSpStats] = useState<{ n_total_combos: number; n_confirmed_combos: number; n_resolved: number } | null>(null)
  const [iteration, setIteration] = useState(1)
  const [totalIterations, setTotalIterations] = useState(1)
  const [decisions, setDecisions] = useState<Record<string, 'confirmed' | 'rejected'>>({})
  const [needsDecision, setNeedsDecision] = useState<Set<string>>(new Set())
  const [lbOpen, setLbOpen] = useState(false)
  const [lbIndex, setLbIndex] = useState(0)
  const [lbInverted, setLbInverted] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [locked, setLocked] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'danger' } | null>(null)
  const decisionsRef = useRef(decisions)
  decisionsRef.current = decisions

  function iterationColor(iter: number, total: number): string {
    const ratio = total > 1 ? (iter - 1) / (total - 1) : 0
    const hue = Math.round(120 - ratio * 120)
    return `hsl(${hue}, 70%, 40%)`
  }

  function showToast(msg: string, type: 'success' | 'danger') {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const loadEvents = useCallback(async (iter: number) => {
    if (!species) return
    setLoading(true)
    setError(null)
    try {
      const [evts, saved, allStats, state] = await Promise.all([
        api.getEvents(species, iter),
        api.getDecisions(species, iter),
        api.getSpecies(),
        api.getState(),
      ])
      const sp = allStats.find((s) => s.species_safe === species)
      if (sp) setSpStats(sp)
      if (state.config?.total_iterations) setTotalIterations(state.config.total_iterations)

      if (sp && sp.n_resolved >= sp.n_total_combos) {
        setCompleted(true)
        const reviewEvts = await api.getReview(species)
        setEvents(reviewEvts)
        const pre: Record<string, 'confirmed' | 'rejected'> = {}
        reviewEvts.forEach((ev) => {
          pre[ev.key] = ev.status === 'confirmed' ? 'confirmed' : 'rejected'
        })
        setDecisions(pre)
        return
      }

      setEvents(evts)
      const pre: Record<string, 'confirmed' | 'rejected'> = {}
      saved.confirmed.forEach((id) => {
        const ev = evts.find((e) => e.repObsId === id || e.frames.some((f) => f.obsId === id))
        if (ev) pre[ev.key] = 'confirmed'
      })
      setDecisions(pre)
      setNeedsDecision(new Set())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar eventos')
    } finally {
      setLoading(false)
    }
  }, [species])

  useEffect(() => { loadEvents(iteration) }, [loadEvents, iteration])

  const slides: EventSlide[] = events.flatMap((ev) =>
    ev.frames.map((fr) => ({
      src: fr.img,
      title: t('gallery.lb_title', { site: ev.siteId, occasion: ev.occasion }),
      description: `${(fr.prob * 100).toFixed(0)}%  ·  ${fr.ts}`,
      eventKey: ev.key,
      repObsId: ev.repObsId,
      siteId: ev.siteId,
      occasion: ev.occasion,
      prob: fr.prob,
      frameTs: fr.ts,
    }))
  )

  function toFlatIdx(evIdx: number, frIdx: number): number {
    return events.slice(0, evIdx).reduce((s, e) => s + e.frames.length, 0) + frIdx
  }

  function currentEventFromSlide(flatIdx: number): DetectionEvent | undefined {
    let remaining = flatIdx
    for (const ev of events) {
      if (remaining < ev.frames.length) return ev
      remaining -= ev.frames.length
    }
  }

  function openLightbox(evIdx: number, frIdx: number) {
    setLbIndex(toFlatIdx(evIdx, frIdx))
    setLbInverted(false)
    setLbOpen(true)
  }

  function decideInLb(d: 'confirmed' | 'rejected') {
    if (completed && locked) return
    const ev = currentEventFromSlide(lbIndex)
    if (!ev) return
    setDecisions((prev) => ({ ...prev, [ev.key]: d }))
    setNeedsDecision((prev) => { const s = new Set(prev); s.delete(ev.key); return s })
    if (!completed) {
      let remaining = lbIndex + 1
      for (let i = 0; i < events.length; i++) {
        const e = events[i]
        if (remaining < e.frames.length) {
          if (!decisionsRef.current[e.key]) { setLbIndex(remaining); return }
        }
        remaining -= e.frames.length
      }
      setLbOpen(false)
    }
  }

  function decide(key: string, _repObsId: string, d: 'confirmed' | 'rejected') {
    setDecisions((prev) => ({ ...prev, [key]: d }))
    setNeedsDecision((prev) => { const s = new Set(prev); s.delete(key); return s })
  }

  async function handleSave() {
    const undecided = events.filter((e) => !decisions[e.key])
    if (undecided.length > 0) {
      setNeedsDecision(new Set(undecided.map((e) => e.key)))
      document.querySelector(`[data-key="${undecided[0].key}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      showToast(t('gallery.needs_decision'), 'danger')
      return
    }
    if (!species) return
    setSaving(true)
    try {
      const confirmedIds = events
        .filter((e) => decisions[e.key] === 'confirmed')
        .map((e) => e.repObsId)
      const result = await api.saveDecisions(species, iteration, confirmedIds)
      if (result.done) {
        showToast(t('gallery.toast_done'), 'success')
        setTimeout(() => navigate('/species'), 1500)
      } else {
        showToast(t('gallery.toast_saved', { n: result.next_iteration, remaining: result.remaining }), 'success')
        setIteration(result.next_iteration!)
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : t('gallery.toast_error'), 'danger')
    } finally {
      setSaving(false)
    }
  }

  async function handleUpdateDecisions() {
    if (!species) return
    setSaving(true)
    try {
      const confirmedKeys = events
        .filter((e) => decisions[e.key] === 'confirmed')
        .map((e) => e.key)
      await api.updateDecisions(species, confirmedKeys)
      setLocked(true)
      showToast(t('gallery.toast_updated'), 'success')
    } catch (e) {
      showToast(e instanceof Error ? e.message : t('gallery.toast_error'), 'danger')
    } finally {
      setSaving(false)
    }
  }

  const bySite = events.reduce<Record<string, DetectionEvent[]>>((acc, ev) => {
    ;(acc[ev.siteId] ??= []).push(ev)
    return acc
  }, {})

  const lbCurrentEv = currentEventFromSlide(lbIndex)
  const lbDecision  = lbCurrentEv ? decisions[lbCurrentEv.key] : undefined
  const lbReadOnly  = completed && locked

  return (
    <div className="container py-4">
      <div className="mb-3">
        <div className="d-flex align-items-baseline gap-3 mb-1">
          <h2 className="mb-0" style={{ cursor: 'pointer' }} onClick={() => navigate(-1)} title="Volver">
            {t('gallery.title')}
          </h2>
          <span className="fst-italic text-body-secondary fs-5">— {species?.replace(/_/g, ' ')}</span>
          {completed ? (
            <span className="d-flex align-items-center gap-1">
              <span className="badge bg-success">{t('gallery.completed_badge')}</span>
              <button
                className="btn btn-sm btn-link p-0 ms-1 text-decoration-none"
                title={locked ? t('gallery.unlock_tooltip') : t('gallery.lock_tooltip')}
                onClick={() => setLocked((l) => !l)}
                style={{ fontSize: '1.15rem', lineHeight: 1 }}
              >
                {locked ? '🔒' : '🔓'}
              </button>
            </span>
          ) : (
            <span className="badge bg-secondary">{t('gallery.round', { n: iteration })}</span>
          )}
        </div>

        {spStats && (() => {
          const pct = spStats.n_total_combos > 0
            ? Math.round(spStats.n_resolved / spStats.n_total_combos * 100) : 0
          return (
            <>
              <span className="text-body-secondary small">
                <span className="text-success fw-semibold">{spStats.n_confirmed_combos}</span>
                {' '}{t('gallery.confirmed_periods', { n: spStats.n_confirmed_combos }).replace(/^\d+ /, '')}
                &nbsp;·&nbsp;
                {t('gallery.reviewed', { resolved: spStats.n_resolved, total: spStats.n_total_combos })}
                &nbsp;·&nbsp;
                <span className={pct === 100 ? 'text-success fw-bold' : 'text-warning fw-semibold'}>
                  {pct}%
                </span>
              </span>
              <div className="progress mt-2 mb-1" style={{ height: 6 }}>
                <div className="progress-bar bg-success" style={{ width: `${pct}%` }} />
              </div>
              <p className="text-body-secondary small mb-0 mt-2">
                {completed
                  ? (locked ? t('gallery.review_hint_locked') : t('gallery.review_hint_unlocked'))
                  : t('gallery.round_hint', { n: iteration })}
              </p>
            </>
          )
        })()}
      </div>

      {!completed && (
        <button
          className="btn btn-success"
          onClick={handleSave}
          disabled={saving}
          style={{ position: 'fixed', bottom: 24, right: 24, zIndex: 200, boxShadow: '0 4px 12px rgba(0,0,0,.5)' }}
        >
          {saving && <span className="spinner-border spinner-border-sm me-1" />}
          {saving ? t('gallery.saving') : t('gallery.save')}
        </button>
      )}

      {completed && !locked && (
        <button
          className="btn btn-warning"
          onClick={handleUpdateDecisions}
          disabled={saving}
          style={{ position: 'fixed', bottom: 24, right: 24, zIndex: 200, boxShadow: '0 4px 12px rgba(0,0,0,.5)' }}
        >
          {saving && <span className="spinner-border spinner-border-sm me-1" />}
          {saving ? t('gallery.updating') : t('gallery.update_decisions')}
        </button>
      )}

      {error && <div className="alert alert-danger">{error}</div>}

      {loading ? (
        <div className="d-flex justify-content-center py-5">
          <div className="spinner-border text-primary" />
        </div>
      ) : events.length === 0 ? (
        <div className="alert alert-info">No hay eventos pendientes para esta especie en esta ronda.</div>
      ) : (
        Object.entries(bySite).map(([site, siteEvents]) => (
          <div key={site} className="mb-4 border border-secondary rounded p-3">
            <h5 className="mb-3 d-flex align-items-center">
              <span className="text-body-secondary fw-normal">{t('gallery.location')}</span>{' '}
              <span className="ms-2">{site}</span>
              <span className="ms-auto badge bg-secondary fs-6 fw-normal">
                {siteEvents.length === 1
                  ? t('gallery.periods', { n: siteEvents.length })
                  : t('gallery.periods_plural', { n: siteEvents.length })}
              </span>
              <span className="ms-2 badge fs-6 fw-normal"
                style={{ backgroundColor: iterationColor(iteration, totalIterations) }}>
                {t('gallery.confidence', {
                  min: Math.min(...siteEvents.map((e) => e.maxProb * 100)).toFixed(0),
                  max: Math.max(...siteEvents.map((e) => e.maxProb * 100)).toFixed(0),
                })}
              </span>
            </h5>
            <hr className="border-secondary mt-0 mb-3" />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '1rem' }}>
              {siteEvents.map((ev) => {
                const idx = events.indexOf(ev)
                return (
                  <div key={ev.key} data-key={ev.key}>
                    <EventCard
                      event={ev}
                      decision={decisions[ev.key] ?? null}
                      needsDecision={needsDecision.has(ev.key)}
                      onDecide={decide}
                      onOpenLightbox={(eIdx, fIdx) => openLightbox(eIdx, fIdx)}
                      eventIdx={idx}
                      readOnly={completed && locked}
                    />
                  </div>
                )
              })}
            </div>
          </div>
        ))
      )}

      {lbInverted && (
        <style>{`.yarl__slide_image { filter: invert(1) !important; }`}</style>
      )}

      <YARLightbox
        open={lbOpen}
        close={() => setLbOpen(false)}
        index={lbIndex}
        slides={slides}
        plugins={[Zoom, Captions]}
        on={{ view: ({ index }) => { setLbIndex(index); setLbInverted(false) } }}
        zoom={{ maxZoomPixelRatio: 8, scrollToZoom: true }}
        captions={{ showToggle: false, descriptionTextAlign: 'center' }}
        toolbar={{
          buttons: [
            <button
              key="invert"
              title={t('gallery.invert')}
              className={`yarl__button ${lbInverted ? 'yarl__button--active' : ''}`}
              onClick={() => setLbInverted((v) => !v)}
              style={{ color: lbInverted ? '#ffc107' : undefined }}
            >
              ⊙
            </button>,
            <span key="sep" style={{ width: 1, background: '#444', margin: '8px 4px' }} />,
            <button
              key="confirm"
              title={t('gallery.confirmed_btn')}
              className="yarl__button"
              style={{
                color: lbDecision === 'confirmed' ? '#198754' : '#aaa',
                fontWeight: 'bold',
                opacity: lbReadOnly ? 0.3 : 1,
              }}
              onClick={() => decideInLb('confirmed')}
              disabled={lbReadOnly}
            >
              ✓
            </button>,
            <button
              key="reject"
              title={t('gallery.rejected_btn')}
              className="yarl__button"
              style={{
                color: lbDecision === 'rejected' ? '#dc3545' : '#aaa',
                fontWeight: 'bold',
                opacity: lbReadOnly ? 0.3 : 1,
              }}
              onClick={() => decideInLb('rejected')}
              disabled={lbReadOnly}
            >
              ✗
            </button>,
            'close',
          ],
        }}
      />

      {toast && (
        <div
          className={`toast show position-fixed bottom-0 end-0 m-3 text-white bg-${toast.type}`}
          style={{ zIndex: 2000 }}
        >
          <div className="toast-body">{toast.msg}</div>
        </div>
      )}
    </div>
  )
}
