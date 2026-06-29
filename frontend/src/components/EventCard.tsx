import { Swiper, SwiperSlide } from 'swiper/react'
import { Navigation, Pagination } from 'swiper/modules'
import { useTranslation } from 'react-i18next'
import 'swiper/css'
import 'swiper/css/navigation'
import 'swiper/css/pagination'
import type { DetectionEvent } from '../types'

interface Props {
  event: DetectionEvent
  decision: 'confirmed' | 'rejected' | null
  needsDecision: boolean
  onDecide: (key: string, repObsId: string, d: 'confirmed' | 'rejected') => void
  onOpenLightbox: (eventIdx: number, frameIdx: number) => void
  eventIdx: number
  readOnly?: boolean
}

export default function EventCard({
  event,
  decision,
  needsDecision,
  onDecide,
  onOpenLightbox,
  eventIdx,
  readOnly = false,
}: Props) {
  const { t } = useTranslation()

  const borderClass = decision === 'confirmed'
    ? 'border-2 border-emerald-500'
    : decision === 'rejected'
    ? 'border-2 border-red-500'
    : needsDecision
    ? 'border-2 border-amber-400'
    : 'border border-zinc-700'

  return (
    <div className={`rounded-lg overflow-hidden bg-zinc-900 text-zinc-100 ${borderClass}`}>
      <div className="relative" style={{ aspectRatio: '16/10', background: '#000' }}>
        <Swiper
          modules={[Navigation, Pagination]}
          navigation={event.frames.length > 1}
          pagination={event.frames.length > 1 ? { clickable: true } : false}
          slidesPerView={1}
          style={{ width: '100%', height: '100%' }}
        >
          {event.frames.map((frame, i) => (
            <SwiperSlide key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <img
                src={frame.img}
                alt=""
                style={{ width: '100%', height: '100%', objectFit: 'contain', cursor: 'pointer' }}
                onClick={() => onOpenLightbox(eventIdx, i)}
                loading="lazy"
              />
              <div
                className="absolute bottom-0 left-0 right-0 flex justify-between px-2 py-1"
                style={{
                  background: 'linear-gradient(transparent, rgba(0,0,0,.8))',
                  fontSize: 11,
                  pointerEvents: 'none',
                  zIndex: 10,
                }}
              >
                <span>{frame.ts}</span>
                <span className="bg-black/50 px-1.5 py-0.5 rounded text-xs">{frame.prob.toFixed(2)}</span>
              </div>
            </SwiperSlide>
          ))}
        </Swiper>

        <span
          className="absolute top-0 right-0 m-1 flex flex-col items-end bg-black/75 px-1.5 py-0.5 rounded"
          style={{ zIndex: 20, fontSize: 11, gap: 2 }}
        >
          <span>{t('gallery.occasion_label', { n: event.occasion })}</span>
          <span>{t('gallery.sequence', { rank: event.rank, total: event.totalSeqs })}</span>
        </span>

        <button
          className="absolute top-0 left-0 m-1 bg-black/50 text-white text-sm px-1.5 py-0.5 rounded opacity-70 hover:opacity-100 transition-opacity"
          style={{ zIndex: 20 }}
          title={t('gallery.zoom')}
          onClick={() => onOpenLightbox(eventIdx, 0)}
        >
          ⊕
        </button>
      </div>

      <div className="flex gap-2 p-2" style={{ opacity: readOnly ? 0.5 : 1 }}>
        <button
          className={`flex-1 py-1.5 text-sm rounded font-medium transition-colors disabled:opacity-50 ${
            decision === 'confirmed'
              ? 'bg-emerald-600 text-white hover:bg-emerald-700'
              : 'border border-emerald-600 text-emerald-400 hover:bg-emerald-600 hover:text-white'
          }`}
          onClick={() => onDecide(event.key, event.repObsId, 'confirmed')}
          disabled={readOnly}
        >
          {t('gallery.confirmed_btn')}
        </button>
        <button
          className={`flex-1 py-1.5 text-sm rounded font-medium transition-colors disabled:opacity-50 ${
            decision === 'rejected'
              ? 'bg-red-600 text-white hover:bg-red-700'
              : 'border border-red-600 text-red-400 hover:bg-red-600 hover:text-white'
          }`}
          onClick={() => onDecide(event.key, event.repObsId, 'rejected')}
          disabled={readOnly}
        >
          {t('gallery.rejected_btn')}
        </button>
      </div>
    </div>
  )
}
