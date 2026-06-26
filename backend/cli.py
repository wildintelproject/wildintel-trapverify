"""
CamTrap Verify — CLI de gestión del backend.

Uso:
    uv run python cli.py serve [dev|prod|debug] [--port 8765]
    uv run python cli.py docs serve
    uv run python cli.py docs build
    uv run python cli.py package build [--format deb|rpm|all] [--version 0.1.0]
"""
import subprocess
import sys
import threading
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).parent / "src"))
from settings import settings  # noqa: E402

# ── Constantes ────────────────────────────────────────────────────────────────

ROOT_DIR      = Path(__file__).parent.parent   # raíz del repositorio
BACKEND_DIR   = Path(__file__).parent
SRC_DIR       = BACKEND_DIR / "src"
MKDOCS_CFG    = BACKEND_DIR / "mkdocs.yml"
DIST_DIR      = ROOT_DIR / "dist"
FRONTEND_DIR  = ROOT_DIR / "frontend"
FRONTEND_MKDOCS = FRONTEND_DIR / "mkdocs.yml"

console = Console()
app     = typer.Typer(help="CamTrap Verify — herramienta de gestión del backend.")


# ── Enums ─────────────────────────────────────────────────────────────────────

class ServeMode(str, Enum):
    dev   = "dev"
    prod  = "prod"
    debug = "debug"

class PackageFormat(str, Enum):
    deb     = "deb"
    rpm     = "rpm"
    windows = "windows"
    all     = "all"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(*args: str, cwd: Path | None = None) -> None:
    result = subprocess.run(list(args), cwd=cwd)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def _require(tool: str, hint: str) -> None:
    if subprocess.run(["which", tool], capture_output=True).returncode != 0:
        console.print(f"[red]✘  '{tool}' no encontrado.[/red]  {hint}")
        raise typer.Exit(1)


# ── serve ─────────────────────────────────────────────────────────────────────

@app.command()
def serve(
    mode: ServeMode = typer.Argument(ServeMode.dev, help="Modo de ejecución."),
    port: int       = typer.Option(None, "--port", "-p", help="Puerto de escucha (por defecto: CAMTRAP_PORT o 8765)."),
) -> None:
    """Arranca el servidor FastAPI en el modo indicado."""
    effective_port = port or settings.port
    console.print(Panel(
        f"[bold]Modo:[/bold] {mode.value}   [bold]Puerto:[/bold] {effective_port}",
        title="CamTrap Verify — backend",
    ))

    if mode == ServeMode.dev:
        console.print(f"  API:     http://localhost:{effective_port}")
        console.print(f"  Swagger: http://localhost:{effective_port}/docs\n")
        _run("uvicorn", "main:app", "--reload", "--port", str(effective_port),
             "--log-level", settings.log_level.lower(), "--app-dir", "src",
             cwd=BACKEND_DIR)

    elif mode == ServeMode.prod:
        console.print(f"  API:     http://localhost:{effective_port}\n")
        _run("uvicorn", "main:app", "--port", str(effective_port),
             "--log-level", "warning", "--workers", "2", "--app-dir", "src",
             cwd=BACKEND_DIR)

    elif mode == ServeMode.debug:
        _require("debugpy", "Instala con: uv sync --group dev")
        console.print(f"  API:      http://localhost:{effective_port}")
        console.print(f"  Swagger:  http://localhost:{effective_port}/docs")
        console.print("  Debugger: localhost:5678\n")
        _run(
            sys.executable, "-m", "debugpy", "--listen", "5678",
            "-m", "uvicorn", "main:app", "--port", str(effective_port),
            "--log-level", "debug", "--app-dir", "src",
            cwd=BACKEND_DIR,
        )


# ── dev (backend + frontend juntos) ──────────────────────────────────────────

@app.command()
def dev(
    backend_port:  int = typer.Option(None,  "--backend-port",  "-b", help="Puerto del backend (por defecto: CAMTRAP_PORT o 8765)."),
    frontend_port: int = typer.Option(5173,  "--frontend-port", "-f", help="Puerto del frontend Vite."),
) -> None:
    """Arranca backend y frontend simultáneamente en modo desarrollo."""
    _require("npm", "Instala Node.js desde https://nodejs.org/ (v18+)")
    effective_port = backend_port or settings.port

    console.print(Panel(
        f"  [bold]Backend:[/bold]  http://localhost:{effective_port}\n"
        f"  [bold]Frontend:[/bold] http://localhost:{frontend_port}\n"
        f"  [bold]API docs:[/bold] http://localhost:{effective_port}/docs\n\n"
        f"  Ctrl+C para detener ambos procesos.",
        title="CamTrap Verify — dev",
    ))

    backend_proc = subprocess.Popen(
        ["uvicorn", "main:app", "--reload", "--port", str(effective_port),
         "--log-level", settings.log_level.lower(), "--app-dir", "src"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    frontend_proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(frontend_port)],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    def _stream(proc: subprocess.Popen, label: str, color: str) -> None:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode(errors="replace").rstrip()
            if line:
                console.print(f"[{color}][{label}][/{color}] {line}")

    threads = [
        threading.Thread(target=_stream, args=(backend_proc,  "backend",  "cyan"),  daemon=True),
        threading.Thread(target=_stream, args=(frontend_proc, "frontend", "green"), daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        backend_proc.wait()
        frontend_proc.wait()
    except KeyboardInterrupt:
        console.print("\n[yellow]Deteniendo...[/yellow]")
        for proc in (backend_proc, frontend_proc):
            proc.terminate()
        for proc in (backend_proc, frontend_proc):
            proc.wait()
        console.print("[yellow]✔  Parado.[/yellow]")


# ── test ──────────────────────────────────────────────────────────────────────

class TestSuite(str, Enum):
    unit        = "unit"
    integration = "integration"
    all         = "all"

@app.command()
def test(
    suite:   TestSuite = typer.Argument(TestSuite.all, help="Suite a ejecutar."),
    verbose: bool      = typer.Option(False, "--verbose", "-v", help="Salida detallada (-v de pytest)."),
    keyword: str | None = typer.Option(None, "--keyword", "-k", help="Filtro de tests por nombre (-k de pytest)."),
) -> None:
    """Ejecuta los tests unitarios y/o de integración con pytest."""
    paths = {
        TestSuite.unit:        ["tests/unit/"],
        TestSuite.integration: ["tests/integration/"],
        TestSuite.all:         ["tests/unit/", "tests/integration/"],
    }[suite]

    console.print(Panel(
        f"[bold]Suite:[/bold] {suite.value}   [bold]Paths:[/bold] {', '.join(paths)}",
        title="CamTrap Verify — tests",
    ))

    cmd = [sys.executable, "-m", "pytest", *paths]
    if verbose:
        cmd.append("-v")
    if keyword:
        cmd.extend(["-k", keyword])

    _run(*cmd, cwd=BACKEND_DIR)


# ── docs ──────────────────────────────────────────────────────────────────────

docs_app = typer.Typer(help="Genera o sirve la documentación con MkDocs.")
app.add_typer(docs_app, name="docs")


@docs_app.command("serve")
def docs_serve(
    port: int = typer.Option(8000, "--port", "-p", help="Puerto del servidor de documentación."),
) -> None:
    """Sirve la documentación en local con recarga automática."""
    console.print(f"[green]Documentación en http://127.0.0.1:{port}[/green]\n")
    _run("mkdocs", "serve", "--config-file", str(MKDOCS_CFG), "--dev-addr", f"127.0.0.1:{port}",
         cwd=BACKEND_DIR)


@docs_app.command("build")
def docs_build() -> None:
    """Genera el sitio estático en backend/site/."""
    console.print("[green]Generando documentación...[/green]")
    _run("mkdocs", "build", "--config-file", str(MKDOCS_CFG), cwd=BACKEND_DIR)
    console.print(f"[green]✔  Sitio generado en {BACKEND_DIR / 'site'}[/green]")


# ── package ───────────────────────────────────────────────────────────────────

package_app = typer.Typer(help="Construye paquetes de distribución (.deb / .rpm).")
app.add_typer(package_app, name="package")


def _get_version(version: str | None) -> str:
    if version:
        return version
    result = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        capture_output=True, text=True, cwd=ROOT_DIR,
    )
    if result.returncode == 0:
        return result.stdout.strip().lstrip("v")
    return "0.0.0~dev"


def _build_linux_package(fmt: str, version: str) -> None:
    _require("docker", "Instala Docker desde https://docs.docker.com/get-docker/")
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]Construyendo paquete [bold]{fmt}[/bold] v{version}...[/green]")
    _run(
        "docker", "build",
        "--build-arg", f"APP_VERSION={version}",
        "--build-arg", f"PKG_FORMAT={fmt}",
        "-f", str(BACKEND_DIR / "Dockerfile.build"),
        "--output", f"type=local,dest={DIST_DIR}",
        str(BACKEND_DIR),
    )
    pkgs = list(DIST_DIR.glob(f"*.{fmt}"))
    if not pkgs:
        console.print(f"[red]✘  No se encontró ningún paquete .{fmt} en {DIST_DIR}[/red]")
        raise typer.Exit(1)
    for pkg in pkgs:
        size = pkg.stat().st_size // 1024
        console.print(f"[green]✔  {pkg}  ({size} KB)[/green]")
    install_cmd = "sudo dnf localinstall" if fmt == "rpm" else "sudo apt install"
    console.print(f"\nPara instalar:  {install_cmd} {pkgs[0]}")


def _build_windows_package(version: str) -> None:
    if sys.platform == "win32":
        _build_windows_native(version)
    else:
        _build_windows_docker(version)


def _build_windows_native(version: str) -> None:
    """Genera el .exe directamente en Windows con PyInstaller."""
    console.print("[green]Construyendo .exe nativo para Windows...[/green]")
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    _run(
        sys.executable, "-m", "PyInstaller", "src/app_entry.py",
        "--onefile",
        "--name", "camtrap-verify-backend",
        "--add-data", "src/camtrap_workflow.py;.",
        "--add-data", "src/settings.py;.",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "anyio._backends._asyncio",
        "--hidden-import", "pandas",
        "--hidden-import", "pydantic_settings",
        "--collect-submodules", "fastapi",
        "--collect-submodules", "starlette",
        cwd=BACKEND_DIR,
    )
    src_exe = BACKEND_DIR / "dist" / "camtrap-verify-backend.exe"
    dst = DIST_DIR / f"camtrap-verify-backend-{version}-windows-x64.exe"
    dst.write_bytes(src_exe.read_bytes())
    size = dst.stat().st_size // (1024 * 1024)
    console.print(f"[green]✔  {dst}  ({size} MB)[/green]")


def _build_windows_docker(version: str) -> None:
    """Cross-compila el .exe desde Linux/macOS usando Docker + Wine."""
    _require("docker", "Instala Docker desde https://docs.docker.com/get-docker/")
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    console.print("[green]Construyendo .exe para Windows vía Docker + Wine...[/green]")
    console.print("[yellow]  (primera vez puede tardar varios minutos descargando Wine)[/yellow]")
    _run(
        "docker", "build",
        "--build-arg", f"APP_VERSION={version}",
        "-f", str(BACKEND_DIR / "Dockerfile.build.windows"),
        "--output", f"type=local,dest={DIST_DIR}",
        str(BACKEND_DIR),
    )
    exes = list(DIST_DIR.glob("*.exe"))
    if not exes:
        console.print(f"[red]✘  No se encontró ningún .exe en {DIST_DIR}[/red]")
        raise typer.Exit(1)
    for exe in exes:
        size = exe.stat().st_size // (1024 * 1024)
        console.print(f"[green]✔  {exe}  ({size} MB)[/green]")


@package_app.command("build")
def package_build(
    fmt: PackageFormat = typer.Option(PackageFormat.all, "--format", "-f",
                                       help="Formato: deb, rpm, windows, all."),
    version: str | None = typer.Option(None, "--version", "-v",
                                        help="Versión (por defecto: git tag o 0.0.0~dev)."),
) -> None:
    """Construye paquetes de distribución usando Docker."""
    v = _get_version(version)
    console.print(Panel(f"[bold]Versión:[/bold] {v}   [bold]Formato:[/bold] {fmt.value}",
                        title="CamTrap Verify — package"))
    if fmt == PackageFormat.windows:
        _build_windows_package(v)
    elif fmt == PackageFormat.all:
        for f in ["deb", "rpm"]:
            _build_linux_package(f, v)
        _build_windows_package(v)
    else:
        _build_linux_package(fmt.value, v)


# ── frontend ──────────────────────────────────────────────────────────────────

frontend_app = typer.Typer(help="Gestiona el frontend React (npm).")
app.add_typer(frontend_app, name="frontend")

frontend_docs_app = typer.Typer(help="Genera o sirve la documentación del frontend.")
frontend_app.add_typer(frontend_docs_app, name="docs")


def _npm(*args: str) -> None:
    _require("npm", "Instala Node.js desde https://nodejs.org/ (v18+)")
    _run("npm", *args, cwd=FRONTEND_DIR)


@frontend_app.command("dev")
def frontend_dev(
    port: int = typer.Option(5173, "--port", "-p", help="Puerto del servidor de desarrollo."),
) -> None:
    """Arranca el servidor de desarrollo Vite (hot-reload)."""
    console.print(Panel(
        f"[bold]Frontend:[/bold] http://localhost:{port}",
        title="CamTrap Verify — frontend dev",
    ))
    _npm("run", "dev", "--", "--port", str(port))


@frontend_app.command("build")
def frontend_build() -> None:
    """Compila el frontend para producción → frontend/dist/."""
    console.print("[green]Compilando frontend...[/green]")
    _npm("run", "build")
    console.print(f"[green]✔  Build en {FRONTEND_DIR / 'dist'}[/green]")


@frontend_app.command("preview")
def frontend_preview(
    port: int = typer.Option(4173, "--port", "-p", help="Puerto del servidor de preview."),
) -> None:
    """Sirve el build de producción localmente."""
    console.print(Panel(
        f"[bold]Preview:[/bold] http://localhost:{port}",
        title="CamTrap Verify — frontend preview",
    ))
    _npm("run", "preview", "--", "--port", str(port))


@frontend_app.command("lint")
def frontend_lint() -> None:
    """Ejecuta oxlint sobre el código fuente."""
    console.print("[green]Linting...[/green]")
    _npm("run", "lint")


@frontend_docs_app.command("serve")
def frontend_docs_serve(
    port: int = typer.Option(8100, "--port", "-p", help="Puerto del servidor de documentación."),
) -> None:
    """Sirve la documentación del frontend con recarga automática."""
    console.print(f"[green]Documentación frontend en http://127.0.0.1:{port}[/green]\n")
    _run("mkdocs", "serve", "--config-file", str(FRONTEND_MKDOCS),
         "--dev-addr", f"127.0.0.1:{port}", cwd=FRONTEND_DIR)


@frontend_docs_app.command("build")
def frontend_docs_build() -> None:
    """Genera el sitio estático en frontend/site/."""
    console.print("[green]Generando documentación del frontend...[/green]")
    _run("mkdocs", "build", "--config-file", str(FRONTEND_MKDOCS), cwd=FRONTEND_DIR)
    console.print(f"[green]✔  Sitio generado en {FRONTEND_DIR / 'site'}[/green]")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
