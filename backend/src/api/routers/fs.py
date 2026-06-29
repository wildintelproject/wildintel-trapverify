import logging
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/fs", tags=["filesystem"])
logger = logging.getLogger(__name__)


def _find_csv(directory: Path, stem: str) -> Path | None:
    """Return the first existing variant: stem.csv, stem.csv.gz, or inside a single subdir."""
    if not directory.exists() or not directory.is_dir():
        return None
    for base in (directory, *[d for d in directory.iterdir() if d.is_dir()]):
        for suffix in ("csv", "csv.gz"):
            candidate = base / f"{stem}.{suffix}"
            if candidate.exists():
                return candidate
    return None


def _read_csv(path: Path) -> "pd.DataFrame":
    compression = "gzip" if path.name.endswith(".gz") else None
    return pd.read_csv(path, dtype=str, compression=compression)


@router.get("/inspect")
def fs_inspect(path: str) -> dict:
    """Inspect a CamtrapDP directory for species and date range.

    Accepts plain .csv and gzip-compressed .csv.gz files, and also searches
    one level of subdirectory (needed when a Trapper ZIP extracts into a
    named subfolder).
    """
    logger.info("Inspecting CamtrapDP directory: %s", path)
    p = Path(path)

    obs_path = _find_csv(p, "observations")
    if obs_path is None:
        logger.warning("observations.csv not found in %s", path)
        raise HTTPException(400, f"No se encontró observations.csv en {path}")

    obs = _read_csv(obs_path)
    species = sorted(
        obs.loc[
            (obs.get("observationType", pd.Series()) == "animal")
            & obs["scientificName"].notna()
            & (obs["scientificName"] != ""),
            "scientificName",
        ].unique().tolist()
    )

    start_date, end_date = None, None
    med_path = _find_csv(p, "media")
    if med_path is not None:
        from camtrap_workflow import normalise_ts
        med = _read_csv(med_path)
        ts = pd.to_datetime(
            med["timestamp"].apply(normalise_ts), errors="coerce", utc=False
        ).dropna()
        if not ts.empty:
            start_date = ts.min().date().isoformat()
            end_date = ts.max().date().isoformat()

    logger.info("Inspect result: %d species, %s to %s", len(species), start_date, end_date)
    return {"species": species, "study_start": start_date, "study_end": end_date}


@router.get("/browse")
def fs_browse(path: str = "") -> dict:
    """Return subdirectories of path for the filesystem picker."""
    p = Path(path).resolve() if path else Path.home()
    while not p.exists() or not p.is_dir():
        parent = p.parent
        if parent == p:
            p = Path.home()
            break
        p = parent
    try:
        dirs = sorted(
            (item for item in p.iterdir() if item.is_dir() and not item.name.startswith(".")),
            key=lambda x: x.name.lower(),
        )
        return {
            "current": str(p),
            "parent": str(p.parent) if p.parent != p else None,
            "dirs": [{"name": d.name, "path": str(d)} for d in dirs],
        }
    except PermissionError:
        logger.warning("Permission denied browsing %s", p)
        raise HTTPException(403, "Sin permiso de acceso")
