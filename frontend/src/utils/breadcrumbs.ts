export interface Crumb {
  label: string
  path: string
}

/**
 * Breadcrumbs of a folder path. Works with POSIX paths (`/home/ana/photos`) and with
 * Windows paths (`D:\fotos\2023`, `D:/fotos`), whose crumbs keep their drive and
 * backslashes (`D:\`, `D:\fotos`, `D:\fotos\2023`).
 */
export function pathCrumbs(current: string): Crumb[] {
  const windows = /^[A-Za-z]:[\\/]?/.test(current)
  const parts = current.split(/[\\/]/).filter(Boolean)
  return parts.map((part, i, arr) => ({
    label: part,
    path: windows
      ? arr.slice(0, i + 1).join('\\') + (i === 0 ? '\\' : '')
      : '/' + arr.slice(0, i + 1).join('/'),
  }))
}
