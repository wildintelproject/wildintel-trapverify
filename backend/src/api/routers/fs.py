import logging
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/fs", tags=["filesystem"])
logger = logging.getLogger(__name__)


def _read_csv(path: Path) -> "pd.DataFrame":
    compression = "gzip" if path.name.endswith(".gz") else None
    return pd.read_csv(path, dtype=str, compression=compression)


@router.get("/inspect")
def fs_inspect(path: str) -> dict:
    """Inspect a CamtrapDP directory for species and date range.

    Accepts plain .csv and gzip-compressed .csv.gz files, and also searches
    one level of subdirectory (needed when a Trapper ZIP extracts into a
    named subfolder).

    If the directory already ships a ``datapackage.json`` (e.g. it came from
    Trapper or another CamtrapDP-producing tool), it's validated with
    ``frictionless`` and any errors are returned in ``datapackage_errors`` --
    non-fatal, just surfaced to the user. Packages this app itself converts
    from a DeepFaune/generic CSV don't have one, so that key is ``None`` then.
    """
    from camtrap_workflow import find_datapackage, resolve_camtrapdp_resource

    logger.info("Inspecting CamtrapDP directory: %s", path)
    p = Path(path)

    obs_path = resolve_camtrapdp_resource(p, "observations")
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
    med_path = resolve_camtrapdp_resource(p, "media")
    if med_path is not None:
        from camtrap_workflow import normalise_ts
        med = _read_csv(med_path)
        ts = pd.to_datetime(
            med["timestamp"].apply(normalise_ts), errors="coerce", utc=False
        ).dropna()
        if not ts.empty:
            start_date = ts.min().date().isoformat()
            end_date = ts.max().date().isoformat()

    datapackage_errors: list[str] | None = None
    dp_path = find_datapackage(p)
    if dp_path is not None:
        from camtrap_workflow import validate_camtrapdp_datapackage
        try:
            datapackage_errors = validate_camtrapdp_datapackage(dp_path)
        except Exception:
            logger.exception("Failed to validate datapackage.json at %s", dp_path)
            datapackage_errors = None

    logger.info("Inspect result: %d species, %s to %s", len(species), start_date, end_date)
    return {
        "species": species,
        "study_start": start_date,
        "study_end": end_date,
        "datapackage_errors": datapackage_errors,
    }


@router.get("/check-images")
def check_images(camtrap_dir: str, image_base_dir: str = "", flat_search: bool = False) -> dict:
    """Check how many media.csv entries resolve to an existing local file.

    When image_base_dir is given, it takes precedence over filePath: each
    image is first looked up at image_base_dir/deploymentID/fileName, even
    for remote (http/https) filePath values -- a common TRAPPER export has a
    remote filePath but the files were downloaded locally under that layout.
    If that misses and flat_search is enabled, fileName is looked up anywhere
    under image_base_dir (see resolve_media_path). Falls back to the previous
    rule (filePath resolved against image_base_dir if given, otherwise
    against the parent of camtrap_dir) when nothing above matched, or when
    image_base_dir is not set (in which case remote filePath values are
    skipped, since those are fetched on demand via the image proxy and are
    not expected to exist locally).
    """
    from camtrap_workflow import (
        find_flat_search_ambiguities,
        is_remote_path,
        resolve_camtrapdp_resource,
        resolve_media_path,
    )

    p = Path(camtrap_dir)
    med_path = resolve_camtrapdp_resource(p, "media")
    if med_path is None:
        raise HTTPException(400, f"No se encontró media.csv en {camtrap_dir}")

    med = _read_csv(med_path)
    if "fileName" in med.columns:
        med["fileName"] = med["fileName"].fillna("")
    else:
        med["fileName"] = med.get("filePath", pd.Series(dtype=str)).fillna("").apply(
            lambda x: Path(x).name
        )
    file_names = med["fileName"]
    dep_ids = med.get("deploymentID", pd.Series(dtype=str)).fillna("")
    file_paths = med.get("filePath", pd.Series(dtype=str))
    fallback_base = Path(image_base_dir) if image_base_dir else p.parent

    total = 0
    missing = 0
    permission_denied = 0
    examples: list[str] = []
    for fp_raw, dep_id, file_name in zip(file_paths, dep_ids, file_names):
        if pd.isna(fp_raw) or str(fp_raw) == "":
            continue
        fp = str(fp_raw)
        if is_remote_path(fp) and not image_base_dir:
            continue
        total += 1
        file_path = resolve_media_path(
            fp, str(dep_id), str(file_name), image_base_dir, fallback_base,
            flat_search=flat_search,
        )
        try:
            exists = file_path.exists()
        except PermissionError:
            permission_denied += 1
            if len(examples) < 5:
                examples.append(str(file_path))
            continue
        if not exists:
            missing += 1
            if len(examples) < 5:
                examples.append(str(file_path))

    ambiguous = find_flat_search_ambiguities(med, image_base_dir) if flat_search else []

    if missing:
        logger.warning("Image check: %d/%d media files missing under base=%s", missing, total, fallback_base)
    if permission_denied:
        logger.warning("Image check: %d/%d media files denied access under base=%s", permission_denied, total, fallback_base)
    if ambiguous:
        logger.warning("Image check: %d ambiguous flat-search match(es) under %s", len(ambiguous), image_base_dir)
    return {
        "total": total,
        "missing": missing,
        "permission_denied": permission_denied,
        "examples": examples,
        "ambiguous": ambiguous,
    }


@router.get("/browse")
def fs_browse(path: str = "", show_files: bool = False, ext: str = "") -> dict:
    """Return subdirectories (and optionally files) of path for the filesystem picker.

    When ``show_files=True``, files matching ``ext`` (e.g. ``'.csv'``) are also
    returned in a ``files`` list alongside the usual ``dirs`` list.
    """
    p = Path(path).resolve() if path else Path.home()
    while not p.exists() or not p.is_dir():
        parent = p.parent
        if parent == p:
            p = Path.home()
            break
        p = parent
    try:
        all_items = list(p.iterdir())
        dirs = sorted(
            (item for item in all_items if item.is_dir() and not item.name.startswith(".")),
            key=lambda x: x.name.lower(),
        )
        files: list[dict] = []
        if show_files:
            matched = sorted(
                (
                    item for item in all_items
                    if item.is_file()
                    and not item.name.startswith(".")
                    and (not ext or item.suffix.lower() == ext.lower())
                ),
                key=lambda x: x.name.lower(),
            )
            files = [{"name": f.name, "path": str(f)} for f in matched]
        return {
            "current": str(p),
            "parent": str(p.parent) if p.parent != p else None,
            "dirs": [{"name": d.name, "path": str(d)} for d in dirs],
            "files": files,
        }
    except PermissionError:
        logger.warning("Permission denied browsing %s", p)
        raise HTTPException(403, "Sin permiso de acceso")


@router.get("/csv-headers")
def csv_headers(path: str) -> dict:
    """Return column names of a CSV file."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(400, f"No se encontró el fichero: {path}")
    try:
        df = pd.read_csv(p, nrows=0, dtype=str)
        return {"columns": list(df.columns)}
    except Exception as exc:
        raise HTTPException(400, f"Error al leer el CSV: {exc}") from exc


@router.get("/csv-labels")
def csv_labels(path: str, col: str) -> dict:
    """Return unique (lowercased) values of a column, pre-filled with DeepFaune map matches."""
    from camtrap_workflow import DEEPFAUNE_LABEL_MAP
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(400, f"No se encontró el fichero: {path}")
    try:
        df = pd.read_csv(p, dtype=str, usecols=[col])
        raw = df[col].dropna().astype(str).str.lower().str.strip()
        labels = sorted(raw.unique().tolist())
        prefilled = {lbl: DEEPFAUNE_LABEL_MAP[lbl] for lbl in labels if lbl in DEEPFAUNE_LABEL_MAP}
        return {"labels": labels, "prefilled": prefilled}
    except Exception as exc:
        raise HTTPException(400, f"Error al leer la columna '{col}': {exc}") from exc
