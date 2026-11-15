import { describe, expect, it } from 'vitest'
import { pathCrumbs } from './breadcrumbs'

describe('pathCrumbs', () => {
  it('splits a POSIX path', () => {
    expect(pathCrumbs('/home/ana/photos')).toEqual([
      { label: 'home', path: '/home' },
      { label: 'ana', path: '/home/ana' },
      { label: 'photos', path: '/home/ana/photos' },
    ])
  })

  it('handles the POSIX root', () => {
    expect(pathCrumbs('/')).toEqual([])
  })

  it('splits a Windows path and keeps the drive and the backslashes', () => {
    expect(pathCrumbs('D:\\fotos\\2023')).toEqual([
      { label: 'D:', path: 'D:\\' },
      { label: 'fotos', path: 'D:\\fotos' },
      { label: '2023', path: 'D:\\fotos\\2023' },
    ])
  })

  it('accepts a Windows drive written with forward slashes', () => {
    expect(pathCrumbs('C:/Users/ana')).toEqual([
      { label: 'C:', path: 'C:\\' },
      { label: 'Users', path: 'C:\\Users' },
      { label: 'ana', path: 'C:\\Users\\ana' },
    ])
  })

  it('handles a bare Windows drive', () => {
    expect(pathCrumbs('E:\\')).toEqual([{ label: 'E:', path: 'E:\\' }])
  })
})
