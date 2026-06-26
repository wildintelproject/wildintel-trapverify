# Configuration

## Server settings (`.env`)

Server behaviour is controlled via environment variables with the prefix `CAMTRAP_`. Copy `.env.example` to `.env` and edit as needed.

```bash
cp .env.example .env
```

### Priority order

Settings are applied in this order (highest wins):

1. **System environment variables** — e.g. `CAMTRAP_PORT=9000 uv run cli serve`
2. **`~/.config/camtrap_verify/.env`** — user-level config, survives updates
3. **`.env` next to the binary / module** — project-level defaults

### Available variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CAMTRAP_PORT` | `8765` | Port the uvicorn server listens on |
| `CAMTRAP_LOG_LEVEL` | `INFO` | Python log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `CAMTRAP_CORS_ORIGINS` | `["http://localhost:5173","http://localhost","http://localhost:8765"]` | Allowed CORS origins (JSON list) |
| `CAMTRAP_APP_DIR` | `~/.config/camtrap_verify` | Where the active session pointer is stored |
| `CAMTRAP_DEFAULT_OUTPUT_DIR` | `~/Documents/camtrap_verify` | Default base directory for session output |

### Example `.env`

```ini
CAMTRAP_PORT=8765
CAMTRAP_LOG_LEVEL=INFO
CAMTRAP_CORS_ORIGINS=["http://localhost:5173","http://localhost","http://localhost:8765"]
# CAMTRAP_APP_DIR=/home/user/.config/camtrap_verify
# CAMTRAP_DEFAULT_OUTPUT_DIR=/home/user/Documents/camtrap_verify
```

---

## Session parameters

These parameters are set through the setup wizard in the web interface when creating a new session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `camtrap_dir` | `string` | — | Absolute path to the CamtrapDP directory |
| `output_dir` | `string` | `~/Documents/camtrap_verify` | Base output directory; each session creates a timestamped sub-folder |
| `target_species` | `string[]` | — | Scientific names exactly as they appear in `observations.csv` |
| `study_start` | `YYYY-MM-DD` | — | Start of the study window |
| `study_end` | `YYYY-MM-DD` | — | End of the study window |
| `occasion_days` | `int` | `5` | Duration of each sampling period in days |
| `gap_seconds` | `int` | `60` | Images separated by less than this (in seconds) belong to the same sequence |
| `total_iterations` | `int` | `100000` | Maximum review depth per site × period × species cell |
| `min_score` | `float [0-1]` | `0.5` | Minimum classification confidence to be included as a candidate |

---

## Input format — CamtrapDP v1.0

The application consumes the [CamtrapDP v1.0](https://camtrap-dp.tdwg.org/) standard: three CSV files in the same directory.

### `deployments.csv`

| Column | Required | Description |
|--------|:--------:|-------------|
| `deploymentID` | Yes | Unique deployment identifier |
| `locationID` | No | Location identifier. Used as the site key when present and non-empty; otherwise `deploymentID` is used |
| `deploymentStart` | No | ISO deployment start date (used for the camera-operation matrix) |
| `deploymentEnd` | No | ISO deployment end date |

### `media.csv`

| Column | Required | Description |
|--------|:--------:|-------------|
| `mediaID` | Yes | Unique file identifier |
| `deploymentID` | Yes | Reference to the deployment |
| `timestamp` | Yes | Date and time in ISO 8601 or EXIF format (`YYYY:MM:DD HH:MM:SS`) |
| `filePath` | Yes | Path to the image file (absolute or remote URL) |

### `observations.csv`

| Column | Required | Description |
|--------|:--------:|-------------|
| `observationID` | Yes | Unique identifier |
| `deploymentID` | Yes | Reference to the deployment |
| `mediaID` | Yes | Reference to the media file |
| `observationLevel` | Yes | Must be `"media"` to be included |
| `observationType` | Yes | `"animal"`, `"blank"`, `"human"`, etc. |
| `scientificName` | Yes | Scientific name (empty for non-animals) |
| `classificationProbability` | Yes | Classifier confidence score in `[0, 1]` |
| `classificationMethod` | No | Classification method (e.g. `"machine"`) |
| `classifiedBy` | No | Classifier name (e.g. `"DeepFaune"`) |
| `classificationTimestamp` | No | Timestamp of the original classification |

---

## Sessions

Each **Start verification** creates a new session with its own timestamped directory:

```
~/Documents/camtrap_verify/
└── 2025-11-01_120000/          ← active session
    ├── config.json
    ├── candidate_manifest.csv
    ├── rejected_media.json
    ├── decisions/
    ├── camtrap_dp_verified/
    └── occupancy_inputs/
```

The active session persists across server restarts. On startup, the last session is recovered from `~/.config/camtrap_verify/last_session.json`.

---

## Full output directory reference

```
<session_dir>/
├── config.json                         session configuration
├── candidate_manifest.csv              all candidate frames, ranked
├── rejected_media.json                 manually rejected media IDs
│
├── decisions/                          per-species, per-round decisions
│   └── decisions_<species>_iter<N>.csv
│
├── camtrap_dp_verified/                updated CamtrapDP dataset
│   ├── deployments.csv                 unchanged copy
│   ├── media.csv                       unchanged copy
│   └── observations.csv               classificationMethod/Probability/By/Timestamp
│                                       updated for confirmed observations
│
└── occupancy_inputs/                   inputs for occupancy models
    ├── camera_operation.csv            active days per site × sampling period
    ├── dethist_naive_<species>.csv     1/0/NA — classifier-based
    ├── dethist_verified_<species>.csv  1/0/NA — expert-verified
    ├── verification_summary.csv        per-species combos, detections, false positives, ψ_obs
    └── review_effort.csv               images actually inspected per cell
```

### Detection history format

`dethist_*.csv` files have one row per location and one column per sampling period (`occ1`, `occ2`, …):

| siteID | occ1 | occ2 | occ3 |
|--------|:----:|:----:|:----:|
| SITE_001 | 1 | 0 | NA |
| SITE_002 | 0 | 1 | 1 |

- **1** — species detected (naive: by classifier; verified: confirmed by expert)
- **0** — camera active but no detection
- **NA** — camera inactive during that period
