# Features

## Data ingestion

- **CamtrapDP v1.0** — loads any directory with `deployments.csv`, `media.csv`, and `observations.csv` produced by an AI classifier or citizen-science platform. No conversion required.
- **DeepFaune CSV importer** — converts DeepFaune classification exports directly to CamtrapDP format; species labels are mapped automatically to scientific names via a built-in lookup table.
- **Generic CSV importer** — accepts any classifier CSV with configurable column mapping (image path, datetime, species label, confidence score, site). An interactive species-name editor allows mapping custom labels to scientific names; non-animal labels (`empty`, `human`, `blank`, etc.) are handled automatically.
- **Classifiers and reference** — combines the CamtrapDP folders of one or more AI classifiers and, optionally, a human reference (e.g. Zooniverse) into one CamtrapDP with a recalculated probability per photo and target species. With a reference, five methods are compared out of sample and per-species thresholds take out of the review the detection events not worth reviewing; they stay in the dataset tagged `camtrapverify:filtered`. See [Classifiers and reference](multiclassifier.md).
- **Flexible timestamp parsing** — accepts ISO 8601 and EXIF-style (`YYYY:MM:DD HH:MM:SS`) timestamps transparently.
- **Automatic metadata detection** — infers available species and the study date range directly from `observations.csv` on load.
- **Site resolution** — uses `locationID` when present; falls back to `deploymentID`, so both survey designs are supported.

---

## Sampling occasion and detection event construction

- **Configurable sampling occasions** — divides the study window into fixed-length windows (`occasion_days`, default 5 days; or `occasion_hours` for occasions shorter than a day, e.g. 1 h for activity patterns, in which case camera operation is given in hours and the occupancy estimate is not computed) per deployment. The number of occasions adapts automatically to the study duration.
- **Detection event grouping** — consecutive frames at the same location separated by less than `gap_seconds` (default 60 s) are grouped into a single reviewable detection event.
- **Confidence ranking** — within each site × occasion × species cell, detection events are ranked by the maximum `classificationProbability` across their frames, so round 1 always shows the most likely true detection. Events with the same score (all of them when no photo has a score) are shown in a seeded random order (`random_seed`, default 42), so the order is reproducible and not chronological.
- **Score filtering** — frames below `min_score` (default 0.5) are excluded from the candidate manifest, avoiding the lowest-confidence noise.

---

## Review gallery

- **One card per cell** — each site × occasion combination is shown as a single card; the expert makes one decision per card per round.
- **Frame navigation** — arrows step through the individual frames of a detection event; the progress badge shows "Frame N / M".
- **Bounding boxes** — when the data include CamtrapDP boxes (`bboxX`, `bboxY`, `bboxWidth`, `bboxHeight`), the box of the animal being verified is drawn on the cards and in the large view (toggle *Show boxes*), so photos with several animals or species are unambiguous.
- **Detection event counter** — the badge "Detection event N / M" shows which ranked detection event is currently displayed and how many are available.
- **Burst context mode** — when enabled, all frames of the physical burst are shown (not only those labelled as the target species), so the expert can see the animal entering and leaving the scene. Context frames are visually dimmed and do not affect the decision.
- **Lightbox** — click any image to open it full-screen with:
    - Mouse-wheel zoom and drag-to-pan
    - Brightness and contrast controls
    - Tonal inversion (useful for night-vision / near-infrared images)
    - Left / right arrows to move between occasions without closing
- **Another species in the photo** — in the large view, confirm another target species at the same location and occasion from the photo being viewed (keys `1`–`9`). It becomes a verified detection (also where the classifier never assigned it), the verified CamtrapDP marks or adds a human observation, and undoing leaves no trace.
- **Keyboard navigation** — arrow keys advance frames; `C` confirms, `R` rejects (configurable); `U` marks a detection event as unsure.
- **Per-species progress bars** — a coloured badge on each species card shows the current round; the bar fills as cells are resolved.

---

## Iterative review logic

- **Round-based flow** — in round 1, only rank-1 detection events are presented. Confirming a detection event closes its cell. Rejecting it makes the rank-2 detection event appear in round 2.
- **Automatic cell closure** — once a detection event is confirmed, the cell disappears from the gallery; no further review is needed for it.
- **Review order by score or by time** — by default each occasion is reviewed from its most confident event; *by time* starts from the earliest, so the first confirmed event is the first true detection (needed for time-to-detection analyses). Detection histories are the same either way.
- **Convergence** — the review depth is bounded by `total_iterations`; in practice most cells resolve in 1-2 rounds.
- **Session persistence** — the active session (config + all decisions) is saved to disk and restored automatically when the server restarts.

---

## Verified output

- **`camtrap_dp_verified/`** — a complete CamtrapDP dataset in which confirmed observations are updated:

    | Field | Value after confirmation |
    |---|---|
    | `classificationMethod` | `"human"` |
    | `classificationProbability` | `1.0` |
    | `classifiedBy` | configurable (default `"expert_review"`) |
    | `classificationTimestamp` | current UTC timestamp |

- **Review recorded in `observationTags`** — the verified CamtrapDP tags the photos the reviewer looked at (every photo of a rejected or unsure event, not only its representative): `camtrapverify:confirmed`, `camtrapverify:rejected`, `camtrapverify:unsure` (pending expert review) and, when recorded, `camtrapverify-actual-species:<name>`. Pipe-separated `key:value` pairs as CamtrapDP defines; existing tags are kept.
- **Configurable `classifiedBy` label** — the value written to `classifiedBy` can be set per session (e.g. `"expert_review"`, `"ornithologist_A"`).
- **Extended confirmation** — when enabled, all observations in the confirmed burst (not just the highest-confidence representative frame) are marked as human-verified in the output.
- **`occupancy_inputs/`** — ready-to-use files for single-species occupancy models:

    | File | Description |
    |------|-------------|
    | `camera_operation.csv` | Active days per site × occasion |
    | `dethist_naive_{sp}.csv` | Detection history from the classifier (1 / 0 / NA) |
    | `dethist_verified_{sp}.csv` | Detection history after human verification |
    | `ttd_naive_{sp}.csv` (and `ttd_verified_{sp}.csv` when reviewed by time) | Hours from the start of each occasion to its first detection, censored at the occasion length (as `occuTTD` expects); NA where the camera was off or the occasion is pending |
    | `verification_summary.csv` | Per-species: combos, detections, false positives, ψ_obs |
    | `review_effort.csv` | Actual number of images inspected per cell |
    | `effort_report.csv` | Effort per species and total: events and cells inspected, by outcome, with rejected/confirmed scores, active review time and an estimate of the time saved |
    | `false_positive_sources.csv` | Main sources of false positives per species (only with *Record the actual species when rejecting*) |

- **Incremental regeneration** — output files are regenerated automatically after every save, so intermediate results are always up to date.

---

## Scope and limitations

- **Needs labels that already exist** — a classifier or citizen-science labels for the study system; it does not classify.
- **Still images only** — video files are not read; extract frames and classify them first (see the [user manual](user-manual.md#9-scope-and-limitations) for guidance).
- **Designed for occupancy models** — only one detection event per cell is verified, so the verified data are not suitable for counting events, activity patterns or abundance; time-to-first-detection needs care because the highest-scoring event is shown first, not the earliest.
- **The score only orders the events** — it does not need to be calibrated (raw model outputs work with the minimum score set to 0); without scores the events are shown in a seeded random order.
- **Corrects false positives, mostly not missed detections** — animals the classifier missed are not searched for. The exception is another target species seen in a photo you are reviewing: it can be confirmed from the large view (a verified detection, counted as a false negative of the classifier).
- **Unsure cases and pending expert review** — mark a doubtful event *Unsure*: the next event of the occasion is shown, and an occasion that runs out with an unsure event and no confirmation waits for an expert (NA in the verified history, `cell_status_<sp>.csv`) instead of counting as not detected.

---

## Configuration

- **`.env` file** — all server parameters (`port`, `log_level`, `cors_origins`, paths) are read from a `.env` file with a clear priority order: system environment variables → `~/.config/camtrap_verify/.env` → `.env` next to the binary.
- **No database** — state is stored as plain CSV and JSON files; the session directory is fully portable.

---

## CLI

A [Typer](https://typer.tiangolo.com/) CLI (`uv run cli`) provides:

- `serve [dev|prod|debug] [--port N]` — start the backend in the selected mode
- `docs serve / build` — serve or build the MkDocs documentation
- `package build [--format deb|rpm|windows]` — produce distributable packages via Docker

---

## Distribution

- **Linux** — `.deb` and `.rpm` packages built with PyInstaller + fpm inside Docker; installs to `/opt/camtrap-verify-backend/` with a `.desktop` launcher.
- **Windows** — `.exe` built natively on Windows or cross-compiled via Docker + Wine on Linux/macOS.
- **Self-contained** — the binary embeds the Python runtime; no Python installation required on the target machine.
