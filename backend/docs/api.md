# API reference

!!! info "Development URLs"
    - Backend: **`http://localhost:8765`**
    - Interactive Swagger UI: **`http://localhost:8765/docs`**
    - ReDoc: **`http://localhost:8765/redoc`**

---

## File system

### `GET /api/fs/inspect`

Inspect a CamtrapDP directory and return the available animal species and the date range.

**Query params**: `path=/absolute/path/to/camtrap_dp`

**Response**
```json
{
  "species": ["Cervus elaphus", "Sus scrofa", "Vulpes vulpes"],
  "study_start": "2025-11-01",
  "study_end": "2025-11-30"
}
```

---

### `GET /api/fs/browse`

Browse the server file system to select directories interactively.

**Query params**: `path=/home/user` (empty = `$HOME`)

**Response**
```json
{
  "current": "/home/user/data",
  "parent": "/home/user",
  "dirs": [
    { "name": "camtrap_dp", "path": "/home/user/data/camtrap_dp" }
  ]
}
```

---

## Session state

### `GET /api/health`

```json
{ "status": "ok" }
```

---

### `GET /api/state`

Current session state.

**Response (no active session)**
```json
{ "ready": false, "default_output_dir": "/home/user/Documents/camtrap_verify" }
```

**Response (active session)**
```json
{
  "ready": true,
  "session_dir": "/home/user/Documents/camtrap_verify/2025-11-01_120000",
  "config": {
    "camtrap_dir": "/path/to/camtrap_dp",
    "target_species": ["Sus scrofa", "Vulpes vulpes"],
    "study_start": "2025-11-01",
    "study_end": "2025-11-30",
    "occasion_days": 5,
    "total_iterations": 100000,
    "gap_seconds": 60,
    "min_score": 0.5
  }
}
```

---

## Session setup

### `POST /api/setup`

Create a new session: loads CamtrapDP, builds the sampling-period matrix, and generates the candidate manifest. Initial output files (`camtrap_dp_verified/`, `occupancy_inputs/`) are generated immediately.

**Body**
```json
{
  "camtrap_dir": "/absolute/path/to/camtrap_dp",
  "output_dir": "",
  "target_species": ["Sus scrofa", "Vulpes vulpes", "Cervus elaphus"],
  "study_start": "2025-11-01",
  "study_end": "2025-11-30",
  "occasion_days": 5,
  "total_iterations": 100000,
  "gap_seconds": 60,
  "min_score": 0.5
}
```

!!! note
    An empty `output_dir` uses `~/Documents/camtrap_verify`. Each call creates a timestamped sub-folder.

**Response**
```json
{
  "ok": true,
  "session_dir": "/home/user/Documents/camtrap_verify/2025-11-01_120000",
  "n_candidates": 12453,
  "n_combos": 147
}
```

---

## Species

### `GET /api/species`

List all target species with progress statistics and thumbnail URLs.

**Response**
```json
[
  {
    "species_name": "Cervus elaphus",
    "species_safe": "Cervus_elaphus",
    "n_total_combos": 21,
    "n_confirmed_combos": 18,
    "n_resolved": 21,
    "current_iteration": 2,
    "thumbnails": ["/api/image/abc123", "/api/image/def456"]
  }
]
```

---

### `GET /api/species/{species_safe}/events`

Pending sequences for a species in a given round.

**Path parameters**

| Parameter | Description |
|-----------|-------------|
| `species_safe` | Species name with non-alphanumeric characters replaced by `_` |

**Query params**: `iteration=1`

**Response**
```json
[
  {
    "key": "site_001_occ1_Cervus_elaphus",
    "siteId": "site_001",
    "occasion": 1,
    "rank": 1,
    "totalSeqs": 3,
    "repObsId": "d58afa28-be8e-4ba6-8f05-a7be0f56e757",
    "maxProb": 0.99,
    "frames": [
      {
        "obsId": "d58afa28-be8e-4ba6-8f05-a7be0f56e757",
        "mediaId": "c2efcabe-355b-437c-8a3e-87de5f993c38",
        "img": "/api/image/c2efcabe-355b-437c-8a3e-87de5f993c38",
        "ts": "2025-11-03 07:15",
        "prob": 0.99
      }
    ]
  }
]
```

!!! note "`rank` and `totalSeqs`"
    `rank` indicates which sequence is being shown (1 = highest confidence). `totalSeqs` is the total number of available sequences for that cell, allowing the UI to show "Sequence 1 / 3".

---

## Decisions

### `GET /api/decisions`

Saved decisions for a species and round (used to restore state on page reload).

**Query params**: `species=Cervus_elaphus&iteration=1`

**Response**
```json
{ "confirmed": ["d58afa28-be8e-4ba6-8f05-a7be0f56e757"] }
```

---

### `POST /api/decisions`

Save the confirmation decisions for a species and round. Automatically regenerates `camtrap_dp_verified/` and `occupancy_inputs/`.

**Body**
```json
{
  "species": "Cervus_elaphus",
  "iteration": 1,
  "confirmed": ["d58afa28-be8e-4ba6-8f05-a7be0f56e757"]
}
```

**Response**
```json
{
  "success": true,
  "saved": 1,
  "done": false,
  "next_iteration": 2,
  "remaining": 3
}
```

When `done: true` the species is complete and `next_iteration` is `null`.

---

## Images

### `GET /api/image/{media_id}`

Serve an image from the local file system.

---

### `GET /api/proxy-image`

Proxy for remote images (e.g. a Trapper platform with authentication).

**Query params**: `url=https://server/image.jpg`

---

## Rejection management

### `GET /api/rejected`

Manually rejected `mediaID`s (excluded from future rounds).

```json
{ "rejected": ["m0000003", "m0000004"] }
```

---

### `POST /api/reject`

Reject the entire sequence that contains the given frame.

**Body** `{ "mediaId": "m0000003" }`

**Response** `{ "success": true, "removed": ["m0000003", "m0000004"] }`

---

### `POST /api/unreject`

Restore previously rejected media.

**Body** `{ "media": ["m0000003", "m0000004"] }`

---

## Results and export

### `GET /api/results`

Verification summary for the active session.

**Response**
```json
{
  "session_dir": "/home/user/Documents/camtrap_verify/2025-11-01_120000",
  "output_dir": "/home/user/Documents/camtrap_verify/2025-11-01_120000/camtrap_dp_verified",
  "occupancy_dir": "/home/user/Documents/camtrap_verify/2025-11-01_120000/occupancy_inputs",
  "total": 147,
  "confirmed": 103,
  "rejected": 0,
  "unverified": 44,
  "by_species": [
    {
      "species": "Cervus elaphus",
      "confirmed": 18,
      "rejected": 0,
      "unverified": 3
    }
  ]
}
```

---

### `POST /api/open-folder`

Open the session directory in the operating system's file manager.

**Response** `{ "ok": true, "path": "/home/user/Documents/camtrap_verify/2025-11-01_120000" }`
