import { useTranslation } from 'react-i18next'

interface Props {
  latest: string
  releaseUrl: string
  onDismiss: () => void
}

export default function UpdateBanner({ latest, releaseUrl, onDismiss }: Props) {
  const { t } = useTranslation()

  return (
    <div className="bg-amber-50 dark:bg-amber-900/30 border-b border-amber-200 dark:border-amber-700">
      <div className="max-w-screen-2xl mx-auto px-4 py-2 flex items-center gap-3 text-sm text-amber-800 dark:text-amber-200">
        <span className="flex-1">
          {t('update.available', { latest })}
        </span>
        <a
          href={releaseUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="px-3 py-1 bg-amber-500 hover:bg-amber-600 text-white rounded text-xs font-medium no-underline transition-colors"
        >
          {t('update.download')}
        </a>
        <button
          onClick={onDismiss}
          className="px-2 py-1 text-amber-600 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-100 text-xs transition-colors"
        >
          {t('update.dismiss')}
        </button>
      </div>
    </div>
  )
}
