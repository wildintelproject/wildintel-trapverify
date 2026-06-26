# Developer guide

This guide covers setting up a development environment, running the test suite, understanding the project structure, and contributing changes.

---

## Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| Python | 3.13 | [python.org](https://www.python.org/) |
| [uv](https://docs.astral.sh/uv/) | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | 24+ | [docs.docker.com](https://docs.docker.com/get-docker/) — only for package builds |
| Git | any | — |

---

## Project structure

```
backend/
├── src/                            application source code
│   ├── main.py                     REST endpoints (FastAPI)
│   ├── camtrap_workflow.py         sampling periods, sequences, ranking, exports
│   ├── settings.py                 pydantic-settings config (reads .env)
│   └── app_entry.py                PyInstaller entry point (desktop binary)
├── cli.py                          Typer management CLI (uv run cli)
├── tests/
│   ├── conftest.py                 shared fixtures and sys.path setup
│   ├── unit/
│   │   ├── test_workflow.py        ~59 tests for camtrap_workflow.py
│   │   └── test_api.py             ~41 endpoint tests with TestClient
│   └── integration/
│       └── test_integration.py     ~25 tests with a real uvicorn server + httpx
├── docs/                           MkDocs source (this documentation)
├── Dockerfile.build                builds .deb / .rpm via Docker + fpm
├── Dockerfile.build.windows        cross-compiles .exe via Docker + Wine
├── mkdocs.yml                      MkDocs configuration
├── pyproject.toml                  project metadata, dependencies, scripts
├── setup.sh                        preflight check + uv sync
└── .env.example                    template for .env
```

---

## Setting up the development environment

```bash
git clone https://github.com/wildintelproject/wildintel-trapverify.git
cd wildintel-trapverify/backend

# Install all dependencies (including dev group) and register the CLI
uv sync

# Optional: copy the example env file
cp .env.example .env
```

After `uv sync`, the `cli` script is available via `uv run cli`.

---

## Running the server

```bash
# Hot-reload, DEBUG log level
uv run cli serve

# Attach a debugger (VS Code / PyCharm) on port 5678
uv run cli serve debug
```

The API is at **`http://localhost:8765`** and the Swagger UI at **`http://localhost:8765/docs`**.

### VS Code — attach to debugpy

Add this configuration to `.vscode/launch.json`:

```json
{
  "type": "debugpy",
  "request": "attach",
  "name": "Attach to CamTrap Verify",
  "connect": { "host": "localhost", "port": 5678 }
}
```

Start the server with `uv run cli serve debug`, then press **F5** in VS Code.

---

## Running tests

```bash
uv run pytest                       # all tests
uv run pytest tests/unit/           # unit tests only  (~2 s)
uv run pytest tests/integration/    # integration tests (real server)
uv run pytest -v                    # verbose output
uv run pytest -k "test_species"     # filter by name
```

### Test layout

| Suite | Location | What it tests |
|-------|----------|---------------|
| Unit — workflow | `tests/unit/test_workflow.py` | `camtrap_workflow.py` functions with in-memory DataFrames |
| Unit — API | `tests/unit/test_api.py` | All endpoints via FastAPI `TestClient` (no network) |
| Integration | `tests/integration/test_integration.py` | Full HTTP cycle against a real uvicorn server on port 18765 |

### Key fixtures (`tests/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `reset_state` | `function` (autouse) | Clears `_state` between API tests |
| `sample_dir` | `function` | Creates a minimal CamtrapDP directory in `tmp_path` |
| `full_session` | `function` | Calls `/api/setup` and returns the session config |
| `live_server` | `module` | Starts a real uvicorn server thread; shuts down after the module |

---

## Architecture

### Request lifecycle

```
Browser / httpx
      │
      ▼
  FastAPI router (src/main.py)
      │  reads / writes _state (in-memory dict)
      │  persists to SESSION_FILE on disk
      ▼
  camtrap_workflow.py
      │  pure functions operating on pandas DataFrames
      │  no global state
      ▼
  File system output
  (camtrap_dp_verified/ + occupancy_inputs/)
```

### State management

- `_state` is a module-level dict in `main.py` that holds the active session config and the loaded DataFrames.
- It is persisted as `~/.config/camtrap_verify/last_session.json` on every mutating request.
- On startup, if `last_session.json` exists and points to a valid session directory, `_state` is restored automatically.

### Settings

`src/settings.py` uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) to load configuration from `.env` files and environment variables. The `Settings` singleton is instantiated at import time; `cli.py` reads from it to determine ports and log levels.

---

## Adding a new endpoint

1. Define the route in `src/main.py`.
2. Write a unit test in `tests/unit/test_api.py` using `TestClient`.
3. Optionally add an integration test in `tests/integration/test_integration.py`.

---

## CLI reference

```bash
uv run cli --help
uv run cli serve --help
uv run cli docs --help
uv run cli package --help
```

| Command | Description |
|---------|-------------|
| `cli serve [dev\|prod\|debug] [--port N]` | Start the FastAPI server |
| `cli docs serve [--port N]` | Serve MkDocs documentation locally |
| `cli docs build` | Build static documentation to `backend/site/` |
| `cli package build [--format deb\|rpm\|windows\|all] [--version X]` | Build distributable packages |

---

## Building packages

Packages are built inside Docker and require no local system tools beyond Docker itself.

```bash
# Linux packages (.deb + .rpm + .exe)
uv run cli package build

# Individual formats
uv run cli package build --format deb
uv run cli package build --format rpm
uv run cli package build --format windows   # Docker + Wine on Linux; native PyInstaller on Windows

# Pin a version
uv run cli package build --version 1.2.0
```

Output goes to `dist/` at the repository root.

### How the Linux build works

`Dockerfile.build`:

1. Installs Ruby, `fpm`, and `uv` on Ubuntu 22.04.
2. Runs `uv sync --frozen` to install Python dependencies.
3. Runs PyInstaller on `src/app_entry.py` → `dist/camtrap-verify-backend/` (onedir).
4. Packages the directory into `.deb` and/or `.rpm` using `fpm`.

### How the Windows build works

`Dockerfile.build.windows`:

1. Installs Wine on Ubuntu 22.04.
2. Installs Python for Windows via Wine.
3. Installs pip, PyInstaller, and the app dependencies under Wine.
4. Runs PyInstaller for Windows inside Wine → `dist/camtrap-verify-backend.exe`.

On Windows the build runs natively (no Docker or Wine needed).

---

## Documentation

```bash
# Serve docs with live reload
uv run cli docs serve

# Build static site → backend/site/
uv run cli docs build
```

Source files are in `backend/docs/`. The MkDocs configuration is `backend/mkdocs.yml`.

---

## Contributing

1. Fork the repository and create a feature branch.
2. Make your changes — follow the existing code style (no type-annotation-less functions, no global mutable state outside `_state`).
3. Add or update tests. All tests must pass: `uv run pytest`.
4. Open a pull request with a clear description of what changes and why.

### Code style

- Python 3.13, type-annotated throughout.
- `uv run ruff check src/ tests/` for linting (ruff is included in dev deps if configured).
- No comments that describe *what* the code does — only *why* when the reason is non-obvious.

### Reporting issues

Open a [GitHub Issue](https://github.com/wildintelproject/wildintel-trapverify/issues) with:

- CamTrap Verify version (`uv run cli --version` once implemented)
- OS and Python version
- Steps to reproduce
- Expected vs. actual behaviour
