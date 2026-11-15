"""Export a session to a ZIP and import it on another computer.

Only the review state travels (config, candidate manifest, decisions and logs); the photos and the
CamtrapDP stay where they are and are re-linked on the receiving computer. Outputs are not shipped:
they are regenerated from the decisions.
"""
import io
import json
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from services import session_service

logger = logging.getLogger(__name__)

SESSION_FILES = (
    "config.json",
    "candidate_manifest.csv",
    "rejected_media.json",
    "min_score_exclusions.csv",
    "rejection_corrections.csv",
    "review_log.csv",
)
MAX_UNCOMPRESSED_BYTES = 2 * 1024**3          # guards against zip bombs


def export_zip(sd: Path) -> bytes:
    """Zip the session's review state in memory."""
    if not (sd / "config.json").exists():
        raise HTTPException(400, "No es una sesión válida.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in SESSION_FILES:
            f = sd / name
            if f.is_file():
                zf.write(f, name)
        dec = sd / "decisions"
        if dec.is_dir():
            for f in sorted(dec.glob("*.csv")):
                zf.write(f, f"decisions/{f.name}")
    return buf.getvalue()


def _safe_member(name: str) -> str | None:
    """Return the normalised member name if it is an allowed, non-escaping path, else None."""
    if not name or name.endswith("/") or "\\" in name:
        return None
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or re.match(r"^[A-Za-z]:", name):
        return None
    if len(p.parts) == 1 and p.name in SESSION_FILES:
        return p.name
    if len(p.parts) == 2 and p.parts[0] == "decisions" and p.name.endswith(".csv"):
        return str(p)
    return None


def import_zip(zip_path: str) -> Path:
    """Extract a session ZIP into a new folder and make it the active session."""
    zp = Path(zip_path)
    if not zp.is_file():
        raise HTTPException(400, f"Archivo no encontrado: {zp}")
    try:
        zf = zipfile.ZipFile(zp)
    except zipfile.BadZipFile:
        raise HTTPException(400, "El archivo no es un ZIP válido.")
    with zf:
        members = {}
        total = 0
        for info in zf.infolist():
            safe = _safe_member(info.filename)
            if safe is None:
                continue                                   # ignore anything unexpected
            total += info.file_size
            members[safe] = info
        if total > MAX_UNCOMPRESSED_BYTES:
            raise HTTPException(400, "El ZIP es demasiado grande.")
        if "config.json" not in members or "candidate_manifest.csv" not in members:
            raise HTTPException(400, "El ZIP no es una sesión de CamTrap Verify (faltan config.json o candidate_manifest.csv).")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = session_service.DEFAULT_OUTPUT_DIR / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', zp.stem)}_imported_{stamp}"
        dest.mkdir(parents=True, exist_ok=False)
        for safe, info in members.items():
            target = dest / safe
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
    cfg_file = dest / "config.json"
    try:
        config = json.loads(cfg_file.read_text())
    except ValueError:
        raise HTTPException(400, "config.json del ZIP no es válido.")
    config["session_dir"] = str(dest)
    config["output_dir"] = str(dest / "camtrap_dp_verified")
    session_service.write_config_file(cfg_file, config)
    logger.info("Session imported from %s into %s", zp, dest)
    return dest
