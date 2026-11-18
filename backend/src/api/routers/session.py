import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from camtrap_workflow import dataset_fingerprint
from schemas.requests import (
    ClassifiedByRequest, ImportSessionRequest, LoadSessionRequest, RelinkRequest,
    RenameSessionRequest, SetupRequest,
)
from services import session_service, session_transfer, workflow_service

router = APIRouter(prefix="/api", tags=["session"])
logger = logging.getLogger(__name__)


@router.get("/state")
def get_state() -> dict:
    """Return the current session state."""
    config = session_service.get_config()
    if config is None:
        return {
            "ready": False,
            "default_output_dir": str(session_service.DEFAULT_OUTPUT_DIR),
        }
    return {
        "ready": True,
        "config": config,
        "default_output_dir": str(session_service.DEFAULT_OUTPUT_DIR),
        "session_dir": str(session_service.session_dir()),
        "relink": session_service.relink_status(),
    }


@router.put("/session/name")
def rename_session(req: RenameSessionRequest) -> dict:
    """Name (or rename) a session; an empty name clears it."""
    return session_service.rename_session(req.session_dir, req.name)


@router.put("/session/classified-by")
def set_classified_by(req: ClassifiedByRequest) -> dict:
    """Change the classifiedBy value of the active session; the verified CamtrapDP is rebuilt."""
    value = session_service.set_classified_by(req.classified_by)
    workflow_service.mark_outputs_stale()       # classifiedBy is written into camtrap_dp_verified/
    return {"classified_by": value}


@router.get("/session/recent")
def recent_sessions() -> list[dict]:
    """List recently opened sessions still present on disk, most recent first."""
    return session_service.list_recent_sessions()


@router.post("/session/load")
def load_session(req: LoadSessionRequest) -> dict:
    """Load an existing session directory into memory."""
    logger.info("Loading session from %s", req.session_dir)
    sd = Path(req.session_dir)
    if not sd.is_dir():
        logger.warning("Session directory not found: %s", sd)
        raise HTTPException(400, f"Directorio no encontrado: {sd}")
    session_service.load_from_dir(sd)
    relink = session_service.auto_relink()
    return {
        "ok": True,
        "session_dir": str(sd),
        "config": session_service.get_config(),
        "relink": relink,
    }


@router.get("/session/export")
def export_session() -> Response:
    """Download the active session as a ZIP (review state only, no photos)."""
    sd = session_service.session_dir()
    if sd is None:
        raise HTTPException(400, "No hay sesión activa.")
    name = session_service.clean_session_name((session_service.get_config() or {}).get("session_name")) or sd.name
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name) or "session"
    return Response(
        session_transfer.export_zip(sd),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
    )


@router.post("/session/import")
def import_session(req: ImportSessionRequest) -> dict:
    """Import a session ZIP exported on another computer and open it."""
    dest = session_transfer.import_zip(req.zip_path)
    try:
        session_service.load_from_dir(dest)
    except HTTPException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except Exception:
        # a manifest the app cannot read (columns missing, wrong format): refuse it cleanly and leave no half-imported folder
        logger.exception("Imported session could not be loaded: %s", dest)
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(400, "El ZIP contiene una sesión que no se puede abrir (el candidate_manifest.csv no es válido).")
    relink = session_service.auto_relink()
    workflow_service.mark_outputs_stale()       # an imported session brings decisions, not the outputs derived from them
    return {"ok": True, "session_dir": str(dest), "config": session_service.get_config(), "relink": relink}


@router.post("/session/relink")
def relink_session(req: RelinkRequest) -> dict:
    """Point the active session at its data/image folders on this computer."""
    config = session_service.get_config()
    if config is None:
        raise HTTPException(400, "No hay sesión activa.")
    camtrap_dir = Path(req.camtrap_dir)
    if not camtrap_dir.is_dir():
        raise HTTPException(400, f"Directorio no encontrado: {camtrap_dir}")
    if req.image_base_dir and not Path(req.image_base_dir).is_dir():
        raise HTTPException(400, f"Directorio de imágenes no encontrado: {req.image_base_dir}")
    expected = config.get("dataset_fingerprint")
    actual = dataset_fingerprint(camtrap_dir)
    if actual is None:
        raise HTTPException(400, "La carpeta no contiene un CamtrapDP válido (falta deployments).")
    if expected and actual != expected:
        raise HTTPException(400, "Esa carpeta contiene un dataset distinto al de la sesión (las deployments no coinciden).")
    session_service.update_paths(str(camtrap_dir), req.image_base_dir, req.flat_search)
    workflow_service.mark_outputs_stale()       # the histories and reports are rebuilt when Results is opened
    return {"ok": True, "relink": session_service.relink_status()}


@router.post("/setup")
def setup(req: SetupRequest) -> dict:
    """Create a new verification session."""
    logger.info("Setup requested: camtrap_dir=%s", req.camtrap_dir)
    camtrap_dir = Path(req.camtrap_dir)
    if not camtrap_dir.exists():
        logger.warning("camtrap_dir not found: %s", camtrap_dir)
        raise HTTPException(400, f"camtrap_dir no encontrado: {camtrap_dir}")
    return workflow_service.run_setup(req)
