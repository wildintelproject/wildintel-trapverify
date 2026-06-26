# Usage guide

This guide walks through a complete verification session from start to finish. It assumes the server is running (see [Installation](installation.md)).

---

## 1. Start the server

```bash
uv run cli serve          # development mode
```

Open **`http://localhost:8765`** in your browser (or whatever port you configured).

---

## 2. Create a new session

On the welcome page click **New session** and complete the four-step setup wizard.

### Step 1 — CamtrapDP directory

Enter the absolute path to your CamtrapDP directory (the folder containing `deployments.csv`, `media.csv`, and `observations.csv`):

```
/home/user/data/my_camtrap_dataset
```

!!! tip "Using the file browser"
    Click **Browse** to navigate the server's file system and select the folder interactively.

The application reads the CSV files immediately and detects the available species and date range.

### Step 2 — Target species

Select the species you want to verify. Only species present in `observations.csv` with `observationType = "animal"` and at least one detection above the minimum score are listed.

### Step 3 — Study period

| Field | Description |
|-------|-------------|
| Start date | First day of the study window (`YYYY-MM-DD`) |
| End date | Last day of the study window |

### Step 4 — Sampling parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Sampling period duration | 5 days | Length of each occupancy occasion |
| Sequence gap | 60 s | Images separated by less than this belong to the same sequence |
| Minimum score | 0.5 | Classification confidence threshold; frames below this are ignored |

Click **Start verification**. The backend builds the candidate manifest and creates the output directory. This may take a few seconds for large datasets.

---

## 3. Review species

The index page shows one card per target species, with a progress bar and a round badge.

**Badge colour guide**

| Colour | Meaning |
|--------|---------|
| Green | Round 1 — highest-confidence sequences |
| Yellow | Round 2 |
| Orange | Round 3 |
| Red | Round 4+ — lowest-confidence sequences |

Click a species card to open its gallery.

---

## 4. The gallery

The gallery groups cards by **location**. Each card represents one **site × sampling-period** combination and shows the current round's top-ranked sequence.

### Within a card

- The **"Sequence N / M"** badge tells you which ranked sequence you are looking at and how many are available for this period.
- The **"Frame N / M"** counter shows your position within the current sequence.
- Use the `‹` and `›` arrows (or keyboard arrow keys) to navigate frames.
- Click the image or the zoom button to open the **lightbox**.

### Lightbox controls

| Action | Control |
|--------|---------|
| Zoom in/out | Mouse wheel |
| Pan | Click and drag |
| Invert colours | Toggle button (useful for IR images) |
| Next / previous period | Left / right arrows |
| Close | `Esc` or click outside |

### Making decisions

For each card, choose:

- **Confirm** — the species is present; the cell is marked as a detection (1) and will not appear again.
- **Reject** — false positive; in the next round, the rank-2 sequence will be shown for this cell.

!!! warning "All cards must be decided before saving"
    The **Save decisions** button is enabled only when every visible card has been confirmed or rejected.

Click **Save decisions** to commit the round. The backend regenerates the output files immediately.

---

## 5. Subsequent rounds

After saving, confirmed cells disappear. Cards for rejected cells reappear in round 2 showing the next-ranked sequence. Repeat the process until a species shows **Complete** — meaning no more candidate sequences remain.

---

## 6. Results

Once all species are complete, navigate to the **Results** tab. You will see:

- A summary table with confirmed, rejected, and unverified counts per species.
- The session output directory path.
- A button to open the directory in your file manager.

### Output directory structure

```
~/Documents/camtrap_verify/<session_timestamp>/
├── config.json                         session configuration
├── candidate_manifest.csv              all candidate frames, ranked
├── rejected_media.json                 manually rejected media IDs
├── decisions/
│   └── decisions_<species>_iter<N>.csv confirmed observations per round
├── camtrap_dp_verified/
│   ├── deployments.csv
│   ├── media.csv
│   └── observations.csv               confirmed obs flagged as "human"
└── occupancy_inputs/
    ├── camera_operation.csv            active days per site × period
    ├── dethist_naive_<species>.csv     classifier-based detection history
    ├── dethist_verified_<species>.csv  expert-verified detection history
    ├── verification_summary.csv        per-species ψ_obs naive vs. verified
    └── review_effort.csv               images actually inspected
```

See [Workflow](workflow.md) for a full description of each file, and [Configuration](configuration.md) for all session parameters.

---

## Session persistence

The active session survives server restarts. When you reopen the application, the last session is restored automatically from `~/.config/camtrap_verify/last_session.json`. To start a completely new session, click **New session** on the welcome page.
