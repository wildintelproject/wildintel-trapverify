# CamTrap Verify

**CamTrap Verify** is an open-source web tool for the iterative expert verification of automatic camera-trap classifications. Its goal is to minimise the review effort by directing expert attention to the events most likely to change the outcome of a species occupancy analysis.

---

## How it works

```
CamtrapDP directory
  (deployments + media + observations)
           │
           ▼
   Sampling periods  (site × period × species)
           │
           ▼
   Review gallery ──► Confirm / Reject
           │
           ▼
   Round 2: next lowest-confidence sequence
           │
           ▼
  camtrap_dp_verified/  +  occupancy_inputs/
```

1. **Ingest** any [CamtrapDP v1.0](https://camtrap-dp.tdwg.org/) directory produced by an AI classifier or citizen-science platform.
2. **Build** a matrix of sampling periods (fixed time windows per location) and group consecutive images into **sequences**, ranked by detection confidence.
3. **Serve** a web gallery where the expert confirms or rejects each sequence — with zoom, pan, tonal inversion, and keyboard navigation.
4. **Export** outputs ready for occupancy models: naive vs. verified detection histories, camera-operation matrix, and per-species summary.

---

## Technology stack

| Layer | Technology |
|-------|-----------|
| Backend | [FastAPI](https://fastapi.tiangolo.com/) · Python 3.13 · pandas |
| Frontend | [React](https://react.dev/) 19 · TypeScript · Bootstrap 5.3 |
| Python tooling | [uv](https://docs.astral.sh/uv/) |
| i18n | i18next (ES / EN) |
| Docs | [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) |

---

## Quick links

- [About the project](about.md) — background, funding, and WildINTEL context
- [Features](features.md) — full list of capabilities
- [Installation](installation.md) — from source or pre-built binaries
- [Quick start](quickstart.md) — step-by-step usage guide
- [Configuration](configuration.md) — session parameters and `.env` reference
- [Workflow](workflow.md) — iterative review logic and output files
- [API reference](api.md) — REST endpoints
- [Developer guide](developer.md) — set up, test, and contribute
