export interface Frame {
  obsId: string
  mediaId: string
  img: string
  ts: string
  prob: number | null
  isContext?: boolean
  /** Number of bounding boxes the server can draw for this frame's observation. */
  boxes?: number
}

export interface DetectionEvent {
  key: string
  siteId: string
  occasion: number
  rank: number
  totalSeqs: number
  repObsId: string
  maxProb: number
  frames: Frame[]
  status?: 'confirmed' | 'not_confirmed'
}

export interface SpeciesStats {
  species_name: string
  species_safe: string
  n_total_combos: number
  n_confirmed_combos: number
  n_resolved: number
  current_iteration: number
  thumbnails: string[]
}

export interface WorkflowConfig {
  camtrap_dir: string
  image_base_dir: string
  flat_search: boolean
  output_dir: string
  target_species: string[]
  study_start: string
  study_end: string
  occasion_days: number
  /** Occasion length in hours when shorter than a day; 0 or missing means use occasion_days. */
  occasion_hours?: number
  total_iterations: number
  gap_seconds: number
  min_score: number
  /** Optional name that tells sessions apart. */
  session_name?: string
  /** Cut-offs that replace min_score for some species (scientific name -> value). */
  min_score_by_species?: Record<string, number>
  include_burst_context: boolean
  classified_by: string
  extended_confirmation: boolean
  record_rejection_species: boolean
  review_idle_seconds: number
  random_seed: number
  /** Order of the detection events of each occasion: most confident first, or earliest first. */
  review_order?: 'score' | 'time'
}

export type Decision = 'confirmed' | 'rejected' | null

export interface OccupancyRow {
  species: string
  psi_naive: number | null
  psi_naive_lo: number | null
  psi_naive_hi: number | null
  p_naive: number | null
  p_naive_lo?: number | null
  p_naive_hi?: number | null
  degenerate_naive: boolean
  psi_verified: number | null
  psi_verified_lo: number | null
  psi_verified_hi: number | null
  p_verified: number | null
  p_verified_lo?: number | null
  p_verified_hi?: number | null
  degenerate_verified: boolean
}

export interface SavedProgress {
  iteration: number
  /** repObsId of each decided event -> its decision */
  decisions: Record<string, 'confirmed' | 'rejected' | 'uncertain'>
  corrections: Record<string, string>
  decision_times: Record<string, number>
  saved_at: string
}

export interface RelinkStatus {
  camtrap_dir_ok: boolean
  images_ok: boolean
  needs_relink: boolean
  camtrap_dir: string
  image_base_dir: string
  flat_search: boolean
}

export interface RecentSession {
  session_dir: string
  last_opened: string
  session_name?: string
  target_species: string[]
  study_start: string | null
  study_end: string | null
}
