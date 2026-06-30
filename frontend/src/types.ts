export interface Frame {
  obsId: string
  mediaId: string
  img: string
  ts: string
  prob: number | null
  isContext?: boolean
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
  output_dir: string
  target_species: string[]
  study_start: string
  study_end: string
  occasion_days: number
  total_iterations: number
  gap_seconds: number
  min_score: number
  include_burst_context: boolean
  classified_by: string
  extended_confirmation: boolean
}

export type Decision = 'confirmed' | 'rejected' | null
