import io
import logging
import subprocess
import zipfile

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from occupancy_model import fit_naive_vs_verified
from services import results_service, session_service

router = APIRouter(prefix="/api", tags=["results"])
logger = logging.getLogger(__name__)


@router.get("/results")
def get_results() -> dict:
    """Aggregate verification results for the active session."""
    return results_service.compute_results()


@router.get("/results/occupancy")
def get_occupancy() -> list[dict]:
    """Return psi(.)p(.) occupancy fit (naive vs verified) for the active session.

    Reads occupancy_fit.csv if it already exists; otherwise runs the fit on demand.
    """
    p = session_service.paths()
    fit_csv = p["occupancy_out"] / "occupancy_fit.csv"

    if fit_csv.exists():
        df = pd.read_csv(fit_csv)
        return df.where(pd.notna(df), None).to_dict(orient="records")

    config = session_service.get_config()
    if config is None:
        raise HTTPException(400, "No hay sesión activa.")

    results = fit_naive_vs_verified(
        p["occupancy_out"], config.get("target_species", [])
    )
    if not results:
        raise HTTPException(404, "No se encontraron historiales de detección. Ejecuta primero una sesión completa.")
    return results


@router.get("/results/download")
def download_results() -> StreamingResponse:
    """Stream the session output directory as a ZIP file."""
    sd = session_service.session_dir()
    if sd is None:
        raise HTTPException(400, "No hay sesión activa.")

    zip_name = f"wildintel-camtrap-verify-{sd.name}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sd.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(sd))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
    )


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
