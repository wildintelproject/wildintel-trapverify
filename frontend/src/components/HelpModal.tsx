import { useTranslation } from 'react-i18next'

interface Props { onClose: () => void }

export default function HelpModal({ onClose }: Props) {
  const { t } = useTranslation()

  return (
    <>
      <div
        onClick={onClose}
        className="fixed inset-0 bg-black/60 z-[1040]"
      />
      <div
        role="dialog"
        aria-modal="true"
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[1050] w-full max-w-[620px] max-h-[85vh] overflow-y-auto rounded-lg shadow-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-200 dark:border-zinc-700">
          <strong className="text-zinc-900 dark:text-zinc-100">{t('help.title')}</strong>
          <button
            className="w-7 h-7 flex items-center justify-center text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 text-xl rounded transition-colors"
            onClick={onClose}
            aria-label="Cerrar"
          >
            ×
          </button>
        </div>

        <div className="p-4 text-sm space-y-4">
          <div>
            <h6 className="font-bold mb-1 text-zinc-900 dark:text-zinc-100">{t('help.what_title')}</h6>
            <p className="text-zinc-500 dark:text-zinc-400">{t('help.what_body')}</p>
          </div>

          <div>
            <h6 className="font-bold mb-1 text-zinc-900 dark:text-zinc-100">{t('help.workflow_title')}</h6>
            <ol className="text-zinc-500 dark:text-zinc-400 pl-5 space-y-1 list-decimal">
              {(t('help.workflow_steps', { returnObjects: true }) as string[]).map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </div>

          <div>
            <h6 className="font-bold mb-1 text-zinc-900 dark:text-zinc-100">{t('help.concepts_title')}</h6>
            <dl className="text-zinc-500 dark:text-zinc-400 space-y-2">
              {(t('help.concepts', { returnObjects: true }) as { term: string; def: string }[]).map((c, i) => (
                <div key={i}>
                  <dt className="font-medium text-zinc-700 dark:text-zinc-300">{c.term}</dt>
                  <dd className="mb-0">{c.def}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div>
            <h6 className="font-bold mb-1 text-zinc-900 dark:text-zinc-100">{t('help.decisions_title')}</h6>
            <p className="text-zinc-500 dark:text-zinc-400 mb-0">{t('help.decisions_body')}</p>
          </div>
        </div>

        <div className="flex justify-end px-4 py-3 border-t border-zinc-200 dark:border-zinc-700">
          <button
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 transition-colors"
            onClick={onClose}
          >
            {t('help.close')}
          </button>
        </div>
      </div>
    </>
  )
}
