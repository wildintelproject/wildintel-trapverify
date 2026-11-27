/**
 * State of an "Another species in this photo?" button for the detection event
 * open in the lightbox.
 *
 * - `confirmed`: the species was confirmed in its own review;
 * - `cross`: confirmed from a photo of this detection event, in the review of
 *   the species being reviewed now (blue; a click undoes it);
 * - `elsewhere`: confirmed from a photo of another detection event of the same
 *   location and occasion, or from a photo of this event while another species
 *   was being reviewed. The same photo can be a candidate of several species
 *   (e.g. a multi-classifier CamtrapDP), so a confirmation made while reviewing
 *   fallow deer must not look like a choice made now in the review of rabbit.
 *   It can only be undone from where it was made.
 * - `none`: not confirmed.
 *
 * The lightbox shows `confirmed` and `elsewhere` the same way (grey, disabled):
 * for the reviewer they mean the same.
 */
export type CrossButtonState = 'confirmed' | 'cross' | 'elsewhere' | 'none'

type CrossEntry = { status: string; mediaID?: string | null; source?: string | null }

export function crossButtonState(
  entry: CrossEntry | undefined,
  frames: { mediaId: string }[],
  reviewing?: string,
): CrossButtonState {
  if (!entry) return 'none'
  if (entry.status === 'confirmed') return 'confirmed'
  if (entry.status === 'cross') {
    // Older sessions may lack the source species: then the photo alone decides.
    const thisReview = !reviewing || !entry.source || entry.source === reviewing
    return thisReview && frames.some((f) => f.mediaId === entry.mediaID) ? 'cross' : 'elsewhere'
  }
  return 'none'
}

/** Species confirmed (blue) from a photo of this detection event in the current review. */
export function crossConfirmedHere<T extends CrossEntry & { scientificName: string }>(
  entries: T[] | undefined,
  frames: { mediaId: string }[],
  reviewing?: string,
): string[] {
  return (entries ?? [])
    .filter((c) => crossButtonState(c, frames, reviewing) === 'cross')
    .map((c) => c.scientificName)
}
