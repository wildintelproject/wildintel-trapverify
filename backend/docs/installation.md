# Installation

CamTrap Verify can be installed from **pre-built binaries** (recommended for end users) or **from source** (recommended for developers and contributors).

---

## Option A — Pre-built binaries

Binary releases are available on the [GitHub Releases](https://github.com/wildintelproject/wildintel-trapverify/releases) page. No Python or Node.js installation is required.

=== "Linux (.deb — Debian / Ubuntu)"

    ```bash
    # Download the latest release
    wget https://github.com/wildintelproject/wildintel-trapverify/releases/latest/download/camtrap-verify-backend_0.1.0_amd64.deb

    # Install
    sudo apt install ./camtrap-verify-backend_0.1.0_amd64.deb

    # Run
    camtrap-verify-backend
    ```

=== "Linux (.rpm — Fedora / RHEL)"

    ```bash
    # Download the latest release
    wget https://github.com/wildintelproject/wildintel-trapverify/releases/latest/download/camtrap-verify-backend-0.1.0-1.x86_64.rpm

    # Install
    sudo dnf localinstall camtrap-verify-backend-0.1.0-1.x86_64.rpm

    # Run
    camtrap-verify-backend
    ```

=== "Windows"

    1. Download `camtrap-verify-backend-0.1.0-windows-x64.exe` from [GitHub Releases](https://github.com/wildintelproject/wildintel-trapverify/releases/latest).
    2. Double-click the `.exe`. The server starts and opens the interface in your default browser automatically.

!!! note "Firewall prompt on Windows"
    Windows may show a network access prompt the first time the binary runs. Allow access to `localhost` only.

### Optional configuration

Place a `.env` file next to the binary to customise settings:

```
CAMTRAP_PORT=8765
CAMTRAP_LOG_LEVEL=INFO
```

See [Configuration](configuration.md) for all available options.

---

## Option B — From source

### Requirements

| Tool | Minimum version | Purpose |
|------|----------------|---------|
| Python | **3.13** | Backend runtime |
| [uv](https://docs.astral.sh/uv/) | latest | Python package management |
| Docker | 24+ | Package builds only (optional) |

!!! tip "Installing uv"
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
    Or run `./setup.sh` — it will install uv automatically if missing.

### Clone and install

```bash
git clone https://github.com/wildintelproject/wildintel-trapverify.git
cd wildintel-trapverify/backend

# Install dependencies and register the CLI
uv sync
```

`uv sync` installs all Python dependencies and registers `cli` as a runnable script in the virtual environment.

### Start the server

```bash
# Development mode — hot-reload, full logging
uv run cli serve

# Production mode — 2 workers, warning-level logging
uv run cli serve prod

# Debug mode — debugpy on port 5678
uv run cli serve debug
```

The API is available at **`http://localhost:8765`**.  
The interactive Swagger UI is at **`http://localhost:8765/docs`**.

### Custom port

```bash
uv run cli serve --port 9000
# or set it persistently:
echo "CAMTRAP_PORT=9000" >> .env
```

### Setup script

`setup.sh` performs a quick preflight check and installs dependencies:

```bash
./setup.sh
```

It verifies that Docker and uv are available (installing uv if missing), then runs `uv sync`.

---

## Verifying the installation

```bash
curl http://localhost:8765/api/health
# {"status":"ok"}
```

---

## Updating

=== "Binary"

    Download and reinstall the new package from [GitHub Releases](https://github.com/wildintelproject/wildintel-trapverify/releases).

=== "From source"

    ```bash
    git pull
    uv sync
    ```
