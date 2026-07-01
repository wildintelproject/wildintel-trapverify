# CamTrap Verify — Developer Manual

This document covers the project architecture, development setup, configuration, build process and CI/CD pipeline.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Project Structure](#3-project-structure)
4. [Development Setup](#4-development-setup)
5. [Configuration](#5-configuration)
6. [Building for Production](#6-building-for-production)
7. [Building Installers and Packages](#7-building-installers-and-packages)
8. [CI/CD — GitHub Actions](#8-cicd--github-actions)
9. [Backend API Reference](#9-backend-api-reference)
10. [Frontend Architecture](#10-frontend-architecture)
11. [Contributing](#11-contributing)
12. [Releasing a New Version](#12-releasing-a-new-version)

---

## 1. Architecture Overview

CamTrap Verify is a **local-first web application**: the backend runs on the user's machine and the frontend is served either by the backend (packaged build) or by a Vite dev server (development mode).

```
┌────────────────────────────────────────────────────────────┐
│  Browser                                                   │
│  React 19 SPA (TypeScript + Vite + TailwindCSS)           │
└────────────────────┬───────────────────────────────────────┘
                     │ HTTP / REST
┌────────────────────▼───────────────────────────────────────┐
│  Backend — FastAPI + Uvicorn (Python 3.13)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ session_svc  │  │ workflow_svc │  │  results_svc     │ │
│  └──────────────┘  └──────────────┘  └──────────────────┘ │
│  In-memory state · pandas DataFrames · JSON/CSV on disk   │
└────────────────────────────────────────────────────────────┘
```

In **production / packaged mode**, the backend also mounts the frontend's static build at `/` (see `backend/src/main.py`) and serves the API under `/api/*`.

In **development mode**, the Vite dev server runs on port 5173 and proxies `/api` requests to the backend on port 8765.

---

## 2. Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.13+ | Backend |
| [uv](https://github.com/astral-sh/uv) | latest | Python package manager |
| Node.js | 18+ | Frontend build |
| npm | 9+ | Frontend dependencies |
| Docker + Compose | any recent | Production deployment |

---

## 3. Project Structure

```
wildintel-trapverify/
├── backend/
│   ├── src/
│   │   ├── api/
│   │   │   └── routers/        # FastAPI routers (one file per domain)
│   │   ├── schemas/            # Pydantic request/response models
│   │   ├── services/           # Business logic (session, workflow, results…)
│   │   ├── app_entry.py        # PyInstaller entry point
│   │   ├── camtrap_workflow.py # CamtrapDP processing logic
│   │   ├── main.py             # FastAPI app factory
│   │   └── settings.py         # Configuration (pydantic-settings)
│   ├── docs/                   # MkDocs source (backend / API docs)
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   ├── Dockerfile              # Production image
│   ├── Dockerfile.build        # Linux package builder (fpm + PyInstaller)
│   ├── Dockerfile.build.windows # Windows exe builder via Wine (optional)
│   └── mkdocs.yml
├── frontend/
│   ├── src/
│   │   ├── components/         # Shared UI components
│   │   ├── locales/            # i18n translations (en.json, es.json)
│   │   ├── pages/              # Route-level components
│   │   ├── api.ts              # API client
│   │   └── main.tsx            # App entry point
│   ├── public/
│   └── vite.config.ts
├── docs/                       # User-facing documentation (this directory)
├── installer/
│   └── windows.iss             # Inno Setup script
├── .github/
│   └── workflows/
│       ├── docs.yml            # Deploy MkDocs to GitHub Pages
│       └── release.yml         # Build Linux packages + Windows installer
├── cli.py                      # Project management CLI (uv run cli …)
├── pyproject.toml
├── docker-compose.yml
├── Caddyfile                   # Reverse proxy config (production)
└── .env.example
```

---

## 4. Development Setup

### Clone and install

```bash
git clone https://github.com/your-org/wildintel-trapverify.git
cd wildintel-trapverify
uv sync --group dev        # installs Python deps + dev tools (mkdocs, pyinstaller…)
cd frontend && npm install # installs Node deps
cd ..
```

### Run backend + frontend together

```bash
uv run cli dev
```

This starts:
- Uvicorn on `http://localhost:8765` (hot-reload)
- Vite dev server on `http://localhost:5173`

Open `http://localhost:5173` in your browser.

### Run separately

```bash
# Backend only
uv run cli backend serve dev [--port 8765]

# Frontend only
uv run cli frontend dev [--port 5173]
```

### Debug mode (VSCode / debugpy)

```bash
uv run cli backend serve debug
# Attach to localhost:5678 from your IDE
```

### Tests

```bash
uv run cli backend test           # all tests
uv run cli backend test unit      # unit tests only
uv run cli backend test integration

uv run cli frontend lint          # oxlint
```

---

## 5. Configuration

All backend settings use the `CAMTRAP_` prefix and can be set via environment variables or `.env` files.

| Variable | Default | Description |
|---|---|---|
| `CAMTRAP_PORT` | `8765` | Backend API port |
| `CAMTRAP_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `CAMTRAP_CORS_ORIGINS` | `["http://localhost:5173",…]` | Allowed browser origins |
| `CAMTRAP_APP_DIR` | `~/.config/camtrap_verify` | Session pointer and config storage |
| `CAMTRAP_DEFAULT_OUTPUT_DIR` | `~/Documents/camtrap_verify` | Default output directory |

**`.env` search order** (highest priority last):

1. `<binary dir>/.env` — next to the executable or `backend/src/`
2. `~/.config/camtrap_verify/.env` — user config dir

Copy `.env.example` to either location and edit as needed.

> The frontend port is not an env variable — pass it to the CLI: `uv run cli dev --frontend-port 5173`

---

## 6. Building for Production

### Docker Compose (recommended)

```bash
uv run cli prod up          # builds images and starts in background
uv run cli prod down        # stop and remove containers
uv run cli prod logs -f     # follow logs
```

The stack runs three containers:
- `backend` — FastAPI / Uvicorn
- `frontend` — Nginx serving the Vite build
- `caddy` — Reverse proxy (handles `/api` → backend, `/` → frontend)

### Manual frontend build

```bash
uv run cli frontend build   # output → frontend/dist/
```

The production build is a static SPA. When placed in `backend/frontend/dist/`, the backend serves it automatically at `/`.

---

## 7. Building Installers and Packages

Use the `package` subcommand. Docker must be running for Linux packages.

```bash
# All formats (.deb, .rpm, .exe)
uv run cli package build

# Specific format
uv run cli package build --format deb
uv run cli package build --format rpm
uv run cli package build --format windows

# Explicit version
uv run cli package build --version 1.2.3
```

Output goes to `dist/`.

### How the Windows build works

1. The frontend is built with `npm run build` → `frontend/dist/`.
2. PyInstaller bundles the backend with `--onefile`, embedding the frontend via `--add-data "../frontend/dist:static"`.
3. The result is a single `.exe` that starts a local server and opens the browser automatically.
4. Inno Setup wraps the `.exe` in an installer (`installer/windows.iss`).

Two artefacts are produced:
- `camtrap-verify-backend-X.Y.Z-windows-x64.exe` — portable, no installation needed.
- `camtrap-verify-setup-X.Y.Z-windows-x64.exe` — installer with Start Menu shortcut and uninstaller.

### How the Linux build works

A multi-stage Docker build (`backend/Dockerfile.build`) runs PyInstaller inside a container and then uses [fpm](https://fpm.readthedocs.io/) to produce `.deb` and `.rpm` packages. The binary installs to `/opt/camtrap-verify-backend/` with a wrapper script at `/usr/local/bin/camtrap-verify-backend`.

---

## 8. CI/CD — GitHub Actions

Two workflows live in `.github/workflows/`:

### `docs.yml` — Documentation

Triggers on push to `main` when docs-related files change, and on manual dispatch.

Steps:
1. Install Python deps (`uv sync --group dev`).
2. Build MkDocs site (`mkdocs build`).
3. Deploy to **GitHub Pages**.

> Enable Pages in the repo settings: **Settings → Pages → Source: GitHub Actions**.

### `release.yml` — Release

Triggers on `v*` tags or manual dispatch.

| Job | Runner | Output |
|---|---|---|
| `build-linux` | `ubuntu-latest` | `.deb` and `.rpm` via Docker |
| `build-windows` | `windows-latest` | portable `.exe` + Inno Setup installer |
| `release` | `ubuntu-latest` | GitHub Release with all artefacts |

To publish a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Manual dispatch (no tag) builds the packages as workflow artefacts but does not create a GitHub Release.

---

## 9. Backend API Reference

The backend exposes a REST API under `/api`. Interactive Swagger docs are available at `http://localhost:8765/docs` when running in development mode.

### Routers

| Prefix | File | Description |
|---|---|---|
| `/api/health` | `health.py` | Liveness check |
| `/api/fs` | `fs.py` | Filesystem browser (directory picker) |
| `/api/session` | `session.py` | Session lifecycle (setup, load, state) |
| `/api/species` | `species.py` | Species list and per-species stats |
| `/api/decisions` | `decisions.py` | Read / write review decisions |
| `/api/media` | `media.py` | Image serving and remote proxy |
| `/api/results` | `results.py` | Computed results and output generation |
| `/api/trapper` | `trapper.py` | Trapper integration (in development) |

### Services

| Module | Responsibility |
|---|---|
| `session_service` | In-memory session state, persistence to `last_session.json` |
| `workflow_service` | CamtrapDP processing, round logic, output generation |
| `results_service` | Aggregates decisions into summary statistics |
| `trapper_service` | Trapper API client |

---

## 10. Frontend Architecture

The frontend is a **React 19 SPA** built with Vite, TypeScript and TailwindCSS.

### Routing

```
/              → SetupPage   (welcome screen + 4-step wizard)
/species       → IndexPage   (species grid)
/gallery/:sp   → GalleryPage (image review for species :sp)
/results       → ResultsPage
```

### Key dependencies

| Package | Purpose |
|---|---|
| `react-router-dom` | Client-side routing |
| `i18next` / `react-i18next` | Internationalisation (en / es) |
| `yet-another-react-lightbox` | Fullscreen image lightbox |
| `tailwindcss` | Utility-first CSS |

### Adding a translation

Edit both `frontend/src/locales/en.json` and `frontend/src/locales/es.json`. Use `t('key')` in components and `useTranslation()` hook.

### API client

All HTTP calls go through `frontend/src/api.ts`. The base URL is `/api` in production (same origin) and `http://localhost:8765/api` in development (configured in `vite.config.ts` via proxy).

---

## 11. Contributing

1. Fork the repository and create a feature branch.
2. Install dependencies: `uv sync --group dev && cd frontend && npm install`.
3. Run `uv run cli dev` and verify your changes work end-to-end.
4. Run the backend tests: `uv run cli backend test`.
5. Run the frontend linter: `uv run cli frontend lint`.
6. Open a pull request against `main`.

### Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add brightness control to lightbox
fix: correct auto-advance index after decision
docs: update configuration table
```

---

## 12. Releasing a New Version

### 1. Update `CHANGELOG.md`

Open `CHANGELOG.md` and move all entries from **Upcoming release** into a new versioned section:

```markdown
## [X.Y.Z](https://github.com/wildintelproject/wildintel-trapverify/compare/vX.Y.Z-1...vX.Y.Z) - YYYY-MM-DD

### Added
- ...

### Changed
- ...

### Fixed
- ...

**Full Changelog:** [`vX.Y.Z-1...vX.Y.Z`](https://github.com/wildintelproject/wildintel-trapverify/compare/vX.Y.Z-1...vX.Y.Z)
```

Then restore the **Upcoming release** section as empty, ready for the next cycle:

```markdown
## Upcoming release

### Added
### Changed
### Fixed
```

### 2. Commit the changelog

```bash
git add CHANGELOG.md
git commit -m "chore: release vX.Y.Z"
```

### 3. Merge to `main`

Make sure all changes intended for this release are merged into `main`:

```bash
git checkout main
git merge development
git push origin main
```

### 4. Tag and push

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Pushing a `v*` tag triggers the `release.yml` workflow automatically. It will:

- Build the Linux packages (`.deb`, `.rpm`, `.AppImage`) via Docker.
- Build the Windows packages (portable `.exe` + Inno Setup installer) via PyInstaller.
- Extract the release notes for `vX.Y.Z` from `CHANGELOG.md` and publish a GitHub Release with all artefacts attached.

### 5. Update the GitHub Release notes for past releases *(first time only)*

If you need to backfill release notes for releases published before the `CHANGELOG.md` workflow was set up, edit each release manually on GitHub and paste the corresponding section from `CHANGELOG.md`.
