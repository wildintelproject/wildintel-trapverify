"""HTTP client for the Trapper wildlife monitoring platform.

Connection lifecycle
--------------------
call login()  →  stores an httpx.AsyncClient with BasicAuth
call get_research_projects() / get_classification_projects()
call start_generation_task()  →  returns task_id
poll get_task_status(task_id)  →  {status, path, error}
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Module-level state (one active connection at a time) ──────────────────

_client: httpx.AsyncClient | None = None
_base_url: str | None = None

# Simple in-memory task store  {task_id: {status, path, error}}
_tasks: dict[str, dict[str, Any]] = {}


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("No hay conexión activa. Llama a login() primero.")
    return _client


# ── Public API ────────────────────────────────────────────────────────────

async def login(base_url: str, username: str, password: str) -> dict[str, Any]:
    """
    Verify credentials and store the connection.
    Uses HTTP Basic Auth so no session/CSRF management is needed.
    """
    global _client, _base_url

    logger.info("Logging in to Trapper at %s as %s", base_url, username)
    if _client is not None:
        await _client.aclose()
        _client = None

    _base_url = base_url.rstrip("/")
    candidate = httpx.AsyncClient(
        base_url=_base_url,
        auth=httpx.BasicAuth(username, password),
        follow_redirects=True,
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=5.0),
    )

    resp = await candidate.get("/research/api/projects", params={"page_size": 1})
    if resp.status_code == 401:
        await candidate.aclose()
        logger.warning("Login failed for user %s at %s (401 Unauthorized)", username, base_url)
        raise ValueError("Credenciales incorrectas o acceso denegado")
    resp.raise_for_status()

    _client = candidate
    pagination = resp.json().get("pagination", {})
    logger.info("Login successful: %d research projects available", pagination.get("count", 0))
    return {
        "ok": True,
        "base_url": _base_url,
        "research_projects_count": pagination.get("count", 0),
    }


async def get_research_projects() -> list[dict[str, Any]]:
    """Return all research projects accessible to the current user."""
    client = _require_client()
    resp = await client.get("/research/api/projects", params={"page_size": 500})
    resp.raise_for_status()
    return resp.json().get("results", [])


async def get_classification_projects(research_project_pk: int) -> list[dict[str, Any]]:
    """Return classification projects linked to *research_project_pk*."""
    client = _require_client()

    # Resolve the research project name (classification list uses it as a field)
    rp_resp = await client.get(f"/research/api/projects/{research_project_pk}")
    rp_resp.raise_for_status()
    rp_name: str = rp_resp.json().get("name", "")

    cp_resp = await client.get(
        "/media_classification/api/projects",
        params={"page_size": 500, "search": rp_name},
    )
    cp_resp.raise_for_status()
    results: list[dict[str, Any]] = cp_resp.json().get("results", [])

    # search is fuzzy — narrow to exact match
    return [r for r in results if r.get("research_project") == rp_name]


async def generate_and_download(
    classification_project_pk: int,
    output_dir: Path,
    *,
    clear_cache: bool = False,
) -> Path:
    """
    Request a CamtrapDP package from Trapper, download the ZIP, and extract it.

    Trapper generates the package synchronously on the server side; if the
    package is already cached the response is immediate, otherwise it blocks
    until generation finishes.  Either way we await the HTTP call with a long
    read timeout (300 s) so the event loop is never blocked on our side.

    Returns the path to the extracted directory.
    """
    client = _require_client()

    logger.info(
        "Requesting CamtrapDP package for classification project %d (clear_cache=%s)",
        classification_project_pk, clear_cache,
    )
    gen_resp = await client.get(
        f"/media_classification/api/package/{classification_project_pk}/",
        params={
            "export_format": "camtrapdp",
            "export_filetype": "csv.gz",
            "clear_cache": "true" if clear_cache else "false",
        },
    )
    gen_resp.raise_for_status()
    data: dict[str, Any] = gen_resp.json().get("data", {})
    download_url: str | None = data.get("package")

    if not download_url:
        msg = data.get("message", "")
        err = data.get("errors", "")
        logger.error(
            "Trapper did not return a download URL. Message: %r  Errors: %r", msg, err
        )
        raise RuntimeError(
            f"Trapper no devolvió URL de descarga. "
            f"Mensaje: {msg!r}  Errores: {err!r}"
        )

    logger.info("Downloading package from %s", download_url)
    dl_resp = await client.get(download_url)
    dl_resp.raise_for_status()

    output_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = output_dir / "camtrap_dp"
    extract_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(BytesIO(dl_resp.content)) as zf:
        zf.extractall(extract_dir)

    # Trapper exports .csv.gz files; decompress them so downstream tools
    # (inspectDir, camtrap_workflow) can read plain CSV without special handling.
    for gz_path in extract_dir.rglob("*.csv.gz"):
        csv_path = gz_path.with_suffix("")  # strips .gz → keeps .csv
        with gzip.open(gz_path, "rb") as f_in, csv_path.open("wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        gz_path.unlink()

    logger.info("Package extracted to %s", extract_dir)
    return extract_dir


# ── Background task helpers ───────────────────────────────────────────────

async def start_generation_task(
    classification_project_pk: int,
    output_dir: Path,
    *,
    clear_cache: bool = False,
) -> str:
    """
    Launch CamtrapDP generation as a background asyncio task.
    Returns a task_id; poll get_task_status() to check progress.
    """
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {"status": "running", "path": None, "error": None}
    logger.info("Started generation task %s for project %d", task_id, classification_project_pk)

    async def _run() -> None:
        try:
            path = await generate_and_download(
                classification_project_pk,
                output_dir,
                clear_cache=clear_cache,
            )
            _tasks[task_id]["status"] = "done"
            _tasks[task_id]["path"] = str(path)
            logger.info("Generation task %s completed: %s", task_id, path)
        except Exception as exc:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(exc)
            logger.error("Generation task %s failed: %s", task_id, exc)

    asyncio.create_task(_run())
    return task_id


def get_task_status(task_id: str) -> dict[str, Any] | None:
    return _tasks.get(task_id)
