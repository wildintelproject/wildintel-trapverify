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

function Spinner({ sm }: { sm?: boolean }) {
  const sz = sm ? 'w-4 h-4 border' : 'w-8 h-8 border-2'
  return <div className={`${sz} border-zinc-600 border-t-blue-500 rounded-full animate-spin`} />
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
  const [lbBrightness, setLbBrightness] = useState(100)
  const [lbContrast, setLbContrast] = useState(100)
  const [lbRotation, setLbRotation] = useState(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [locked, setLocked] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'danger' } | null>(null)
  const decisionsRef = useRef(decisions)
  decisionsRef.current = decisions
  const decideInLbRef = useRef<(d: 'confirmed' | 'rejected') => void>(() => {})

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

  useEffect(() => {
    if (!lbOpen) return
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'y' || e.key === 'Y') decideInLbRef.current('confirmed')
      if (e.key === 'n' || e.key === 'N') decideInLbRef.current('rejected')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lbOpen])

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

  function resetLbFilters() {
    setLbBrightness(100)
    setLbContrast(100)
    setLbRotation(0)
    setLbInverted(false)
  }

  function decideInLb(d: 'confirmed' | 'rejected') {
    if (completed && locked) return
    const ev = currentEventFromSlide(lbIndex)
    if (!ev) return
    setDecisions((prev) => ({ ...prev, [ev.key]: d }))
    setNeedsDecision((prev) => { const s = new Set(prev); s.delete(ev.key); return s })
    if (!completed) {
      const currentEvIdx = events.indexOf(ev)
      for (let i = currentEvIdx + 1; i < events.length; i++) {
        if (!decisionsRef.current[events[i].key]) {
          setLbIndex(toFlatIdx(i, 0))
          return
        }
      }
      setLbOpen(false)
    }
  }
  decideInLbRef.current = decideInLb

  function decide(key: string, _repObsId: string, d: 'confirmed' | 'rejected') {
    setDecisions((prev) => ({ ...prev, [key]: d }))
    setNeedsDecision((prev) => { const s = new Set(prev); s.delete(key); return s })
  }

  function confirmAll() {
    const all: Record<string, 'confirmed' | 'rejected'> = {}
    events.forEach((ev) => { all[ev.key] = 'confirmed' })
    setDecisions(all)
    setNeedsDecision(new Set())
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
    <div className="max-w-screen-xl mx-auto px-4 py-4">
      <div className="mb-3">
        <div className="flex items-baseline gap-3 mb-1">
          <h2 className="text-2xl font-semibold mb-0 cursor-pointer" onClick={() => navigate(-1)} title="Volver">
            {t('gallery.title')}
          </h2>
          <span className="italic text-zinc-500 dark:text-zinc-400 text-lg">— {species?.replace(/_/g, ' ')}</span>
          {completed ? (
            <span className="flex items-center gap-1">
              <span className="px-2 py-0.5 text-xs font-medium bg-emerald-600 text-white rounded-full">
                {t('gallery.completed_badge')}
              </span>
              <button
                className="ml-1 bg-transparent border-0 cursor-pointer text-xl leading-none"
                title={locked ? t('gallery.unlock_tooltip') : t('gallery.lock_tooltip')}
                onClick={() => setLocked((l) => !l)}
              >
                {locked ? '🔒' : '🔓'}
              </button>
            </span>
          ) : (
            <span className="px-2 py-0.5 text-xs font-medium bg-zinc-600 text-zinc-200 rounded-full">
              {t('gallery.round', { n: iteration })}
            </span>
          )}
        </div>

        {spStats && (() => {
          const pct = spStats.n_total_combos > 0
            ? Math.round(spStats.n_resolved / spStats.n_total_combos * 100) : 0
          return (
            <>
              <span className="text-zinc-500 dark:text-zinc-400 text-sm">
                <span className="text-emerald-500 font-semibold">{spStats.n_confirmed_combos}</span>
                {' '}{t('gallery.confirmed_periods', { n: spStats.n_confirmed_combos }).replace(/^\d+ /, '')}
                {' · '}
                {t('gallery.reviewed', { resolved: spStats.n_resolved, total: spStats.n_total_combos })}
                {' · '}
                <span className={pct === 100 ? 'text-emerald-500 font-bold' : 'text-amber-400 font-semibold'}>
                  {pct}%
                </span>
              </span>
              <div className="w-full bg-zinc-200 dark:bg-zinc-700 rounded-full mt-2 mb-1" style={{ height: 6 }}>
                <div className="bg-emerald-500 rounded-full h-full" style={{ width: `${pct}%` }} />
              </div>
              <div className="flex items-start gap-2.5 px-3.5 py-2.5 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 text-sm mt-2">
                <svg className="flex-shrink-0 mt-0.5" width="15" height="15" viewBox="0 0 15 15" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M7.5 1C3.91 1 1 3.91 1 7.5S3.91 14 7.5 14 14 11.09 14 7.5 11.09 1 7.5 1zm.75 10.5h-1.5V7h1.5v4.5zm0-6h-1.5V4h1.5v1.5z" fill="currentColor"/>
                </svg>
                <span>
                  {completed
                    ? (locked ? t('gallery.review_hint_locked') : t('gallery.review_hint_unlocked'))
                    : t('gallery.round_hint', { n: iteration })}
                </span>
              </div>
            </>
          )
        })()}
      </div>

      {/* Floating action buttons */}
      {!completed && (
        <div className="fixed bottom-6 right-6 z-[200] flex gap-2">
          <button
            className="px-5 py-2.5 bg-zinc-700 text-white rounded-lg shadow-xl hover:bg-zinc-600 transition-colors flex items-center gap-2"
            onClick={() => navigate(-1)}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M10 3L5 8l5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            {t('gallery.back')}
          </button>
          <button
            className="px-5 py-2.5 bg-zinc-600 text-white rounded-lg shadow-xl hover:bg-zinc-500 transition-colors disabled:opacity-50 flex items-center gap-2"
            onClick={confirmAll}
            disabled={saving || events.length === 0}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M2 8.5L5.5 12L10 6M5 5.5L8.5 9L13 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            {t('gallery.confirm_all')}
          </button>
          <button
            className="px-5 py-2.5 bg-emerald-600 text-white rounded-lg shadow-xl hover:bg-emerald-700 transition-colors disabled:opacity-50 flex items-center gap-2"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? <Spinner sm /> : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M13 13.5H3a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5h8l2.5 2.5V13a.5.5 0 0 1-.5.5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M5 13.5V9.5h6v4M5 2.5v3h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            )}
            {saving ? t('gallery.saving') : t('gallery.save')}
          </button>
        </div>
      )}

      {completed && !locked && (
        <button
          className="fixed bottom-6 right-6 z-[200] px-5 py-2.5 bg-amber-500 text-white rounded-lg shadow-xl hover:bg-amber-600 transition-colors disabled:opacity-50 flex items-center gap-2"
          onClick={handleUpdateDecisions}
          disabled={saving}
        >
          {saving && <Spinner sm />}
          {saving ? t('gallery.updating') : t('gallery.update_decisions')}
        </button>
      )}

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 mb-3">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner />
        </div>
      ) : events.length === 0 ? (
        <div className="px-4 py-3 rounded-lg bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300">
          No hay eventos pendientes para esta especie en esta ronda.
        </div>
      ) : (
        Object.entries(bySite).map(([site, siteEvents]) => (
          <div key={site} className="mb-4 border border-zinc-700 rounded-lg p-3">
            <h5 className="mb-3 flex items-center text-base font-semibold">
              <span className="text-zinc-500 dark:text-zinc-400 font-normal">{t('gallery.location')}</span>
              <span className="ml-2">{site}</span>
              <span className="ml-auto px-2 py-0.5 text-xs font-normal bg-zinc-600 text-zinc-200 rounded-full">
                {siteEvents.length === 1
                  ? t('gallery.periods', { n: siteEvents.length })
                  : t('gallery.periods_plural', { n: siteEvents.length })}
              </span>
              <span className="ml-2 px-2 py-0.5 text-xs font-normal rounded-full text-white"
                style={{ backgroundColor: iterationColor(iteration, totalIterations) }}>
                {t('gallery.confidence', {
                  min: Math.min(...siteEvents.map((e) => e.maxProb * 100)).toFixed(0),
                  max: Math.max(...siteEvents.map((e) => e.maxProb * 100)).toFixed(0),
                })}
              </span>
            </h5>
            <hr className="border-zinc-700 mt-0 mb-3" />
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

      <style>{`.yarl__slide_image {
        filter: brightness(${lbBrightness}%) contrast(${lbContrast}%)${lbInverted ? ' invert(1)' : ''} !important;
        ${lbRotation !== 0 ? `transform: rotate(${lbRotation}deg) !important; ${lbRotation % 180 !== 0 ? 'max-width: 80vh !important; max-height: 80vw !important;' : ''}` : ''}
      }`}</style>

      <YARLightbox
        open={lbOpen}
        close={() => { setLbOpen(false); resetLbFilters() }}
        index={lbIndex}
        slides={slides}
        plugins={[Zoom, Captions]}
        on={{ view: ({ index }) => { setLbIndex(index); resetLbFilters() } }}
        zoom={{ maxZoomPixelRatio: 8, scrollToZoom: true }}
        captions={{ showToggle: false, descriptionTextAlign: 'center' }}
        toolbar={{
          buttons: [
            <label
              key="brightness"
              title={`${t('gallery.brightness')}: ${lbBrightness}%`}
              style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 6px', color: lbBrightness !== 100 ? '#fbbf24' : '#aaa', fontSize: 14, cursor: 'default' }}
            >
              ☀
              <input
                type="range" min={50} max={200} step={5} value={lbBrightness}
                onChange={(e) => setLbBrightness(Number(e.target.value))}
                onMouseDown={(e) => e.stopPropagation()}
                onTouchStart={(e) => e.stopPropagation()}
                style={{ width: 70, accentColor: '#fbbf24' }}
              />
            </label>,
            <label
              key="contrast"
              title={`${t('gallery.contrast')}: ${lbContrast}%`}
              style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 6px', color: lbContrast !== 100 ? '#fbbf24' : '#aaa', fontSize: 14, cursor: 'default' }}
            >
              ◑
              <input
                type="range" min={50} max={200} step={5} value={lbContrast}
                onChange={(e) => setLbContrast(Number(e.target.value))}
                onMouseDown={(e) => e.stopPropagation()}
                onTouchStart={(e) => e.stopPropagation()}
                style={{ width: 70, accentColor: '#fbbf24' }}
              />
            </label>,
            <button
              key="rotate"
              title={t('gallery.rotate')}
              className="yarl__button"
              onClick={() => setLbRotation((r) => (r + 90) % 360)}
              style={{ color: lbRotation !== 0 ? '#fbbf24' : undefined }}
            >
              ↻
            </button>,
            ...(lbBrightness !== 100 || lbContrast !== 100 || lbRotation !== 0 || lbInverted ? [
              <button
                key="reset"
                title={t('gallery.reset_filters')}
                className="yarl__button"
                onClick={resetLbFilters}
                style={{ color: '#f87171' }}
              >
                ⊘
              </button>,
            ] : []),
            <span key="sep0" style={{ width: 1, background: '#444', margin: '8px 4px' }} />,
            <button
              key="invert"
              title={t('gallery.invert')}
              className={`yarl__button ${lbInverted ? 'yarl__button--active' : ''}`}
              onClick={() => setLbInverted((v) => !v)}
              style={{ color: lbInverted ? '#fbbf24' : undefined }}
            >
              ⊙
            </button>,
            <span key="sep" style={{ width: 1, background: '#444', margin: '8px 4px' }} />,
            <button
              key="confirm"
              title={`${t('gallery.confirmed_btn')} (Y)`}
              className="yarl__button"
              style={{
                color: lbDecision === 'confirmed' ? '#10b981' : '#aaa',
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
              title={`${t('gallery.rejected_btn')} (N)`}
              className="yarl__button"
              style={{
                color: lbDecision === 'rejected' ? '#ef4444' : '#aaa',
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
        <div className={`fixed bottom-0 right-0 m-3 z-[2000] px-4 py-3 rounded-lg text-white shadow-lg ${
          toast.type === 'success' ? 'bg-emerald-600' : 'bg-red-600'
        }`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
