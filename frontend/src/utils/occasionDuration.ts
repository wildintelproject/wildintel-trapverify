import type { TFunction } from 'i18next'

/** "5 days" / "1 hour": the length of a sampling occasion, for sentences. */
export function occasionDuration(t: TFunction, days: number, hours?: number | null): string {
  return hours && hours > 0
    ? t('duration.hours', { count: hours })
    : t('duration.days', { count: days })
}
