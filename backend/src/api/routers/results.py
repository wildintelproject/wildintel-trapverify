import logging
import subprocess

from fastapi import APIRouter

from services import results_service, session_service

router = APIRouter(prefix="/api", tags=["results"])
logger = logging.getLogger(__name__)


@router.get("/results")
def get_results() -> dict:
    """Aggregate verification results for the active session."""
    return results_service.compute_results()


@router.post("/open-folder")
def open_folder() -> dict:
    """Open the session directory in the OS file manager."""
    folder = str(session_service.session_dir())
    logger.info("Opening session folder: %s", folder)
    for cmd in (["xdg-open"], ["open"], ["explorer"]):
        try:
            subprocess.Popen(cmd + [folder])
            break
        except FileNotFoundError:
            continue
    return {"ok": True, "path": folder}
