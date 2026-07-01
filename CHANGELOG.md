# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-07-01

### Added
- German (Deutsch) and Polish (Polski) UI translations.
- Occupancy model: fitted per species and integrated into the results page.
- File browser API endpoint for listing filesystem contents from the UI.
- New conversion endpoints for Custom CSV and DeepFaune CSV import flows.
- AppImage packaging for Linux (self-contained, no installation required).
- Windows portable `.exe` and Inno Setup installer in the release workflow.

### Changed
- Setup page now shows separate screenshots for sampling parameters and confirmation sections.
- Column mapping section includes an introductory explanation with screenshot placeholder.
- Back button is now displayed at the same level as the Convert button in DeepFaune and Custom CSV sub-forms.

### Fixed
- Lightbox left/right navigation is now bounded to the current sampling period; up/down arrows switch between sampling periods within the same location.

## [0.2.0] - 2026-06-30

### Fixed
- Documentation links in Navbar and README now point to the correct project website and user manual URLs.

### Changed
- Documentation deployment workflow updated to use `mike` for versioned docs.
- Previous alias is deleted before deploying a new version with `mike`.

## [0.1.0] - 2026-06-30

### Added
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

[Unreleased]: https://github.com/wildintelproject/wildintel-trapverify/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/wildintelproject/wildintel-trapverify/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/wildintelproject/wildintel-trapverify/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wildintelproject/wildintel-trapverify/releases/tag/v0.1.0
