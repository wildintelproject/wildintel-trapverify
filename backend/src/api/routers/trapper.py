"""FastAPI router — Trapper integration."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from schemas.requests import TrapperGenerateRequest, TrapperLoginRequest
from services import trapper_service
from services.session_service import DEFAULT_OUTPUT_DIR

router = APIRouter(prefix="/api/trapper", tags=["trapper"])
logger = logging.getLogger(__name__)


def _http_exc(exc: Exception) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        return HTTPException(exc.response.status_code, str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(401, str(exc))
    return HTTPException(400, str(exc))


@router.post("/login")
async def login(req: TrapperLoginRequest) -> dict:
    """Verify credentials against a Trapper instance and open a session."""
    logger.info("Trapper login attempt: url=%s user=%s", req.url, req.username)
    try:
        return await trapper_service.login(req.url, req.username, req.password)
    except ValueError as exc:
        logger.warning("Trapper login failed: %s", exc)
        raise HTTPException(401, str(exc)) from exc
    except Exception as exc:
        logger.error("Trapper login error: %s", exc)
        raise _http_exc(exc) from exc


@router.get("/research-projects")
async def research_projects() -> dict:
    """List research projects accessible to the logged-in user."""
    try:
        results = await trapper_service.get_research_projects()
        return {"results": results}
    except Exception as exc:
        raise _http_exc(exc) from exc


@router.get("/classification-projects/{research_project_pk}")
async def classification_projects(research_project_pk: int) -> dict:
    """List classification projects for a given research project."""
    try:
        results = await trapper_service.get_classification_projects(research_project_pk)
        return {"results": results}
    except Exception as exc:
        raise _http_exc(exc) from exc


@router.post("/generate")
async def generate(req: TrapperGenerateRequest) -> dict:
    """
    Start asynchronous CamtrapDP package generation.
    Returns a task_id; poll GET /api/trapper/generate/{task_id} for status.
    """
    logger.info(
        "Generate requested: project_pk=%d clear_cache=%s", req.classification_project_pk, req.clear_cache
    )
    try:
        output_dir = (
            Path(req.output_dir) if req.output_dir
            else DEFAULT_OUTPUT_DIR / "trapper_imports"
        )
        task_id = await trapper_service.start_generation_task(
            req.classification_project_pk,
            output_dir,
            clear_cache=req.clear_cache,
        )
        logger.info("Generation task started: task_id=%s", task_id)
        return {"task_id": task_id}
    except Exception as exc:
        logger.error("Failed to start generation task: %s", exc)
        raise _http_exc(exc) from exc


@router.get("/generate/{task_id}")
async def generation_status(task_id: str) -> dict:
    """Poll the status of a CamtrapDP generation task."""
    status = trapper_service.get_task_status(task_id)
    if status is None:
        raise HTTPException(404, f"Tarea {task_id!r} no encontrada")
    return status
