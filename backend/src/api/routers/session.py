import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from schemas.requests import LoadSessionRequest, SetupRequest
from services import session_service, workflow_service

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
    }


@router.post("/session/load")
def load_session(req: LoadSessionRequest) -> dict:
    """Load an existing session directory into memory."""
    logger.info("Loading session from %s", req.session_dir)
    sd = Path(req.session_dir)
    if not sd.is_dir():
        logger.warning("Session directory not found: %s", sd)
        raise HTTPException(400, f"Directorio no encontrado: {sd}")
    session_service.load_from_dir(sd)
    return {
        "ok": True,
        "session_dir": str(sd),
        "config": session_service.get_config(),
    }


@router.post("/setup")
def setup(req: SetupRequest) -> dict:
    """Create a new verification session."""
    logger.info("Setup requested: camtrap_dir=%s", req.camtrap_dir)
    camtrap_dir = Path(req.camtrap_dir)
    if not camtrap_dir.exists():
        logger.warning("camtrap_dir not found: %s", camtrap_dir)
        raise HTTPException(400, f"camtrap_dir no encontrado: {camtrap_dir}")
    return workflow_service.run_setup(req)
