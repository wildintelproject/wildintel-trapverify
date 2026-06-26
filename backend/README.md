# <img src="docs/img/wildIntel_logo.webp" alt="WildINTEL Logo" height="60">  CamTrap Verify — Backend

![Python](https://img.shields.io/badge/python-3.13-blue.svg)
![License](https://img.shields.io/badge/license-GPLv3-blue.svg)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.138-009688)](https://fastapi.tiangolo.com/)
[![uv](https://img.shields.io/badge/uv-package_manager-5C4EE5)](https://github.com/astral-sh/uv)

<hr>

## REST API for the CamTrap Verify backend

REST API of the **CamTrap Verify** backend, built with [FastAPI](https://fastapi.tiangolo.com/) and [pandas](https://pandas.pydata.org/). It manages the verification session, implements the iterative review workflow and generates all outputs for species occupancy models.

## ✨ Features

- Loads any [CamtrapDP v1.0](https://camtrap-dp.tdwg.org/) directory and builds the candidate manifest
- Iterative review logic: ranks sequences by classification confidence per site × period × species
- Exports `camtrap_dp_verified/` with confirmed observations tagged as human classifications
- Generates naive vs. verified detection histories and camera-operation matrices (`occupancy_inputs/`)
- Session persistence: the active session survives server restarts

## 📋 Requirements

- Python 3.13+ with [uv](https://github.com/astral-sh/uv)
- Docker (only required for package builds)

## 📚 Documentation

Full documentation is available under `docs/`. To serve it locally:

```bash
uv run mkdocs serve   # → http://127.0.0.1:8000
```

Full online documentation at:
**https://wildintelproject.github.io/wildintel-trap-verify/**

## 🚀 Quick start

```bash
# Check requirements and install dependencies
./setup.sh

# Start in development mode (hot-reload)
uv run cli serve

# Start in production mode
uv run cli serve prod

# Start in debug mode (debugpy on port 5678)
uv run cli serve debug
```

`setup.sh` verifies that Docker and [uv](https://github.com/astral-sh/uv) are available, installs uv automatically if missing, and runs `uv sync` to install all Python dependencies. All server management is handled by `cli`.

The API will be available at `http://localhost:8765`. Interactive Swagger UI at `http://localhost:8765/docs`.

## 🛠️ CLI

`cli.py` is a [Typer](https://typer.tiangolo.com/) CLI registered as a `uv run cli` script that centralises all management tasks.

### Server

```bash
uv run cli serve                    # dev mode, port 8765 (default)
uv run cli serve prod
uv run cli serve debug              # debugpy listening on :5678
uv run cli serve dev --port 9000
uv run cli serve --help
```

### Documentation

```bash
uv run cli docs serve               # → http://127.0.0.1:8000
uv run cli docs build               # → backend/site/
```

### Packages

```bash
uv run cli package build                        # .deb + .rpm + .exe (git tag version)
uv run cli package build --format deb
uv run cli package build --format rpm
uv run cli package build --format windows       # .exe (Docker + Wine on Linux/macOS)
uv run cli package build --format rpm --version 1.2.0
```

Packages are built using Docker and output to `dist/`. Requires Docker to be running.

## 🧪 Tests

```bash
uv run pytest tests/unit/           # unit tests (~2 s)
uv run pytest tests/integration/    # integration tests (real server)
uv run pytest                       # all
```

```
tests/
├── conftest.py             ← shared fixtures
├── unit/
│   ├── test_workflow.py    ← 59 tests for camtrap_workflow.py
│   └── test_api.py         ← 41 endpoint tests with TestClient
└── integration/
    └── test_integration.py ← 25 tests with real uvicorn + httpx
```

## 🗂️ Project structure

```
backend/
├── src/                        ← application source code
│   ├── main.py                 ← REST endpoints (FastAPI)
│   ├── camtrap_workflow.py     ← period, sequence, ranking and export logic
│   ├── settings.py             ← pydantic-settings config (reads .env)
│   └── app_entry.py            ← PyInstaller entry point
├── cli.py                      ← management CLI (uv run cli)
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── docs/                       ← MkDocs source
├── Dockerfile.build            ← builds .deb / .rpm via Docker
├── Dockerfile.build.windows    ← cross-compiles .exe via Docker + Wine
├── pyproject.toml
├── setup.sh
└── .env.example
```

## ⚙️ Configuration

Copy `.env.example` to `.env` and edit as needed. Settings are read in this priority order (highest wins):

1. Environment variables (`CAMTRAP_PORT=9000 uv run cli serve`)
2. `~/.config/camtrap_verify/.env`
3. `.env` next to the binary / module

## 📁 Session output

Each session creates a timestamped directory under `~/Documents/camtrap_verify/`:

```
<session_dir>/
├── config.json
├── candidate_manifest.csv
├── decisions/
├── camtrap_dp_verified/         ← CamtrapDP with confirmed observations
└── occupancy_inputs/            ← detection histories and camera effort
```

See [`docs/configuration.md`](docs/configuration.md) for a full description of every output file.

## 🤝 Contributing

Contributions are welcome! Please feel free to open an issue or submit a pull request.

## 📝 License

This project is licensed under the GNU General Public License v3.0 or later — see the [LICENSE](../LICENSE) file for details.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

## 🏛️ Funding

This work is part of the [WildINTEL project](https://wildintel.eu/), funded by the [Biodiversa+](https://www.biodiversa.eu/) Joint Research Call 2022-2023 "Improved transnational monitoring of biodiversity and ecosystem change for science and society (BiodivMon)". Biodiversa+ is the European co-funded biodiversity partnership supporting excellent research on biodiversity with an impact for policy and society. Biodiversa+ is part of the European Biodiversity Strategy for 2030 that aims to put Europe's biodiversity on a path to recovery by 2030 and is co-funded by the European Commission.

WildINTEL has been co-funded by the [European Commission](https://commission.europa.eu/) (GA No. 101052342) and the following funding organisations: [Agencia Estatal de Investigación](https://www.aei.gob.es/) (Spain, PCI2023-145963-2, PCI2024-153489), [National Science Centre](https://www.ncn.gov.pl/?language=en) (Poland, UMO-2023/05/Y/NZ8/00104), the [Research Council of Norway](https://www.forskningsradet.no/en/) (Norway, NFR350962) and the [German Research Foundation](https://www.dfg.de/en/) (Germany).
