"""Trapper integration — thin async wrapper around wildintel-trapper-sdk.

wildintel-trapper-sdk's TrapperClient is synchronous (a plain httpx.Client
under the hood); every call into it here runs inside asyncio.to_thread() so
it never blocks this backend's event loop.

Connection lifecycle
--------------------
call login()  →  stores a TrapperClient (module-level, one active connection)
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

from trapper_client import TrapperClient, err

logger = logging.getLogger(__name__)

# ── Module-level state (one active connection at a time) ──────────────────

_client: TrapperClient | None = None
_base_url: str | None = None

# Simple in-memory task store  {task_id: {status, path, error}}
_tasks: dict[str, dict[str, Any]] = {}


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_client() -> TrapperClient:
    if _client is None:
        raise RuntimeError("No hay conexión activa. Llama a login() primero.")
    return _client


# ── Public API ────────────────────────────────────────────────────────────

async def login(base_url: str, username: str, password: str) -> dict[str, Any]:
    """
    Verify credentials and store the connection.
    Uses HTTP Basic Auth (via TrapperClient's user_name/user_password) so no
    session/CSRF management is needed.
    """
    global _client, _base_url

    logger.info("Logging in to Trapper at %s as %s", base_url, username)

    _base_url = base_url.rstrip("/")
    candidate = TrapperClient(base_url=_base_url, user_name=username, user_password=password)

    try:
        result = await asyncio.to_thread(candidate.research_projects.get, page=1, page_size=1)
    except err.UnauthorizedError as exc:
        logger.warning("Login failed for user %s at %s (401 Unauthorized)", username, base_url)
        raise ValueError("Credenciales incorrectas o acceso denegado") from exc

    _client = candidate
    count = result.pagination.count
    logger.info("Login successful: %d research projects available", count)
    return {
        "ok": True,
        "base_url": _base_url,
        "research_projects_count": count,
    }


def _fetch_research_projects(client: TrapperClient) -> list[dict[str, Any]]:
    return [
        {"pk": p.pk, "name": p.name, "acronym": p.acronym}
        for p in client.research_projects.where(page_size=500)
    ]


async def get_research_projects() -> list[dict[str, Any]]:
    """Return all research projects accessible to the current user."""
    client = _require_client()
    return await asyncio.to_thread(_fetch_research_projects, client)


def _fetch_classification_projects(
    client: TrapperClient, research_project_pk: int
) -> list[dict[str, Any]]:
    # Resolve the research project name (classification list uses it as a field)
    rp = client.research_projects.find(pk=research_project_pk)
    rp_name = rp.name or ""

    # search is fuzzy — narrow to exact match
    return [
        {"pk": p.pk, "name": p.name, "is_active": p.is_active}
        for p in client.classification_projects.where(search=rp_name, page_size=500)
        if p.research_project == rp_name
    ]


async def get_classification_projects(research_project_pk: int) -> list[dict[str, Any]]:
    """Return classification projects linked to *research_project_pk*."""
    client = _require_client()
    return await asyncio.to_thread(_fetch_classification_projects, client, research_project_pk)


def _generate_and_download(
    client: TrapperClient,
    classification_project_pk: int,
    output_dir: Path,
    clear_cache: bool,
) -> Path:
    logger.info(
        "Requesting CamtrapDP package for classification project %d (clear_cache=%s)",
        classification_project_pk, clear_cache,
    )
    response = client.classification_package.get_project_package(
        project_pk=classification_project_pk,
        export_format="camtrapdp",
        export_filetype="csv.gz",
        clear_cache="true" if clear_cache else "false",
    )
    data = response.data
    download_url = data.package if data else None

    if not download_url:
        msg = data.message if data else ""
        errors = data.errors if data else ""
        logger.error(
            "Trapper did not return a download URL. Message: %r  Errors: %r", msg, errors
        )
        raise RuntimeError(
            f"Trapper no devolvió URL de descarga. "
            f"Mensaje: {msg!r}  Errores: {errors!r}"
        )

    logger.info("Downloading package from %s", download_url)
    dl_resp = client.make_request(endpoint=download_url, method="GET")

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
    until generation finishes — this runs in a worker thread (via
    asyncio.to_thread) so the event loop is never blocked on our side.

    Returns the path to the extracted directory.
    """
    client = _require_client()
    return await asyncio.to_thread(
        _generate_and_download, client, classification_project_pk, output_dir, clear_cache
    )


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
