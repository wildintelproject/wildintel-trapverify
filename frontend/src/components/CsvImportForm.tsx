import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import DirectoryPicker from './DirectoryPicker'

interface Props {
  onConverted: (camtrapDir: string) => void
  onBack?: () => void
}

const NONANIMAL = new Set(['empty', 'vide', 'blank', 'human', 'humain', 'person', 'undefined', 'unknown'])

function SmallSpinner() {
  return <span className="inline-block w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
}

const selectClass =
  'block w-full rounded border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500'
const inputClass =
  'flex-1 min-w-0 block rounded-l border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500'
const browseBtn =
  'px-3 py-2 text-sm rounded-r border border-l-0 border-zinc-300 dark:border-zinc-600 bg-zinc-100 dark:bg-zinc-700 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-600 transition-colors whitespace-nowrap'
const labelClass = 'block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1'
const hintClass  = 'mt-1 text-xs text-zinc-500 dark:text-zinc-400'

export default function CsvImportForm({ onConverted, onBack }: Props) {
  const { t } = useTranslation()

  const [csvPath,      setCsvPath]      = useState('')
  const [imageBaseDir, setImageBaseDir] = useState('')
  const [headers,      setHeaders]      = useState<string[]>([])
  const [cols,         setCols]         = useState({ filename: '', datetime: '', label: '', score: '', site: '' })
  const [labels,       setLabels]       = useState<string[]>([])
  const [speciesMap,   setSpeciesMap]   = useState<Record<string, string>>({})
  const [loadingHdr,   setLoadingHdr]   = useState(false)
  const [loadingLbl,   setLoadingLbl]   = useState(false)
  const [converting,   setConverting]   = useState(false)
  const [error,        setError]        = useState<string | null>(null)
  const [picker,       setPicker]       = useState<'csv' | 'imgdir' | null>(null)

  useEffect(() => {
    if (!csvPath) { setHeaders([]); setCols({ filename: '', datetime: '', label: '', score: '', site: '' }); setLabels([]); setSpeciesMap({}); return }
    setLoadingHdr(true)
    setError(null)
    api.csvHeaders(csvPath)
      .then(r => setHeaders(r.columns))
      .catch(e => { setHeaders([]); setError(e instanceof Error ? e.message : String(e)) })
      .finally(() => setLoadingHdr(false))
  }, [csvPath])

  useEffect(() => {
    if (!csvPath || !cols.label) { setLabels([]); setSpeciesMap({}); return }
    setLoadingLbl(true)
    api.csvLabels(csvPath, cols.label)
      .then(r => { setLabels(r.labels); setSpeciesMap(r.prefilled) })
      .catch(() => setLabels([]))
      .finally(() => setLoadingLbl(false))
  }, [csvPath, cols.label])

  async function handleConvert() {
    setConverting(true)
    setError(null)
    try {
      const { camtrap_dir } = await api.convertCsv({
        csv_path:      csvPath,
        col_filename:  cols.filename,
        col_datetime:  cols.datetime,
        col_label:     cols.label,
        col_score:     cols.score  || null,
        col_site:      cols.site   || null,
        species_map:   speciesMap,
        image_base_dir: imageBaseDir || null,
      })
      onConverted(camtrap_dir)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setConverting(false)
    }
  }

  function setCol(key: keyof typeof cols, value: string) {
    setCols(c => ({ ...c, [key]: value }))
  }

  function autofill() {
    setSpeciesMap(prev => {
      const next = { ...prev }
      for (const lbl of labels) {
        if (!next[lbl]) {
          // Capitalize first letter if no map entry
          next[lbl] = ''
        }
      }
      return next
    })
  }

  const animalLabels   = labels.filter(l => !NONANIMAL.has(l))
  const nonanimalCount = labels.length - animalLabels.length
  const canConvert     = !!(csvPath && cols.filename && cols.datetime && cols.label && !converting)

  const colOption = (col: string) => <option key={col} value={col}>{col}</option>

  return (
    <div>
      <h4 className="text-lg font-semibold mb-1">{t('setup.csv_title')}</h4>
      <p className="text-zinc-500 dark:text-zinc-400 mb-6 text-sm">{t('setup.csv_desc')}</p>

      {/* ── Fichero CSV ── */}
      <div className="mb-5">
        <label className={labelClass}>{t('setup.csv_file_label')} <span className="text-red-500">*</span></label>
        <div className="flex">
          <input className={inputClass} placeholder={t('setup.csv_file_placeholder')}
            value={csvPath} onChange={e => setCsvPath(e.target.value)} />
          <button type="button" className={browseBtn} onClick={() => setPicker('csv')}>
            {t('setup.browse')}
          </button>
        </div>
        {loadingHdr && <p className={hintClass}>{t('setup.csv_loading_headers')}</p>}
        {headers.length > 0 && !loadingHdr && (
          <p className={hintClass}>{t('setup.csv_headers_found', { n: headers.length })}</p>
        )}
      </div>

      {/* ── Directorio de imágenes ── */}
      <div className="mb-5">
        <label className={labelClass}>
          {t('setup.csv_imgdir_label')}{' '}
          <span className="text-zinc-400 font-normal">{t('setup.label_output_optional')}</span>
        </label>
        <div className="flex">
          <input className={inputClass} placeholder={t('setup.csv_imgdir_placeholder')}
            value={imageBaseDir} onChange={e => setImageBaseDir(e.target.value)} />
          <button type="button" className={browseBtn} onClick={() => setPicker('imgdir')}>
            {t('setup.browse')}
          </button>
        </div>
        <p className={hintClass}>{t('setup.csv_imgdir_hint')}</p>
      </div>

      {/* ── Mapeo de columnas ── */}
      {headers.length > 0 && (
        <div className="mb-5 p-4 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/50">
          <h5 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-3">
            {t('setup.csv_cols_title')}
          </h5>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* Obligatorias */}
            <div>
              <label className={labelClass}>
                {t('setup.csv_col_filename')} <span className="text-red-500">*</span>
              </label>
              <select className={selectClass} value={cols.filename} onChange={e => setCol('filename', e.target.value)}>
                <option value="">{t('setup.csv_col_placeholder')}</option>
                {headers.map(colOption)}
              </select>
            </div>
            <div>
              <label className={labelClass}>
                {t('setup.csv_col_datetime')} <span className="text-red-500">*</span>
              </label>
              <select className={selectClass} value={cols.datetime} onChange={e => setCol('datetime', e.target.value)}>
                <option value="">{t('setup.csv_col_placeholder')}</option>
                {headers.map(colOption)}
              </select>
            </div>
            <div>
              <label className={labelClass}>
                {t('setup.csv_col_label')} <span className="text-red-500">*</span>
              </label>
              <select className={selectClass} value={cols.label} onChange={e => setCol('label', e.target.value)}>
                <option value="">{t('setup.csv_col_placeholder')}</option>
                {headers.map(colOption)}
              </select>
            </div>
            {/* Opcionales */}
            <div>
              <label className={labelClass}>
                {t('setup.csv_col_score')}{' '}
                <span className="text-zinc-400 font-normal">{t('setup.label_output_optional')}</span>
              </label>
              <select className={selectClass} value={cols.score} onChange={e => setCol('score', e.target.value)}>
                <option value="">{t('setup.csv_col_placeholder')}</option>
                {headers.map(colOption)}
              </select>
            </div>
            <div>
              <label className={labelClass}>
                {t('setup.csv_col_site')}{' '}
                <span className="text-zinc-400 font-normal">{t('setup.label_output_optional')}</span>
              </label>
              <select className={selectClass} value={cols.site} onChange={e => setCol('site', e.target.value)}>
                <option value="">{t('setup.csv_col_placeholder')}</option>
                {headers.map(colOption)}
              </select>
              <p className={hintClass}>{t('setup.csv_col_site_hint')}</p>
            </div>
          </div>
        </div>
      )}

      {/* ── Mapa de especies ── */}
      {cols.label && (
        <div className="mb-5 p-4 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/50">
          <div className="flex items-center justify-between mb-2">
            <h5 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              {t('setup.csv_species_title')}
            </h5>
            {animalLabels.length > 0 && (
              <button
                type="button"
                className="text-xs px-2 py-1 rounded border border-blue-400 text-blue-600 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors"
                onClick={autofill}
              >
                {t('setup.csv_species_autofill')}
              </button>
            )}
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">{t('setup.csv_species_desc')}</p>

          {loadingLbl && <p className="text-xs text-zinc-400">{t('setup.csv_loading_labels')}</p>}

          {nonanimalCount > 0 && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mb-2">
              {t('setup.csv_nonanimal_note', { n: nonanimalCount })}
            </p>
          )}

          {animalLabels.length > 0 && !loadingLbl && (
            <div className="max-h-64 overflow-y-auto rounded border border-zinc-200 dark:border-zinc-700">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="bg-zinc-100 dark:bg-zinc-700 text-left">
                    <th className="px-3 py-2 font-medium text-zinc-600 dark:text-zinc-300 w-2/5">{t('setup.csv_label_col')}</th>
                    <th className="px-3 py-2 font-medium text-zinc-600 dark:text-zinc-300">→</th>
                    <th className="px-3 py-2 font-medium text-zinc-600 dark:text-zinc-300">{t('setup.csv_name_col')}</th>
                  </tr>
                </thead>
                <tbody>
                  {animalLabels.map(lbl => (
                    <tr key={lbl} className="border-t border-zinc-200 dark:border-zinc-700">
                      <td className="px-3 py-1.5 text-zinc-700 dark:text-zinc-300 font-mono text-xs">{lbl}</td>
                      <td className="px-1 text-zinc-400">→</td>
                      <td className="px-3 py-1.5">
                        <input
                          className="w-full rounded border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 px-2 py-1 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                          placeholder={t('setup.csv_name_placeholder')}
                          value={speciesMap[lbl] ?? ''}
                          onChange={e => setSpeciesMap(m => ({ ...m, [lbl]: e.target.value }))}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Botón convertir ── */}
      <div className="flex items-center justify-between gap-2">
        {onBack && (
          <button type="button"
            className="px-4 py-2 text-sm border border-zinc-300 dark:border-zinc-600 text-zinc-700 dark:text-zinc-300 rounded hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
            onClick={onBack}>
            {t('setup.back')}
          </button>
        )}
        <div className="flex flex-col items-end gap-2">
          <button
            type="button"
            disabled={!canConvert}
            onClick={handleConvert}
            className={[
              'px-5 py-2 text-sm rounded bg-emerald-600 text-white flex items-center gap-2 transition-opacity',
              canConvert ? 'hover:bg-emerald-700 cursor-pointer' : 'opacity-40 cursor-not-allowed',
            ].join(' ')}
          >
            {converting && <SmallSpinner />}
            {t(converting ? 'setup.csv_converting' : 'setup.csv_convert')}
          </button>
          {error && <p className="text-sm text-red-600 dark:text-red-400 text-right">{error}</p>}
        </div>
      </div>

      {/* ── Picker ── */}
      {picker === 'csv' && (
        <DirectoryPicker
          showFiles fileExt=".csv"
          title={t('setup.csv_file_picker_title')}
          onSelect={path => { setCsvPath(path); setPicker(null) }}
          onClose={() => setPicker(null)}
        />
      )}
      {picker === 'imgdir' && (
        <DirectoryPicker
          title={t('setup.csv_imgdir_picker_title')}
          onSelect={path => { setImageBaseDir(path); setPicker(null) }}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  )
}
