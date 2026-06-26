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
  const borderColor = decision === 'confirmed'
    ? '2px solid #198754'
    : decision === 'rejected'
    ? '2px solid #dc3545'
    : needsDecision
    ? '2px solid #ffc107'
    : '1px solid #444'

  return (
    <div className="card bg-dark text-white" style={{ border: borderColor }}>
      <div className="position-relative" style={{ aspectRatio: '16/10', background: '#000' }}>
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
              {/* Overlay info */}
              <div
                className="position-absolute bottom-0 start-0 end-0 d-flex justify-content-between px-2 py-1"
                style={{
                  background: 'linear-gradient(transparent, rgba(0,0,0,.8))',
                  fontSize: 11,
                  pointerEvents: 'none',
                  zIndex: 10,
                }}
              >
                <span>{frame.ts}</span>
                <span className="badge bg-dark bg-opacity-50">{frame.prob.toFixed(2)}</span>
              </div>
            </SwiperSlide>
          ))}
        </Swiper>

        {/* Período de muestreo + secuencia */}
        <span
          className="badge bg-dark bg-opacity-75 position-absolute top-0 end-0 m-1 d-flex flex-column align-items-end"
          style={{ zIndex: 20, fontSize: 11, gap: 2 }}
        >
          <span>{t('gallery.occasion_label', { n: event.occasion })}</span>
          <span>{t('gallery.sequence', { rank: event.rank, total: event.totalSeqs })}</span>
        </span>

        {/* Zoom button */}
        <button
          className="btn btn-sm btn-dark bg-opacity-50 position-absolute top-0 start-0 m-1"
          style={{ zIndex: 20, opacity: 0.7 }}
          title={t('gallery.zoom')}
          onClick={() => onOpenLightbox(eventIdx, 0)}
        >
          ⊕
        </button>
      </div>

      {/* Acción */}
      <div className="d-flex gap-2 p-2" style={{ opacity: readOnly ? 0.5 : 1 }}>
        <button
          className={`btn btn-sm flex-fill ${decision === 'confirmed' ? 'btn-success' : 'btn-outline-success'}`}
          onClick={() => onDecide(event.key, event.repObsId, 'confirmed')}
          disabled={readOnly}
        >
          {t('gallery.confirmed_btn')}
        </button>
        <button
          className={`btn btn-sm flex-fill ${decision === 'rejected' ? 'btn-danger' : 'btn-outline-danger'}`}
          onClick={() => onDecide(event.key, event.repObsId, 'rejected')}
          disabled={readOnly}
        >
          {t('gallery.rejected_btn')}
        </button>
      </div>
    </div>
  )
}
