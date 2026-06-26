import { useTranslation } from 'react-i18next'

interface Props { onClose: () => void }

export default function HelpModal({ onClose }: Props) {
  const { t } = useTranslation()

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,.6)',
          zIndex: 1040,
        }}
      />

      {/* Modal */}
      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: 'fixed',
          top: '50%', left: '50%',
          transform: 'translate(-50%,-50%)',
          zIndex: 1050,
          width: '100%',
          maxWidth: 620,
          maxHeight: '85vh',
          overflowY: 'auto',
          borderRadius: 8,
        }}
        className="card shadow-lg"
      >
        <div className="card-header d-flex align-items-center justify-content-between">
          <strong>{t('help.title')}</strong>
          <button className="btn-close" onClick={onClose} aria-label="Cerrar" />
        </div>
        <div className="card-body" style={{ fontSize: 14.5 }}>

          <h6 className="fw-bold">{t('help.what_title')}</h6>
          <p className="text-body-secondary">{t('help.what_body')}</p>

          <h6 className="fw-bold">{t('help.workflow_title')}</h6>
          <ol className="text-body-secondary">
            {(t('help.workflow_steps', { returnObjects: true }) as string[]).map((s, i) => (
              <li key={i} className="mb-1">{s}</li>
            ))}
          </ol>

          <h6 className="fw-bold">{t('help.concepts_title')}</h6>
          <dl className="text-body-secondary">
            {(t('help.concepts', { returnObjects: true }) as { term: string; def: string }[]).map((c, i) => (
              <div key={i} className="mb-2">
                <dt className="text-body">{c.term}</dt>
                <dd className="mb-0">{c.def}</dd>
              </div>
            ))}
          </dl>

          <h6 className="fw-bold">{t('help.decisions_title')}</h6>
          <p className="text-body-secondary mb-0">{t('help.decisions_body')}</p>
        </div>
        <div className="card-footer text-end">
          <button className="btn btn-primary btn-sm" onClick={onClose}>
            {t('help.close')}
          </button>
        </div>
      </div>
    </>
  )
}
