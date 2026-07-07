import { useTranslation } from 'react-i18next'

export default function ConnectionBanner() {
  const { t } = useTranslation()

  return (
    <div className="bg-amber-50 dark:bg-amber-900/30 border-b border-amber-200 dark:border-amber-700">
      <div className="max-w-screen-2xl mx-auto px-4 py-2 flex items-center gap-2.5 text-sm text-amber-800 dark:text-amber-200">
        <span className="w-3.5 h-3.5 border-2 border-amber-600 dark:border-amber-300 border-t-transparent rounded-full animate-spin flex-shrink-0" />
        <span>{t('connection.lost')}</span>
      </div>
    </div>
  )
}
