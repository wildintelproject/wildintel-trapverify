export interface Frame {
  obsId: string
  mediaId: string
  img: string
  ts: string
  prob: number | null
  isContext?: boolean
  /** Number of bounding boxes the server can draw for this frame's observation. */
  boxes?: number
  /** Pending review: the observation that represents the detection event this frame belongs to. */
  burstRepObsId?: string
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
  status?: 'confirmed' | 'not_confirmed' | 'pending'
}

export interface SpeciesStats {
  species_name: string
  species_safe: string
  n_total_combos: number
  n_confirmed_combos: number
  n_resolved: number
  /** Cells whose events ran out with an unsure event and no expert verdict yet. */
  n_pending?: number
  /** rounds: review in progress · pending: only pending cells left · complete */
  phase?: 'rounds' | 'pending' | 'complete'
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
  /** 'rounds' for an unfinished round, 'pending' for the pending-expert-review view (iteration 0) */
  mode: 'rounds' | 'pending'
  iteration: number
  /** cell key of each decided event -> its decision */
  decisions: Record<string, 'confirmed' | 'rejected' | 'unsure'>
  /** cell key -> the event confirmed in the pending view (the photo being looked at) */
  chosen_rep: Record<string, string>
  /** cell key -> actual species typed for a rejection */
  corrections: Record<string, string>
  /** cell key -> epoch ms of the click */
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

export interface McClassifier {
  name: string
  path: string
  role: 'ai' | 'reference'
}

export interface McLabels {
  date_min: string | null
  date_max: string | null
  n_photos: number
  labels: { classifier: string; label: string; photos: number }[]
  families: string[]
  remote_paths: number
}

export interface McRunRequest {
  classifiers: McClassifier[]
  groups: Record<string, string[]>
  date_start: string
  date_end: string
  occasion_days: number
  occasion_hours?: number
  gap_seconds: number
  filter_mode: 'cells' | 'events' | 'none'
  retention: number
  tie_break: 'ambiguous' | 'simple' | 'none'
  use_reference_in_output: boolean
  aliases?: Record<string, string>
  output_dir?: string | null
  output_name?: string | null
}

export interface McStrategyRow {
  strategy: string
  rounds: number
  cell_retention: number
  eligible: boolean
  diff_ci_low: number | null
  diff_ci_high: number | null
  tie: boolean
  ambiguous_photos: number | null
  mean_second_species: number | null
  best: boolean
  chosen: boolean
}

export interface McSpeciesRow {
  species: string
  events_before: number
  events_after: number
  removed: number
  saving: number
  cells_before: number
  cells_after: number
  reference_cells: number | null
  threshold: number | null
}

export interface McResult {
  camtrap_dir: string
  strategy: string
  has_reference: boolean
  filter_mode: string
  events_before: number
  events_after: number
  photos_high_in_two_before: number
  photos_high_in_two_after: number
  by_species: McSpeciesRow[]
  strategies: McStrategyRow[]
  study_start: string
  study_end: string
  occasion_days: number
  occasion_hours?: number
  gap_seconds: number
  warnings: string[]
  /** Folder the photo paths were made relative to, if it exists here. */
  images_dir?: string | null
}

export interface McJob {
  status: 'running' | 'done' | 'error'
  log: string[]
  out_dir: string
  result?: McResult
  error?: string
  unmapped?: string[]
}

export interface CrossSpecies {
  scientificName: string
  species_safe: string
  /** cross: confirmed from a photo of another species; confirmed: in its own review */
  status: 'none' | 'cross' | 'confirmed'
  /** whether the classifier flagged this species at this location and occasion */
  has_candidates?: boolean
  mediaID?: string
  observationID?: string
  source?: string
}
