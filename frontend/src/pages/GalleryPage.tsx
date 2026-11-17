import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import YARLightbox, { type ControllerRef, type SlideImage } from 'yet-another-react-lightbox'
import Zoom from 'yet-another-react-lightbox/plugins/zoom'
import Captions from 'yet-another-react-lightbox/plugins/captions'
import 'yet-another-react-lightbox/styles.css'
import 'yet-another-react-lightbox/plugins/captions.css'
import { api } from '../api'
import EventCard, { type Decision } from '../components/EventCard'
import { frameSrc } from '../utils/frameImage'
import { crossButtonState } from '../crossState'
import { effectiveMinScore } from '../utils/minScore'
import { clearDraft, draftKey, loadDraft, saveDraft } from '../utils/draft'
import type { CrossSpecies, DetectionEvent, SpeciesStats } from '../types'

interface EventSlide extends SlideImage {
  eventKey: string
  repObsId: string
  siteId: string
  occasion: number
  prob: number
  frameTs: string
}

/** The unfinished work as the server stores it: decided events by their cell key (as in the community fork). */
function progressBody(
  events: DetectionEvent[],
  decisions: Record<string, Decision>,
  corrections: Record<string, string>,
  times: Record<string, number>,
  iteration: number,
  mode: 'rounds' | 'pending' = 'rounds',
  chosenRep: Record<string, string> = {},
) {
  const dec: Record<string, 'confirmed' | 'rejected' | 'unsure'> = {}
  const corr: Record<string, string> = {}
  const tm: Record<string, number> = {}
  const rep: Record<string, string> = {}
  events.forEach((e) => {
    const d = decisions[e.key]
    if (!d) return
    dec[e.key] = d
    const text = (corrections[e.key] ?? '').trim()
    if (d === 'rejected' && text) corr[e.key] = text
    if (times[e.key]) tm[e.key] = times[e.key]
    if (mode === 'pending' && d === 'confirmed' && chosenRep[e.key]) rep[e.key] = chosenRep[e.key]
  })
  return { mode, iteration, decisions: dec, chosen_rep: rep, corrections: corr, decision_times: tm }
}

/** The draft this browser kept for a round, when it is newer than what the server holds. */
function newerDraft(sid: string, species: string, mode: 'rounds' | 'pending', iter: number, serverSavedAt?: string | null) {
  if (!sid) return null
  const d = loadDraft(draftKey(sid, species, mode, iter))
  if (!d || Object.keys(d.decisions).length === 0) return null
  const tLocal = d.savedAt ? Date.parse(d.savedAt) || 0 : 0
  const tServer = serverSavedAt ? Date.parse(serverSavedAt) || 0 : 0
  return tLocal > tServer ? d : null
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
  const [spStats, setSpStats] = useState<{ species_name: string; n_total_combos: number; n_confirmed_combos: number; n_resolved: number; n_pending?: number } | null>(null)
  const [reviewParams, setReviewParams] = useState<{ gap_seconds: number; occasion_days: number; occasion_hours: number; min_score: number; min_score_by_species?: Record<string, number>; review_order?: 'score' | 'time' } | null>(null)
  const [iteration, setIteration] = useState(1)
  const [totalIterations, setTotalIterations] = useState(1)
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [needsDecision, setNeedsDecision] = useState<Set<string>>(new Set())
  const [lbOpen, setLbOpen] = useState(false)
  const [lbEvIdx, setLbEvIdx] = useState(0)   // which event is shown in the lightbox
  const [siteIdx, setSiteIdx] = useState(0)    // the gallery shows one location at a time
  const gridTopRef = useRef<HTMLDivElement>(null)
  // Cards the lightbox moved on from after a decision, most recent last: "previous card" walks
  // back through them to correct a mistake.
  const [lbHistory, setLbHistory] = useState<number[]>([])
  // Narrow screens keep the controls in a strip at the bottom instead of a panel on the left.
  const [lbNarrow, setLbNarrow] = useState(() => typeof window !== 'undefined' && window.innerWidth < 900)
  const [lbIndex, setLbIndex] = useState(0)   // frame index within that event
  const [lbInverted, setLbInverted] = useState(false)
  const [lbBrightness, setLbBrightness] = useState(100)
  const [lbContrast, setLbContrast] = useState(100)
  const [lbRotation, setLbRotation] = useState(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [completed, setCompleted] = useState(false)
  // Pending expert review: the cells whose events ran out with an unsure event. Shown after the rounds;
  // each can be confirmed (the event being looked at), settled as not detected, or left unsure.
  const [pendingMode, setPendingMode] = useState(false)
  const chosenRepRef = useRef<Record<string, string>>({})     // cell key -> event confirmed while looking at it
  const [recordRejection, setRecordRejection] = useState(false)
  const [showBoxes, setShowBoxes] = useState<boolean>(() => {
    try { return localStorage.getItem('camtrapShowBoxes') !== '0' } catch { return true }
  })
  function toggleBoxes(on: boolean) {
    setShowBoxes(on)
    try { localStorage.setItem('camtrapShowBoxes', on ? '1' : '0') } catch { /* storage unavailable */ }
  }
  const [corrections, setCorrections] = useState<Record<string, string>>({})
  const [taxa, setTaxa] = useState<string[]>([])
  const [locked, setLocked] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'danger' | 'warning' } | null>(null)
  // Progress of the unfinished round, kept in the session folder ("Save progress").
  const [progressAt, setProgressAt] = useState<string | null>(null)
  const [progressState, setProgressState] = useState<'idle' | 'dirty' | 'saving' | 'error'>('idle')
  const [reloadKey, setReloadKey] = useState(0)
  const lastSavedRef = useRef('')
  const finishedRef = useRef(false)
  const [sessionId, setSessionId] = useState('')
  const progressTimerRef = useRef<number | null>(null)
  const decisionsRef = useRef(decisions)
  const completedRef = useRef(false)
  // When the reviewer last set each event's decision in this page (epoch ms), for the review-time log.
  const decidedAtRef = useRef<Record<string, number>>({})
  decisionsRef.current = decisions
  completedRef.current = completed
  const decideInLbRef = useRef<(d: Decision) => void>(() => {})
  const lbBackRef = useRef<() => void>(() => {})
  const toggleCrossRef = useRef<(i: number) => void>(() => {})
  // Another species seen in a photo can be confirmed from the large view (see the lightbox panel).
  const [targetSpecies, setTargetSpecies] = useState<string[]>([])
  const [crossByCell, setCrossByCell] = useState<Record<string, CrossSpecies[]>>({})
  const [crossBusy, setCrossBusy] = useState(false)
  const lbControllerRef = useRef<ControllerRef>(null)

  function iterationColor(iter: number, total: number): string {
    const ratio = total > 1 ? (iter - 1) / (total - 1) : 0
    const hue = Math.round(120 - ratio * 120)
    return `hsl(${hue}, 70%, 40%)`
  }

  function showToast(msg: string, type: 'success' | 'danger' | 'warning', ms = 3000) {
    setToast({ msg, type })
    setTimeout(() => setToast(null), ms)
  }

  const loadEvents = useCallback(async (iter: number) => {
    if (!species) return
    finishedRef.current = false
    setLoading(true)
    setError(null)
    try {
      const [allStats, state] = await Promise.all([api.getSpecies().catch(() => [] as SpeciesStats[]), api.getState()])
      const sp = allStats.find((s) => s.species_safe === species)
      if (sp) setSpStats(sp)
      if (state.config?.total_iterations) setTotalIterations(state.config.total_iterations)
      setSessionId(state.session_dir ?? '')
      const recording = !!state.config?.record_rejection_species
      setRecordRejection(recording)
      if (recording) {
        api.getTaxa().then((r) => setTaxa(Array.from(new Set([...r.taxa, ...r.extra])))).catch(() => {})
      }
      setTargetSpecies(state.config?.target_species ?? [])
      if (state.config) setReviewParams({ gap_seconds: state.config.gap_seconds, occasion_days: state.config.occasion_days, occasion_hours: state.config.occasion_hours ?? 0, min_score: state.config.min_score, min_score_by_species: state.config.min_score_by_species, review_order: state.config.review_order })

      setPendingMode(false)
      setCompleted(false)
      if (sp && sp.phase === 'pending') {
        const pend = await api.getPending(species)
        setPendingMode(true)
        setEvents(pend)
        setSiteIdx(0)
        setNeedsDecision(new Set())
        decidedAtRef.current = {}
        chosenRepRef.current = {}
        // Verdicts given earlier in this view and not yet saved come back as they were left.
        const prog = await api.getProgress(species, 'pending', 0).then((r) => r.progress).catch(() => null)
        // A draft kept by this browser that is newer than the server's progress wins (the tab was
        // closed before the autosave reached the server).
        const draft = newerDraft(state.session_dir ?? '', species, 'pending', 0, prog?.saved_at)
        const restored: Record<string, Decision> = {}
        const restoredCorr: Record<string, string> = {}
        pend.forEach((ev) => {
          const d = (draft ? draft.decisions : prog?.decisions)?.[ev.key]
          if (!d) return
          restored[ev.key] = d
          const rep = (draft ? draft.chosenRep : prog?.chosen_rep)?.[ev.key]
          if (rep) chosenRepRef.current[ev.key] = rep
          if (prog?.corrections[ev.key]) restoredCorr[ev.key] = prog.corrections[ev.key]
          if (prog?.decision_times[ev.key]) decidedAtRef.current[ev.key] = prog.decision_times[ev.key]
        })
        setDecisions(restored)
        setCorrections(restoredCorr)
        setProgressAt(prog?.saved_at ?? null)
        // With a newer draft the server does not hold this yet: the next autosave sends it.
        lastSavedRef.current = draft ? '' : JSON.stringify(progressBody(pend, restored, restoredCorr, decidedAtRef.current, 0, 'pending', chosenRepRef.current))
        setProgressState('idle')
        return
      }
      if (sp && sp.n_resolved >= sp.n_total_combos) {
        setCompleted(true)
        const reviewEvts = await api.getReview(species)
        setEvents(reviewEvts)
        const pre: Record<string, Decision> = {}
        reviewEvts.forEach((ev) => {
          pre[ev.key] = ev.status === 'confirmed' ? 'confirmed' : 'rejected'
        })
        setDecisions(pre)
        return
      }

      // Only a species still in its rounds needs the events of this round (a complete one shows its
      // review, one with only pending cells shows those).
      const [evts, saved] = await Promise.all([api.getEvents(species, iter), api.getDecisions(species, iter)])
      setEvents(evts)
      setSiteIdx(0)
      const pre: Record<string, Decision> = {}
      saved.confirmed.forEach((id) => {
        const ev = evts.find((e) => e.repObsId === id || e.frames.some((f) => f.obsId === id))
        if (ev) pre[ev.key] = 'confirmed'
      })
      ;(saved.unsure ?? []).forEach((id) => {
        const ev = evts.find((e) => e.repObsId === id || e.frames.some((f) => f.obsId === id))
        if (ev && !pre[ev.key]) pre[ev.key] = 'unsure'
      })
      setDecisions(pre)
      const corr: Record<string, string> = {}
      Object.entries(saved.corrections ?? {}).forEach(([id, text]) => {
        const ev = evts.find((e) => e.repObsId === id || e.frames.some((f) => f.obsId === id))
        if (ev) corr[ev.key] = text
      })
      setCorrections(corr)
      decidedAtRef.current = {}
      setNeedsDecision(new Set())

      // Unfinished work from an earlier visit (any browser, or another computer through the
      // session export): the progress saved in the session folder wins over the round's files.
      const prog = await api.getProgress(species, 'rounds', iter).then((r) => r.progress).catch(() => null)
      const draft = newerDraft(state.session_dir ?? '', species, 'rounds', iter, prog?.saved_at)
      if (prog || draft) {
        const restored: Record<string, Decision> = {}
        const restoredCorr: Record<string, string> = {}
        evts.forEach((ev) => {
          const d = (draft ? draft.decisions : prog?.decisions)?.[ev.key]
          if (!d) return
          restored[ev.key] = d
          if (prog?.corrections[ev.key]) restoredCorr[ev.key] = prog.corrections[ev.key]
          if (prog?.decision_times[ev.key]) decidedAtRef.current[ev.key] = prog.decision_times[ev.key]
        })
        setDecisions(restored)
        setCorrections(restoredCorr)
        setProgressAt(prog?.saved_at ?? null)
        lastSavedRef.current = draft ? '' : JSON.stringify(progressBody(evts, restored, restoredCorr, decidedAtRef.current, iter))
      } else {
        setProgressAt(null)
        lastSavedRef.current = JSON.stringify(progressBody(evts, pre, corr, decidedAtRef.current, iter))
      }
      setProgressState('idle')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar eventos')
    } finally {
      setLoading(false)
    }
  }, [species])

  // Open a species at its current round (the one the index shows), not always at round 1:
  // coming back to a species mid-review used to re-present occasions already rejected.
  const [roundReady, setRoundReady] = useState(false)
  useEffect(() => {
    if (!species) return
    let live = true
    api.getSpecies()
      .then((all) => {
        const sp = all.find((s) => s.species_safe === species)
        if (live && sp && sp.current_iteration > 0) setIteration(sp.current_iteration)
      })
      .catch(() => { /* fall back to round 1 */ })
      .finally(() => { if (live) setRoundReady(true) })
    return () => { live = false }
  }, [species])

  useEffect(() => { if (roundReady) loadEvents(iteration) }, [loadEvents, iteration, roundReady, reloadKey])

  // Save the progress a couple of seconds after the last click, with the "Save progress"
  // button, and when the page is closed. Nothing counts as a result until the round is finished.
  const progressPayload = useCallback(() => {
    if (!species || completed || loading || saving || finishedRef.current || events.length === 0) return null
    const body = pendingMode
      ? progressBody(events, decisions, corrections, decidedAtRef.current, 0, 'pending', chosenRepRef.current)
      : progressBody(events, decisions, corrections, decidedAtRef.current, iteration)
    const json = JSON.stringify(body)
    return json === lastSavedRef.current ? null : { body, json }
  }, [species, completed, pendingMode, loading, saving, events, decisions, corrections, iteration])

  const flushProgress = useCallback(async (opts: { keepalive?: boolean; announce?: boolean } = {}) => {
    if (progressTimerRef.current) { window.clearTimeout(progressTimerRef.current); progressTimerRef.current = null }
    const p = progressPayload()
    if (!p || !species) {
      if (opts.announce) showToast(t('gallery.progress_up_to_date'), 'success')
      return
    }
    setProgressState('saving')
    try {
      const r = await api.saveProgress(species, p.body, opts.keepalive)
      lastSavedRef.current = p.json
      setProgressAt(r.saved_at)
      setProgressState('idle')
      if (opts.announce) showToast(t('gallery.progress_saved_toast', { n: Object.keys(p.body.decisions).length }), 'success')
    } catch {
      setProgressState('error')
      if (opts.announce) showToast(t('gallery.toast_error'), 'danger')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [progressPayload, species])

  useEffect(() => {
    if (!progressPayload()) return
    setProgressState('dirty')
    progressTimerRef.current = window.setTimeout(() => { flushProgress() }, 2500)
    return () => { if (progressTimerRef.current) window.clearTimeout(progressTimerRef.current) }
  }, [progressPayload, flushProgress])

  // Keep a draft of the decisions in this browser too, so hours of review are not lost if the tab
  // is closed before the autosave reaches the server. Only a convenience: the server's progress is
  // what counts, and the draft is dropped when the round is saved.
  useEffect(() => {
    if (loading || completed || finishedRef.current || !sessionId || !species) return
    if (Object.keys(decisions).length === 0) return
    saveDraft(draftKey(sessionId, species, pendingMode ? 'pending' : 'rounds', pendingMode ? 0 : iteration),
      { decisions, chosenRep: { ...chosenRepRef.current } })
  }, [decisions, loading, completed, sessionId, species, pendingMode, iteration])

  const flushRef = useRef(flushProgress)
  flushRef.current = flushProgress
  useEffect(() => {
    const onHide = () => { flushRef.current({ keepalive: true }) }
    window.addEventListener('pagehide', onHide)
    return () => { window.removeEventListener('pagehide', onHide); flushRef.current({ keepalive: true }) }
  }, [])

  useEffect(() => {
    if (!lbOpen) return
    const curSiteId = events[lbEvIdx]?.siteId
    const siteIndices = events
      .map((ev, i) => ({ i, siteId: ev.siteId }))
      .filter(x => x.siteId === curSiteId)
    const posInSite = siteIndices.findIndex(x => x.i === lbEvIdx)

    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'y' || e.key === 'Y') decideInLbRef.current('confirmed')
      if (e.key === 'n' || e.key === 'N') decideInLbRef.current('rejected')
      if ((e.key === 'u' || e.key === 'U') && !completedRef.current) decideInLbRef.current('unsure')
      if (e.key === 'Backspace') { e.preventDefault(); lbBackRef.current() }
      if (/^[1-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) toggleCrossRef.current(Number(e.key) - 1)
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        e.stopPropagation()
        if (posInSite > 0) {
          setLbEvIdx(siteIndices[posInSite - 1].i)
          setLbIndex(0)
        }
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        e.stopPropagation()
        if (posInSite < siteIndices.length - 1) {
          setLbEvIdx(siteIndices[posInSite + 1].i)
          setLbIndex(0)
        }
      }
    }
    window.addEventListener('keydown', onKey, { capture: true })
    return () => window.removeEventListener('keydown', onKey, { capture: true })
  }, [lbOpen, lbEvIdx, events])

  useEffect(() => {
    const onResize = () => setLbNarrow(window.innerWidth < 900)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const lbEv = events[lbEvIdx]
  const lbSlides: EventSlide[] = lbEv
    ? lbEv.frames.map((fr, i) => ({
        src: frameSrc(fr, showBoxes),
        title: t('gallery.lb_title', {
          site: lbEv.siteId,
          occasion: lbEv.occasion,
          idx: i + 1,
          total: lbEv.frames.length,
          meta: fr.prob != null ? `${(fr.prob * 100).toFixed(0)}%  ·  ${fr.ts}` : fr.ts,
        }),
        eventKey: lbEv.key,
        repObsId: lbEv.repObsId,
        siteId: lbEv.siteId,
        occasion: lbEv.occasion,
        prob: fr.prob ?? 0,
        frameTs: fr.ts,
      }))
    : []

  const openLightbox = useCallback((evIdx: number, frIdx: number) => {
    setLbEvIdx(evIdx)
    setLbIndex(frIdx)
    setLbHistory([])
    setLbInverted(false)
    setLbOpen(true)
  }, [])

  function resetLbFilters() {
    setLbBrightness(100)
    setLbContrast(100)
    setLbRotation(0)
    setLbInverted(false)
  }

  // ── Other target species seen in the photo ───────────────────────────────
  const otherSpecies = useMemo(
    () => targetSpecies.filter((sp) => sp !== spStats?.species_name),
    [targetSpecies, spStats?.species_name],
  )
  const crossReadOnly = completed && locked

  const refreshCross = useCallback(async (siteId: string, occasion: number) => {
    try {
      const r = await api.getCross(siteId, occasion)
      setCrossByCell((prev) => ({ ...prev, [`${siteId}|${occasion}`]: r.species }))
    } catch { /* the panel just stays as it was */ }
  }, [])

  useEffect(() => {
    const ev = events[lbEvIdx]
    if (!lbOpen || !ev || otherSpecies.length === 0) return
    refreshCross(ev.siteId, ev.occasion)
  }, [lbOpen, lbEvIdx, events, otherSpecies.length, refreshCross])

  async function toggleCross(i: number) {
    const sp = otherSpecies[i]
    const ev = events[lbEvIdx]
    const frame = ev?.frames[lbIndex]
    if (!sp || !ev || !frame || crossBusy || crossReadOnly) return
    const cur = crossByCell[`${ev.siteId}|${ev.occasion}`]?.find((c) => c.scientificName === sp)
    // Already confirmed in this occasion (in its own review, or from a photo of another detection
    // event): nothing to do here, and it cannot be undone by mistake from a photo that may not show it.
    const state = crossButtonState(cur, ev.frames)
    if (state === 'confirmed' || state === 'elsewhere') return
    setCrossBusy(true)
    try {
      if (cur?.status === 'cross') {
        await api.removeCross(sp, ev.siteId, ev.occasion)
        showToast(t('gallery.cross_removed', { species: sp, site: ev.siteId, occasion: ev.occasion }), 'success')
      } else {
        const res = await api.addCross({
          species: sp, site_id: ev.siteId, occasion: ev.occasion,
          media_id: frame.mediaId, observation_id: frame.isContext ? '' : frame.obsId,
          source_species: spStats?.species_name ?? '',
        })
        if (res.added) {
          showToast(t('gallery.cross_added_outside', { species: sp, site: ev.siteId, occasion: ev.occasion }), 'warning', 7000)
        } else {
          showToast(t('gallery.cross_added', { species: sp, site: ev.siteId, occasion: ev.occasion }), 'success')
        }
      }
      await refreshCross(ev.siteId, ev.occasion)
    } catch (e) {
      showToast(e instanceof Error ? e.message : t('gallery.toast_error'), 'danger')
    } finally {
      setCrossBusy(false)
    }
  }
  toggleCrossRef.current = (i) => { toggleCross(i) }

  function decideInLb(d: Decision) {
    if (completed && locked) return
    const ev = events[lbEvIdx]
    if (!ev) return
    if (d === 'confirmed') chosenRepRef.current[ev.key] = ev.frames[lbIndex]?.burstRepObsId ?? ev.repObsId
    // Confirmed or unsure here while another species was confirmed from a photo of this event: right
    // only with animals of both species. The decision is recorded but the large view stays on the
    // card; pressing the same decision again moves on.
    const crossHere = (crossByCell[`${ev.siteId}|${ev.occasion}`] ?? [])
      .filter((c) => c.status === 'cross' && ev.frames.some((f) => f.mediaId === c.mediaID))
      .map((c) => c.scientificName)
    const conflict = !completed && d !== 'rejected' && crossHere.length > 0
    const repeated = decisionsRef.current[ev.key] === d
    setDecisions((prev) => ({ ...prev, [ev.key]: d }))
    decidedAtRef.current[ev.key] = Date.now()
    if (d !== 'rejected') dropCorrection(ev.key)
    setNeedsDecision((prev) => { const s = new Set(prev); s.delete(ev.key); return s })
    if (conflict && !repeated) {
      showToast(t('gallery.cross_conflict_toast', { species: crossHere.join(', ') }), 'warning', 7000)
      return
    }
    if (!completed) {
      // decisionsRef mirrors state as of the last render, so it doesn't
      // include the decision just made above (setDecisions hasn't
      // committed yet) -- merge it in locally, or the fallback loop below
      // (which starts at 0, unlike the same-site one) can find the event
      // we just decided and re-select itself instead of closing.
      const updated = { ...decisionsRef.current, [ev.key]: d }

      // Prefer the next undecided occasion at the same site (matches the
      // Arrow Up/Down navigation), so confirming/rejecting doesn't jump to
      // an unrelated site. Only fall back to searching the whole list once
      // the current site has no undecided occasions left.
      const siteIndices = events
        .map((e, i) => ({ i, siteId: e.siteId }))
        .filter((x) => x.siteId === ev.siteId)
      const posInSite = siteIndices.findIndex((x) => x.i === lbEvIdx)
      const from = lbEvIdx
      for (let p = posInSite + 1; p < siteIndices.length; p++) {
        const i = siteIndices[p].i
        if (!updated[events[i].key]) {
          setLbHistory((h) => [...h, from])
          setLbEvIdx(i)
          setLbIndex(0)
          return
        }
      }
      for (let i = 0; i < events.length; i++) {
        if (!updated[events[i].key]) {
          setLbHistory((h) => [...h, from])
          setLbEvIdx(i)
          setLbIndex(0)
          return
        }
      }
      setLbOpen(false)
    }
  }
  decideInLbRef.current = decideInLb

  // Back to the card decided just before (or, with no history, the previous one in the list).
  const lbCanGoBack = lbHistory.length > 0 || lbEvIdx > 0
  function lbGoBack() {
    if (lbHistory.length) {
      const prev = lbHistory[lbHistory.length - 1]
      setLbHistory((h) => h.slice(0, -1))
      setLbEvIdx(prev)
    } else if (lbEvIdx > 0) {
      setLbEvIdx(lbEvIdx - 1)
    } else {
      return
    }
    setLbIndex(0)
  }
  lbBackRef.current = lbGoBack

  // Stable identities: the cards are memoised, so a decision re-renders one card, not all of them.
  const dropCorrection = useCallback((key: string) => {
    setCorrections((prev) => { if (!(key in prev)) return prev; const c = { ...prev }; delete c[key]; return c })
  }, [])

  const setCorrection = useCallback((key: string, value: string) => {
    setCorrections((prev) => ({ ...prev, [key]: value }))
  }, [])

  const decide = useCallback((key: string, repObsId: string, d: Decision) => {
    if (d === 'confirmed') chosenRepRef.current[key] = repObsId
    setDecisions((prev) => ({ ...prev, [key]: d }))
    decidedAtRef.current[key] = Date.now()
    if (d !== 'rejected') dropCorrection(key)
    setNeedsDecision((prev) => { const s = new Set(prev); s.delete(key); return s })
  }, [dropCorrection])

  // Confirm every card of the location being shown (the page shows one location at a time).
  function confirmAllInSite() {
    const now = Date.now()
    setDecisions((prev) => {
      const next = { ...prev }
      siteEvents.forEach((ev) => { next[ev.key] = 'confirmed'; decidedAtRef.current[ev.key] = now })
      return next
    })
    setCorrections((prev) => {
      const next = { ...prev }
      siteEvents.forEach((ev) => { delete next[ev.key] })
      return next
    })
    setNeedsDecision((prev) => {
      const s = new Set(prev)
      siteEvents.forEach((ev) => s.delete(ev.key))
      return s
    })
  }

  function goSite(i: number) {
    setSiteIdx(Math.max(0, Math.min(i, sites.length - 1)))
    gridTopRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }

  // Pending expert review: nothing has to be decided; cells left unsure stay pending.
  async function handleSettlePending() {
    if (!species) return
    setSaving(true)
    try {
      const confirmedIds = events.filter((e) => decisions[e.key] === 'confirmed').map((e) => chosenRepRef.current[e.key] ?? e.repObsId)
      const rejectedKeys = events.filter((e) => decisions[e.key] === 'rejected').map((e) => e.key)
      if (confirmedIds.length === 0 && rejectedKeys.length === 0) {
        showToast(t('gallery.pending_nothing_to_save'), 'danger')
        return
      }
      const r = await api.settlePending(species, confirmedIds, rejectedKeys)
      finishedRef.current = true                           // the server dropped the pending progress
      clearDraft(draftKey(sessionId, species, 'pending', 0))
      showToast(t('gallery.pending_saved', { confirmed: r.confirmed, rejected: r.rejected }), 'success')
      setLbOpen(false)
      setReloadKey((k) => k + 1)
    } catch (e) {
      showToast(e instanceof Error ? e.message : t('gallery.toast_error'), 'danger')
    } finally {
      setSaving(false)
    }
  }

  async function handleSave() {
    if (pendingMode) { await handleSettlePending(); return }
    const undecided = events.filter((e) => !decisions[e.key])
    if (undecided.length > 0) {
      setNeedsDecision(new Set(undecided.map((e) => e.key)))
      setSiteIdx(Math.max(0, sites.indexOf(undecided[0].siteId)))
      setTimeout(() => {
        document.querySelector(`[data-key="${CSS.escape(undecided[0].key)}"]`)
          ?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
      }, 50)
      showToast(t('gallery.needs_decision_count', { n: undecided.length }), 'warning', 6000)
      return
    }
    if (!species) return
    if (progressTimerRef.current) window.clearTimeout(progressTimerRef.current)
    setSaving(true)
    try {
      const confirmedIds = events
        .filter((e) => decisions[e.key] === 'confirmed')
        .map((e) => e.repObsId)
      const unsureIds = events
        .filter((e) => decisions[e.key] === 'unsure')
        .map((e) => e.repObsId)
      const correctionIds: Record<string, string> = {}
      events.forEach((e) => {
        const text = (corrections[e.key] ?? '').trim()
        if (decisions[e.key] === 'rejected' && text) correctionIds[e.repObsId] = text
      })
      const decisionTimes: Record<string, number> = {}
      events.forEach((e) => {
        const at = decidedAtRef.current[e.key]
        if (decisions[e.key] && at) decisionTimes[e.repObsId] = at
      })
      const result = await api.saveDecisions(species, iteration, confirmedIds, unsureIds, correctionIds, decisionTimes)
      finishedRef.current = true                           // the server dropped the progress with the round
      clearDraft(draftKey(sessionId, species, 'rounds', iteration))
      if (result.done) {
        // The rounds are over: cells with an unsure event and no event left are now pending expert review.
        const after = await api.getSpecies().catch(() => [] as SpeciesStats[])
        const nPending = after.find((x) => x.species_safe === species)?.n_pending ?? 0
        if (nPending > 0) {
          showToast(t('gallery.toast_rounds_done_pending', { n: nPending }), 'success')
          setReloadKey((k) => k + 1)                     // opens the pending cells
        } else {
          showToast(t('gallery.toast_done'), 'success')
          setTimeout(() => navigate('/species'), 1500)
        }
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

  // Go back to the last finished round (e.g. a mistake noticed afterwards). The round's decisions
  // come back as progress; the progress of the current round is kept for later.
  async function handleReopen() {
    if (!species) return
    if (!window.confirm(t('gallery.reopen_confirm'))) return
    await flushProgress()
    try {
      const r = await api.reopenRound(species)
      showToast(t('gallery.reopen_done', { n: r.iteration }), 'success')
      setCompleted(false)
      setLocked(true)
      setIteration(r.iteration)
      setReloadKey((k) => k + 1)
    } catch (e) {
      showToast(e instanceof Error ? e.message : t('gallery.toast_error'), 'danger')
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

  // One page per location.
  const { sites, bySite, indexByKey } = useMemo(() => {
    const bySite: Record<string, DetectionEvent[]> = {}
    const sites: string[] = []
    const indexByKey = new Map<string, number>()
    events.forEach((ev, i) => {
      indexByKey.set(ev.key, i)
      if (!bySite[ev.siteId]) { bySite[ev.siteId] = []; sites.push(ev.siteId) }
      bySite[ev.siteId].push(ev)
    })
    sites.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))      // easy to find in the list
    return { sites, bySite, indexByKey }
  }, [events])
  const currentSiteIdx = Math.min(siteIdx, Math.max(sites.length - 1, 0))
  const currentSite = sites[currentSiteIdx]
  const siteEvents = currentSite ? bySite[currentSite] : []

  // The page behind the large view follows the card shown in it.
  useEffect(() => {
    if (!lbOpen) return
    const ev = events[lbEvIdx]
    if (!ev) return
    const i = sites.indexOf(ev.siteId)
    if (i >= 0 && i !== siteIdx) setSiteIdx(i)
  }, [lbOpen, lbEvIdx, events, sites, siteIdx])

  const lbCurrentEv = events[lbEvIdx]
  const lbDecision  = lbCurrentEv ? decisions[lbCurrentEv.key] : undefined
  const lbReadOnly  = completed && locked

  // Progress shown beside the photos: round, decided in the round, decided at this location and
  // cells resolved for the species before the round started.
  const decidedCount = events.reduce((n, e) => n + (decisions[e.key] ? 1 : 0), 0)
  const lbSiteEvents = lbCurrentEv ? (bySite[lbCurrentEv.siteId] ?? []) : []
  const lbSiteDone = lbSiteEvents.reduce((n, e) => n + (decisions[e.key] ? 1 : 0), 0)
  const lbProgressLine = [
    completed ? '' : pendingMode ? t('gallery.pending_badge') : t('gallery.round', { n: iteration }),
    t('gallery.decided_progress', { done: decidedCount, total: events.length }),
    lbCurrentEv ? t('gallery.lb_site_progress', { site: lbCurrentEv.siteId, done: lbSiteDone, total: lbSiteEvents.length }) : '',
  ].filter(Boolean).join(' · ')
  const lbProgress = (
    <div className="rounded-lg bg-black/55 border border-white/15 px-3 py-2 text-[11px] leading-snug text-white/80" aria-label={t('gallery.lb_progress_label')}>
      <div className="mb-1 text-white/70">{t('gallery.lb_reviewing')}: <span className="italic font-semibold text-white">{spStats?.species_name ?? (species ?? '').replace(/_/g, ' ')}</span></div>
      {!completed && <div className="font-semibold text-white">{pendingMode ? t('gallery.pending_badge') : t('gallery.round', { n: iteration })}</div>}
      <div>{t('gallery.decided_progress', { done: decidedCount, total: events.length })}</div>
      <div className="h-1.5 rounded bg-white/15 my-1 overflow-hidden">
        <div className="h-full bg-sky-500" style={{ width: `${events.length ? Math.round(decidedCount / events.length * 100) : 0}%` }} />
      </div>
      {lbCurrentEv && (
        <div>{t('gallery.lb_site_progress', { site: lbCurrentEv.siteId, done: lbSiteDone, total: lbSiteEvents.length })}</div>
      )}
      {!completed && spStats && spStats.n_total_combos > 0 && (
        <div className="text-white/60">{t('gallery.lb_species_progress', { resolved: spStats.n_resolved, total: spStats.n_total_combos })}</div>
      )}
    </div>
  )
  const crossCellKey = lbCurrentEv ? `${lbCurrentEv.siteId}|${lbCurrentEv.occasion}` : ''
  const crossHere = lbCurrentEv
    ? (crossByCell[crossCellKey] ?? [])
        .filter((c) => c.status === 'cross' && lbCurrentEv.frames.some((f) => f.mediaId === c.mediaID))
        .map((c) => c.scientificName)
    : []
  const lbCrossPanel = otherSpecies.length > 0 && lbCurrentEv ? (
    <div className="flex flex-col gap-1.5" data-testid="lb-cross">
      <span className="text-[11px] leading-tight text-white/70 mb-0.5">{t('gallery.cross_title')}</span>
      {otherSpecies.map((sp, i) => {
        const st = crossByCell[crossCellKey]?.find((c) => c.scientificName === sp)
        const status = crossButtonState(st, lbCurrentEv.frames)
        const already = status === 'confirmed' || status === 'elsewhere'
        // The classifier did not flag this species here: a confirmation is recorded apart
        // (not in the verified history).
        const outside = st?.has_candidates === false
        return (
          <button
            key={sp}
            className={`px-2 py-1.5 text-left text-sm rounded transition-colors flex items-center gap-1.5 disabled:opacity-50 ${
              status === 'cross'
                ? 'bg-sky-600 text-white hover:bg-sky-700'
                : already
                ? 'border border-white/20 bg-white/10 text-white/60 cursor-default'
                : 'border border-white/40 bg-black/40 text-white/90 hover:bg-sky-600 hover:border-sky-600 hover:text-white'
            }`}
            onClick={() => toggleCross(i)}
            disabled={crossReadOnly || already}
            title={status === 'confirmed'
              ? t('gallery.cross_already', { species: sp })
              : status === 'elsewhere'
              ? t('gallery.cross_elsewhere_tooltip', { species: sp })
              : status === 'cross'
              ? t('gallery.cross_undo_tooltip', { species: sp })
              : outside
              ? t('gallery.cross_outside_tooltip', { species: sp })
              : t('gallery.cross_tooltip', { species: sp, site: lbCurrentEv.siteId, occasion: lbCurrentEv.occasion })}
          >
            {i < 9 && <span className="text-[10px] opacity-60 font-mono w-3">{i + 1}</span>}
            <span className="flex-1 leading-tight break-words">
              <span className="italic">{sp}</span>
              {already && <span className="block text-[10px] not-italic">{t('gallery.cross_elsewhere')}</span>}
              {!already && outside && (
                <span className="block text-[10px] not-italic opacity-70" data-testid="cross-outside">{t('gallery.cross_outside')}</span>
              )}
            </span>
            {status === 'cross' && <span aria-hidden="true">✓</span>}
          </button>
        )
      })}
      {lbDecision !== 'rejected' && crossHere.length > 0 && (
        <p role="note" className="mt-1 text-[11px] leading-snug text-amber-300">
          {t(lbDecision === 'unsure' ? 'gallery.cross_unsure_note' : lbDecision === 'confirmed' ? 'gallery.cross_confirmed_note' : 'gallery.cross_pending_note',
             { species: crossHere.join(', ') })}
        </p>
      )}
    </div>
  ) : null
  const lbPanelWidth = otherSpecies.length > 0 ? 240 : 168
  const lbDecisionButtons = (wrapClass: string, btnClass: string) => (
    <div className={wrapClass}>
      <button
        className={`${btnClass} text-base rounded font-medium transition-colors disabled:opacity-50 ${
          lbDecision === 'confirmed'
            ? 'bg-emerald-600 text-white hover:bg-emerald-700'
            : 'border border-emerald-600 bg-black/40 text-emerald-400 hover:bg-emerald-600 hover:text-white'
        }`}
        onClick={() => decideInLb('confirmed')}
        disabled={lbReadOnly}
      >
        {t('gallery.confirmed_btn')} <span className="opacity-60">(Y)</span>
      </button>
      <button
        className={`${btnClass} text-base rounded font-medium transition-colors disabled:opacity-50 ${
          lbDecision === 'rejected'
            ? 'bg-red-600 text-white hover:bg-red-700'
            : 'border border-red-600 bg-black/40 text-red-400 hover:bg-red-600 hover:text-white'
        }`}
        onClick={() => decideInLb('rejected')}
        disabled={lbReadOnly}
      >
        {t('gallery.rejected_btn')} <span className="opacity-60">(N)</span>
      </button>
      {!completed && (
        <button
          className={`${btnClass} text-base rounded font-medium transition-colors disabled:opacity-50 ${
            lbDecision === 'unsure'
              ? 'bg-amber-600 text-white hover:bg-amber-700'
              : 'border border-amber-600 bg-black/40 text-amber-400 hover:bg-amber-600 hover:text-white'
          }`}
          onClick={() => decideInLb('unsure')}
          disabled={lbReadOnly}
          title={t('gallery.unsure_hint')}
        >
          {t('gallery.unsure_btn')} <span className="opacity-60">(U)</span>
        </button>
      )}
    </div>
  )
  const lbCorrectionInput = recordRejection && !completed && lbDecision === 'rejected' && lbCurrentEv ? (
    <input
      type="text"
      list="actual-species-list"
      className="w-full px-3 py-2 text-sm rounded border border-zinc-500 bg-black/50 text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
      style={{ maxWidth: 420 }}
      placeholder={t('gallery.actual_species_placeholder')}
      title={t('gallery.actual_species_hint')}
      value={corrections[lbCurrentEv.key] ?? ''}
      onChange={(e) => setCorrection(lbCurrentEv.key, e.target.value)}
      onKeyDown={(e) => e.stopPropagation()}
      readOnly={lbReadOnly}
    />
  ) : null

  const siteLabel = (site: string) => {
    const evs = bySite[site] ?? []
    const done = evs.reduce((n, e) => n + (decisions[e.key] ? 1 : 0), 0)
    return `${site}  ·  ${done}/${evs.length}`
  }

  const siteNav = sites.length > 1 && (
    <div className="flex flex-wrap items-center gap-2 mb-3">
      <button
        className="px-3 py-1.5 text-sm rounded bg-zinc-700 text-white hover:bg-zinc-600 disabled:opacity-40"
        onClick={() => goSite(currentSiteIdx - 1)}
        disabled={currentSiteIdx === 0}
      >
        ‹ {t('gallery.prev_site')}
      </button>
      <select
        aria-label={t('gallery.location')}
        className="px-2 py-1.5 text-sm rounded border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100"
        value={currentSiteIdx}
        onChange={(e) => goSite(Number(e.target.value))}
      >
        {sites.map((s, i) => <option key={s} value={i}>{siteLabel(s)}</option>)}
      </select>
      <button
        className="px-3 py-1.5 text-sm rounded bg-zinc-700 text-white hover:bg-zinc-600 disabled:opacity-40"
        onClick={() => goSite(currentSiteIdx + 1)}
        disabled={currentSiteIdx >= sites.length - 1}
      >
        {t('gallery.next_site')} ›
      </button>
      <span className="text-sm text-zinc-500 dark:text-zinc-400">
        {t('gallery.site_position', { i: currentSiteIdx + 1, n: sites.length })}
        {' · '}
        {t('gallery.decided_progress', { done: decidedCount, total: events.length })}
      </span>
    </div>
  )

  return (
    <div className="max-w-screen-xl mx-auto px-4 py-4">
      <div className="mb-3" ref={gridTopRef}>
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-baseline gap-3">
            <h2 className="text-2xl font-semibold mb-0">
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
            ) : pendingMode ? (
              <span className="px-2 py-0.5 text-xs font-medium bg-amber-500 text-white rounded-full">
                {t('gallery.pending_badge')}
                {events.length > 0 && ` · ${t('gallery.round', { n: Math.min(...events.map((e) => e.pendingIndex ?? 1)) })}`}
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <span className="px-2 py-0.5 text-xs font-medium bg-zinc-600 text-zinc-200 rounded-full">
                  {t('gallery.round', { n: iteration })}
                </span>
                {iteration > 1 && (
                  <button
                    className="px-2 py-0.5 text-xs border border-zinc-400 dark:border-zinc-600 text-zinc-700 dark:text-zinc-300 rounded hover:bg-zinc-100 dark:hover:bg-zinc-700"
                    title={t('gallery.reopen_tooltip', { n: iteration - 1 })}
                    onClick={handleReopen}
                  >
                    ← {t('gallery.reopen', { n: iteration - 1 })}
                  </button>
                )}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
          {events.some((e) => e.frames.some((f) => !!f.boxes)) && (
            <label
              className="flex items-center gap-1.5 text-sm text-zinc-600 dark:text-zinc-300 cursor-pointer select-none"
              title={t('gallery.show_boxes_hint')}
            >
              <input type="checkbox" checked={showBoxes} onChange={(e) => toggleBoxes(e.target.checked)} />
              {t('gallery.show_boxes')}
            </label>
          )}
          {events.length > 0 && (
            <button
              className="px-4 py-1.5 text-sm rounded transition-colors border border-zinc-500 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-700"
              title={t('gallery.open_large_view_hint')}
              onClick={() => {
                const firstUndecided = completed ? -1 : events.findIndex((e) => !decisions[e.key])
                openLightbox(firstUndecided >= 0 ? firstUndecided : 0, 0)
              }}
            >
              {t('gallery.open_large_view')}
            </button>
          )}
          <button
            className="px-4 py-1.5 text-sm rounded transition-colors bg-zinc-700 text-white hover:bg-zinc-600 flex items-center gap-1.5"
            onClick={() => navigate(-1)}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M10 3L5 8l5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            {t('gallery.back')}
          </button>
          </div>
        </div>

        {!completed && !pendingMode && reviewParams && (
          <p
            className="text-zinc-500 dark:text-zinc-400 text-sm mb-3"
            dangerouslySetInnerHTML={{
              __html: t(reviewParams.occasion_hours > 0 ? 'gallery.intro_hint_hours' : 'gallery.intro_hint', {
                gap: reviewParams.gap_seconds,
                days: reviewParams.occasion_days,
                count: reviewParams.occasion_hours > 0 ? reviewParams.occasion_hours : undefined,
                minScore: effectiveMinScore(reviewParams.min_score, reviewParams.min_score_by_species, spStats?.species_name),
                species: spStats?.species_name ?? species?.replace(/_/g, ' '),
              }),
            }}
          />
        )}

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
                {(spStats.n_pending ?? 0) > 0 && (
                  <>
                    {' · '}
                    <span className="text-amber-500 font-semibold">{t('gallery.pending_count', { n: spStats.n_pending })}</span>
                  </>
                )}
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
                  {pendingMode
                    ? t('gallery.pending_hint')
                    : completed
                    ? (locked ? t('gallery.review_hint_locked') : t('gallery.review_hint_unlocked'))
                    : t(reviewParams?.review_order === 'time' ? 'gallery.round_hint_time' : 'gallery.round_hint', { n: iteration })}
                  {!completed && !pendingMode && (
                    <><br /><strong>{t('gallery.open_tip_title')}</strong> {t('gallery.open_tip')}</>
                  )}
                </span>
              </div>
            </>
          )
        })()}
      </div>

      {/* Floating action buttons */}
      {!completed && (
        <div className="fixed bottom-6 right-6 z-[200] flex gap-2">
          {/* Not in the pending expert review: every event there was unsure or rejected, confirming them all would defeat it */}
          {!pendingMode && (
            <button
              className="px-5 py-2.5 bg-zinc-600 text-white rounded-lg shadow-xl hover:bg-zinc-500 transition-colors disabled:opacity-50 flex items-center gap-2"
              onClick={confirmAllInSite}
              disabled={saving || siteEvents.length === 0}
              title={t('gallery.confirm_all_site_tooltip')}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M2 8.5L5.5 12L10 6M5 5.5L8.5 9L13 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              {t('gallery.confirm_all_site')}
            </button>
          )}
          <button
            className="px-5 py-2.5 bg-blue-600 text-white rounded-lg shadow-xl hover:bg-blue-700 transition-colors disabled:opacity-50 flex flex-col items-center leading-tight"
            onClick={() => flushProgress({ announce: true })}
            disabled={saving || progressState === 'saving'}
            title={t('gallery.save_progress_hint')}
          >
            <span>{t('gallery.save_progress')}</span>
            <span className="text-[10px] opacity-80">
              {progressState === 'dirty' ? t('gallery.progress_unsaved')
                : progressState === 'saving' ? t('gallery.saving')
                : progressState === 'error' ? t('gallery.progress_error')
                : progressAt ? t('gallery.progress_saved_at', { time: new Date(progressAt).toLocaleTimeString() })
                : t('gallery.progress_none')}
            </span>
          </button>
          <button
            className="px-5 py-2.5 bg-emerald-600 text-white rounded-lg shadow-xl hover:bg-emerald-700 transition-colors disabled:opacity-50 flex items-center gap-2"
            onClick={handleSave}
            title={pendingMode ? undefined : t('gallery.finish_round_tooltip')}
            disabled={saving}
          >
            {saving ? <Spinner sm /> : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M13 13.5H3a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5h8l2.5 2.5V13a.5.5 0 0 1-.5.5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M5 13.5V9.5h6v4M5 2.5v3h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            )}
            {saving ? t('gallery.saving') : pendingMode ? t('gallery.pending_save') : t('gallery.finish_round')}
          </button>
        </div>
      )}

      {completed && !locked && (
        <div className="fixed bottom-6 right-6 z-[200]">
          <button
            className="px-5 py-2.5 bg-amber-500 text-white rounded-lg shadow-xl hover:bg-amber-600 transition-colors disabled:opacity-50 flex items-center gap-2"
            onClick={handleUpdateDecisions}
            disabled={saving}
          >
            {saving && <Spinner sm />}
            {saving ? t('gallery.updating') : t('gallery.update_decisions')}
          </button>
        </div>
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
          {t('gallery.no_events')}
        </div>
      ) : (
        <>
          {siteNav}
          <div key={currentSite} className="mb-4 border border-zinc-700 rounded-lg p-3">
            <h5 className="mb-3 flex items-center text-base font-semibold">
              <span className="text-zinc-500 dark:text-zinc-400 font-normal">{t('gallery.location')}</span>
              <span className="ml-2">{currentSite}</span>
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
              {siteEvents.length > 0 && (
                <button type="button"
                  className="ml-auto px-3 py-1 text-sm font-normal rounded-md bg-blue-600 text-white hover:bg-blue-500"
                  onClick={() => {
                    const first = (completed ? undefined : siteEvents.find((e) => !decisions[e.key])) ?? siteEvents[0]
                    openLightbox(indexByKey.get(first.key) ?? 0, 0)
                  }}>
                  ⤢ {t('gallery.open_large')}
                </button>
              )}
            </h5>
            <hr className="border-zinc-700 mt-0 mb-3" />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '1rem' }}>
              {siteEvents.map((ev) => (
                <div key={ev.key} data-key={ev.key}>
                  <EventCard
                    event={ev}
                    decision={decisions[ev.key] ?? null}
                    needsDecision={needsDecision.has(ev.key)}
                    onDecide={decide}
                    allowUnsure={!completed}
                    showBoxes={showBoxes}
                    recordCorrection={recordRejection && !completed}
                    correction={corrections[ev.key] ?? ''}
                    onCorrect={setCorrection}
                    onOpenLightbox={openLightbox}
                    eventIdx={indexByKey.get(ev.key) ?? 0}
                    readOnly={completed && locked}
                  />
                </div>
              ))}
            </div>
          </div>
          {currentSiteIdx < sites.length - 1 && (
            <div className="flex justify-center mb-24">
              <button
                className="px-5 py-2 text-sm rounded bg-blue-600 text-white hover:bg-blue-700"
                onClick={() => goSite(currentSiteIdx + 1)}
              >
                {t('gallery.next_site_cta', { site: sites[currentSiteIdx + 1] })} ›
              </button>
            </div>
          )}
        </>
      )}

      <style>{`.yarl__slide_image {
        width: 100%; height: 100%; object-fit: contain;
        max-width: 100% !important; max-height: 100% !important;
        filter: brightness(${lbBrightness}%) contrast(${lbContrast}%)${lbInverted ? ' invert(1)' : ''} !important;
        ${lbRotation !== 0 ? `transform: rotate(${lbRotation}deg) !important; ${lbRotation % 180 !== 0 ? 'max-width: 80vh !important; max-height: 80vw !important;' : ''}` : ''}
      }
      .yarl__slide_title {
        white-space: normal !important;
        overflow: visible !important;
      }`}</style>

      <datalist id="actual-species-list">
        {taxa.map((n) => <option key={n} value={n} />)}
      </datalist>
      <YARLightbox
        key={lbEvIdx}
        open={lbOpen}
        close={() => { setLbOpen(false); resetLbFilters() }}
        index={lbIndex}
        slides={lbSlides}
        plugins={[Zoom, Captions]}
        carousel={{ finite: true, preload: 2 }}
        // No slide / fade transitions: the frames of an event are compared one after another,
        // so they must switch instantly.
        animation={{ fade: 0, swipe: 0, navigation: 0 }}
        // Photos are scaled up to fill the screen (see the .yarl__slide_image rule); the padding
        // leaves room for the title above and the decision buttons below.
        styles={lbNarrow
          ? { slide: { padding: '48px 56px 150px' } }
          : { slide: { padding: `48px 56px 56px ${lbPanelWidth + 56}px` }, navigationPrev: { left: lbPanelWidth + 44 } }}
        controller={{ ref: lbControllerRef }}
        on={{ view: ({ index }) => { setLbIndex(index); resetLbFilters() } }}
        zoom={{ maxZoomPixelRatio: 8, scrollToZoom: true }}
        captions={{ showToggle: false }}
        render={{
          controls: () => lbCurrentEv && (
            <>
              {!lbNarrow && (
                <div
                  className="absolute left-6 top-14 bottom-6 flex flex-col gap-3 overflow-y-auto"
                  style={{ zIndex: 10000, width: lbPanelWidth }}
                  data-testid="lb-panel"
                >
                  {lbProgress}
                  {lbCrossPanel}
                  <div className="flex flex-col gap-2">
                    <span className="text-[11px] leading-tight text-white/70">{t('gallery.lb_decision_title')}</span>
                    {lbDecisionButtons('flex flex-col gap-2', 'w-full py-3')}
                  </div>
                  {lbCorrectionInput}
                  <button
                    type="button"
                    onClick={lbGoBack}
                    disabled={!lbCanGoBack}
                    title={t('gallery.prev_card_tooltip')}
                    className="w-full py-1.5 text-xs rounded border border-white/40 bg-black/50 text-white/90 hover:bg-white/15 disabled:opacity-30 disabled:hover:bg-black/50"
                  >
                    ↶ {t('gallery.prev_card')} <span className="opacity-60">(⌫)</span>
                  </button>
                  <p className="text-[10px] leading-snug text-white/50">{t('gallery.lb_keys_tip')}</p>
                </div>
              )}
              <div
                className="absolute bottom-0 right-0 flex flex-col items-center gap-3 px-4 pb-3"
                style={{ zIndex: 10000, left: lbNarrow ? 0 : lbPanelWidth + 40 }}
              >
                {lbCurrentEv.frames.length > 1 && (
                  <div className="flex gap-1">
                    {lbCurrentEv.frames.map((_, i) => (
                      <button
                        key={i}
                        aria-label={`${i + 1}/${lbCurrentEv.frames.length}`}
                        onClick={() => {
                          const delta = i - lbIndex
                          if (delta === 0) return
                          if (delta > 0) lbControllerRef.current?.next({ count: delta })
                          else lbControllerRef.current?.prev({ count: -delta })
                        }}
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: '50%',
                          padding: 0,
                          border: 'none',
                          cursor: 'pointer',
                          background: i === lbIndex ? '#007aff' : 'rgba(255,255,255,.3)',
                        }}
                      />
                    ))}
                  </div>
                )}
                {lbNarrow && (
                  <>
                    <div className="w-full text-center text-[11px] text-white/70">{lbProgressLine}</div>
                    {lbCrossPanel && <div className="w-full" style={{ maxWidth: 480 }}>{lbCrossPanel}</div>}
                    <div className="flex gap-2 w-full" style={{ maxWidth: 480 }}>
                      {lbDecisionButtons('flex gap-3 flex-1', 'flex-1 py-2.5')}
                      <button
                        type="button"
                        onClick={lbGoBack}
                        disabled={!lbCanGoBack}
                        title={t('gallery.prev_card_tooltip')}
                        aria-label={t('gallery.prev_card')}
                        className="px-3 rounded border border-white/40 bg-black/50 text-white/90 disabled:opacity-30"
                      >
                        ↶
                      </button>
                    </div>
                    {lbCorrectionInput}
                  </>
                )}
              </div>
            </>
          ),
        }}
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
            'close',
          ],
        }}
      />

      {toast && (
        <div className={`fixed bottom-0 right-0 m-3 z-[2000] px-4 py-3 rounded-lg text-white shadow-lg ${
          toast.type === 'success' ? 'bg-emerald-600' : toast.type === 'warning' ? 'bg-amber-600' : 'bg-red-600'
        }`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
