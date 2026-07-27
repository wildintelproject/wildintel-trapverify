# Changelog

WildINTEL project provides up-to-date release notes for the CamTrap Verify application on all supported platforms. This
document contains information about recent changes, including new features, bug fixes, and improvements. It is intended to 
help users and developers understand the evolution of the project over time. 

You can download the latest version of CamTrap Verify from the [releases page](https://github.com/wildintelproject/wildintel-trapverify/releases).

To report a bug or request a new feature, please open an [issue](https://github.com/wildintelproject/wildintel-trapverify/issues).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),  and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Upcoming release

## Released 

**Note:** The information in past release notes may have been superseded by newer releases. Please refer to the latest release for the most up-to-date information.

### [0.4.0](https://github.com/wildintelproject/wildintel-trapverify/compare/v0.3.0...v0.4.0) - 2026-07-27

#### Added
- Optional **Images directory** field in the CamtrapDP setup flow: when provided, relative `filePath` values in `media.csv` are resolved against this directory instead of the parent of the data directory.
- **Download results** button on the Results page: generates a ZIP file of the full session directory (`wildintel-camtrap-verify-{session_id}.zip`) and triggers a browser download.
- macOS DMG package (`camtrap-verify-X.Y.Z-macos-arm64.dmg`) added to the release workflow for Apple Silicon.
- GitHub repository link (icon, stars, forks) added to the documentation header via `repo_url` in `mkdocs.yml`.
- `CHANGELOG.md` with release history following the Keep a Changelog format.
- Release notes section in the developer manual describing the full release process.
- `flat_search` option added to the setup request schema and workflow config (backend/frontend type wiring for a non-recursive directory search).
- Optional **Output directory** field in the setup wizard's Parameters step, with a directory browser, so a session's folder no longer always defaults silently to `~/Documents/camtrap_verify` — the backend and its config already supported a custom `output_dir`, but no UI ever exposed it.
- When a source directory (local pick or Trapper download) already ships a `datapackage.json`, `/api/fs/inspect` now validates it with `frictionless` and the setup wizard shows any schema/data errors as a non-blocking warning — helps catch a malformed source package instead of silently working around it.
- When the source package has no `datapackage.json` at all (converted from a DeepFaune/generic CSV, or a CamtrapDP source that simply never had one), `export_verified_camtrapdp()` now generates a best-effort default via `generate_default_datapackage()` instead of leaving the exported package without one. It derives `temporal`/`taxonomic`/`project.observationLevel` from the data and `spatial` from `deployments.csv` coordinates when present, and invents placeholders for everything it can't know (`contributors`, `project.title`/`samplingDesign`/`captureMethod`/`individualAnimals`, `spatial` when no coordinates exist). The Results page shows a warning listing exactly which fields were invented, read from the generated file's `wildintelGenerated.fabricatedFields` marker — the process is never blocked by a missing or invented descriptor.

#### Changed
- `export_verified_camtrapdp()` now also copies `datapackage.json` unchanged into `camtrap_dp_verified/` when the source package has one, instead of dropping it — only the values in `observations.csv` change, not its schema, so the original descriptor still describes the exported package correctly and it stays usable by other CamtrapDP tools.
- **Show all event frames** (formerly *Show event context images*): reworked logic so that only frames captured between the first and last detection of the target species are included, preventing frames from adjacent animal visits from appearing in the carousel.
- **Gallery review cards** now open on the sequence frame with the highest detection confidence instead of the chronologically first one; the zoom button opens the lightbox at that same frame instead of always the first.
- The Trapper integration (`trapper_service.py`) now uses `wildintel-trapper-sdk` instead of a hand-rolled `httpx.AsyncClient` wrapper, with SDK calls run via `asyncio.to_thread` to keep the event loop unblocked. Behavior-preserving; error responses now map the SDK's typed exceptions to HTTP status codes.

#### Fixed
- `media.csv` timestamps that mix timezone-aware and timezone-naive values (or different UTC offsets) no longer crash `/api/fs/inspect` and `/api/setup` with `ValueError: Mixed timezones detected` — `normalise_ts()` now strips any UTC offset/`Z` suffix before parsing, since every caller only uses the resulting timestamp as wall-clock local time (sampling occasion assignment, burst gaps, display), never as an absolute instant.
- The Linux `.deb`/`.rpm` package build no longer fails with `Git executable not found` — the build image now installs `git`, needed since `wildintel-trapper-sdk` is a git-sourced dependency.
- macOS installation instructions (Gatekeeper workaround) rewritten to use only GUI steps (double-click, System Settings → Privacy & Security → Open Anyway), removing the terminal-based quarantine-removal alternative.
- The **Minimum detection score** setting was never applied to the review workflow — `build_candidates()` had no `min_score` parameter, so events were included regardless of confidence. Frames whose own classification probability falls below the configured threshold are now demoted before bursts are grouped, matching the reference R tool's per-frame `to_camtrapdp()` threshold (a frame with no score at all is never demoted).
- `/api/image/{mediaID}` now sends `Cache-Control: no-store`, so the browser always revalidates against the backend instead of reusing a previously cached image for the same mediaID — a stale browser cache could otherwise keep showing a photo after it was moved or deleted between sessions.
- **Show all event frames** no longer collapses to a zero-width time window for detection events with a single target-species frame (the dominant case) — the burst window is now padded by `gap_seconds` on each side before looking up neighbouring frames, matching the reference R tool, so those events can actually show context frames instead of silently showing none.
- Frames sharing the exact same timestamp within a burst (e.g. second-resolution timestamps from some exports) are now ordered by a trailing numeric suffix in the file name (`..._1.JPEG` → 1) instead of an arbitrary order, matching the reference R tool's capture-order tiebreak.
- `deepfaune_to_camtrapdp()` had the confidence-score column name hardcoded to `score`, so a caller using DeepFaune's older `predictionbase`/`scorebase` columns directly (bypassing the API router's rename workaround) would silently get `NaN` scores. A `score_col` parameter now makes it configurable, same as `label_col`. The "Convert DeepFaune CSV" step also now shows which columns were auto-detected (`predictionbase`/`scorebase` vs. `top1`/`score`) instead of converting silently.
- `predictionbase`/`scorebase` (DeepFaune's per-image base classifier) now take priority over `top1`/`score` when a CSV has both, matching the reference R tool — previously `top1`/`score` always won, silently ignoring `predictionbase`/`scorebase`.
- The in-process flat-search file index (used when the *Images directory* option's subfolder search is enabled) is now cleared at the start of every `/api/setup`, so starting a new session no longer risks resolving images against a listing scanned before files were added, moved, or removed on disk.

**Full Changelog:** [`v0.3.0...v0.4.0`](https://github.com/wildintelproject/wildintel-trapverify/compare/v0.3.0...v0.4.0)

### [0.3.0](https://github.com/wildintelproject/wildintel-trapverify/compare/v0.2.0...v0.3.0) - 2026-07-01

#### Added
- German (Deutsch) and Polish (Polski) UI translations.
- Occupancy model: fitted per species and integrated into the results page.
- File browser API endpoint for listing filesystem contents from the UI.
- New conversion endpoints for Custom CSV and DeepFaune CSV import flows.
- AppImage packaging for Linux (self-contained, no installation required).
- Windows portable `.exe` and Inno Setup installer in the release workflow.

#### Changed
- Setup page now shows separate screenshots for sampling parameters and confirmation sections.
- Column mapping section includes an introductory explanation with screenshot placeholder.
- Back button is now displayed at the same level as the Convert button in DeepFaune and Custom CSV sub-forms.

#### Fixed
- Lightbox left/right navigation is now bounded to the current sampling period; up/down arrows switch between sampling periods within the same location.

**Full Changelog:** [`v0.2.0...v0.3.0`](https://github.com/wildintelproject/wildintel-trapverify/compare/v0.2.0...v0.3.0)

### [0.2.0](https://github.com/wildintelproject/wildintel-trapverify/compare/v0.1.0...v0.2.0) - 2026-06-30

#### Fixed
- Documentation links in Navbar and README now point to the correct project website and user manual URLs.

#### Changed
- Documentation deployment workflow updated to use `mike` for versioned docs.
- Previous alias is deleted before deploying a new version with `mike`.

**Full Changelog:** [`v0.1.0...v0.2.0`](https://github.com/wildintelproject/wildintel-trapverify/compare/v0.1.0...v0.2.0)

### [0.1.0](https://github.com/wildintelproject/wildintel-trapverify/releases/tag/v0.1.0) - 2026-06-30

#### Added
- Initial release of CamTrap Verify.
- FastAPI backend with routers for decisions, filesystem, health, media, session, and species management.
- React/TypeScript frontend with Tailwind CSS, dark mode, and directory picker.
- CamtrapDP v1.0 import workflow (deployments, media, observations).
- DeepFaune CSV and Custom CSV import converters.
- Gallery page with species card review, lightbox viewer, image filters (brightness, contrast, invert, rotate), and keyboard shortcuts (Y/N).
- Results page with per-species decision summary.
- In-app version check with update notification banner.
- CI workflow for unit and integration tests.
- Release workflow for Linux (`.deb`, `.rpm`) and Windows packages.
- MkDocs documentation site with user manual and developer guide.
- Docker Compose setup for local development (Caddy + backend + frontend).

**Full Changelog:** [`v0.1.0`](https://github.com/wildintelproject/wildintel-trapverify/releases/tag/v0.1.0)
