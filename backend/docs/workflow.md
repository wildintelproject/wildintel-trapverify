# Workflow

## Overview

The review workflow is **iterative and confidence-directed**: in each round the expert is shown the highest-confidence unreviewed sequence for every site × period × species cell. Confirming it closes the cell. Rejecting it causes the next-ranked sequence to appear in round 2.

```
CamtrapDP
  (deployments + media + observations)
           │
           ▼
  build_candidates()
  ┌─────────────────────────────────────┐
  │  1. Filter to target species        │
  │  2. Assign sampling periods         │
  │  3. Group into sequences            │
  │  4. Rank by confidence              │
  └────────────────┬────────────────────┘
                   │  candidate_manifest.csv
                   ▼
         Review gallery
         ┌───────────────────┐
         │  Round 1          │
         │  (highest conf.)  │
         └────────┬──────────┘
                  │  Confirm / Reject
                  ▼
         decisions/  ←──── updated on every save
                  │
           ┌──────┴──────┐
           ▼             ▼
  camtrap_dp_verified/   occupancy_inputs/
```

---

## Key concepts

### Sampling period

A fixed-length time window (default **5 days**) per deployment location. All images from the same site within that window belong to the same period. The number of periods is determined by the study duration and `occasion_days`.

### Sequence

A group of images captured at the same location with less than `gap_seconds` (default 60 s) between consecutive frames. The sequence is the unit of review: the expert confirms or rejects the presence of a species based on the full sequence, not individual frames.

### Round

In each round, the highest-confidence unreviewed sequence is shown for each cell. The round badge in the interface goes from green (round 1, highest confidence) towards red (later rounds, lower confidence).

### Cell

The combination `site × period × species` is a **cell** in the occupancy matrix:

| Value | Meaning |
|:-----:|---------|
| **1** | At least one confirmed sequence in that period |
| **0** | Camera active, but no confirmed detection |
| **NA** | Camera inactive during that period |

---

## Backend modules

### `build_candidates` (`camtrap_workflow.py`)

The central function that builds the candidate manifest:

1. Parses timestamps from `media.csv` (ISO 8601 and EXIF format)
2. Filters to target species and the study window
3. Assigns sampling periods (fixed temporal breaks)
4. Groups frames into sequences: frames within `gap_seconds` of each other
5. Ranks sequences by maximum `classificationProbability` within each cell

### `export_verified_camtrapdp`

Generates `camtrap_dp_verified/observations.csv` by updating **only the representative observation** (highest confidence) of each confirmed sequence:

| Field | Value after confirmation |
|-------|--------------------------|
| `classificationMethod` | `"human"` |
| `classificationProbability` | `1.0` |
| `classifiedBy` | `"expert_review"` |
| `classificationTimestamp` | current UTC timestamp |

All other observations in the period remain unchanged.

### `build_occupancy_inputs`

Generates the files in `occupancy_inputs/`:

- **`camera_operation.csv`** — active days per site × period, using `deploymentStart`/`deploymentEnd` from `deployments.csv` when available; otherwise full activity is assumed.
- **`dethist_naive_<sp>.csv`** — 1 if the classifier detected the species in that period, 0 if the camera was active but without detection, NA if inactive.
- **`dethist_verified_<sp>.csv`** — same, but counting only human confirmations.
- **`verification_summary.csv`** — per-species summary with `psi_obs` (proportion of sites with ≥1 detection) naive vs. verified.

### `build_review_effort`

Calculates how many images the expert actually inspected:

- **Confirmed cells** — counts the rank of the confirmed sequence (stops at the first "yes").
- **Rejected cells** — counts all available ranks.

---

## Decision logic

| Action | Immediate effect | Effect in next round |
|--------|-----------------|----------------------|
| Confirm sequence | Cell marked as detection (1) | Cell disappears from the gallery |
| Reject sequence | No change to the cell | Next-ranked sequence appears in round N+1 |
| Save without deciding all | Error — all visible cards must have a decision | — |
| No more candidates | Species marked **Complete** | — |

---

## Output files reference

### `candidate_manifest.csv`

One row per candidate frame. Main columns:

| Column | Description |
|--------|-------------|
| `site_occasion_key` | Unique key `{site}_occ{N}_{species}` |
| `rank` | Sequence rank (1 = highest confidence) |
| `burst_id` | Sequence index within the cell |
| `burst_seq` | Frame position within the sequence |
| `observationID` | ID in `observations.csv` |
| `mediaID` | ID in `media.csv` |
| `classificationProbability` | Classifier score |
| `siteID` | Location identifier |
| `occasion` | Sampling period number |

### `decisions/decisions_<species>_iter<N>.csv`

Confirmed observations for the species in round N:

`observationID`, `site_occasion_key`, `mediaID`, `scientificName`, `siteID`, `occasion`

### `verification_summary.csv`

| Column | Description |
|--------|-------------|
| `species` | Scientific name |
| `candidate_frames` | Total candidate frames |
| `candidate_combos` | Total cells (site × period) with candidates |
| `naive_detections` | Cells with a classifier detection |
| `verified_detections` | Cells with a human-confirmed detection |
| `false_positive_cells` | `naive=1` but `verified=0` |
| `psi_obs_naive` | Proportion of sites with ≥1 detection (classifier) |
| `psi_obs_verified` | Proportion of sites with ≥1 detection (verified) |
