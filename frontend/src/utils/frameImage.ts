import type { Frame } from '../types'

/**
 * URL of the image to show for a frame. With boxes on and a box available, the
 * server draws the box of the observation being verified into the image, so it
 * follows the image through scaling, zoom, rotation and fullscreen. Remote
 * (proxied) images and frames without a box are returned as they are.
 */
export function frameSrc(frame: Pick<Frame, 'img' | 'obsId' | 'boxes'>, showBoxes: boolean): string {
  if (!showBoxes || !frame.boxes || !frame.img.startsWith('/api/image/')) return frame.img
  const sep = frame.img.includes('?') ? '&' : '?'
  return `${frame.img}${sep}boxes=true&obs=${encodeURIComponent(frame.obsId)}`
}
