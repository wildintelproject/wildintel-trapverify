"""
CamTrap Verify — backend workflow.

Port of the R verification pipeline to Python/pandas. Handles loading a
CamtrapDP dataset, building the ranked candidate manifest, persisting expert
decisions, and generating the verified CamtrapDP and occupancy-model inputs.
"""
import json
import logging
import os
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pandas as pd

logger = logging.getLogger(__name__)


# ─── DeepFaune label map ──────────────────────────────────────────────────────

DEEPFAUNE_LABEL_MAP: dict[str, str] = {
    "red deer": "Cervus elaphus",
    "fallow deer": "Dama dama",
    "wild boar": "Sus scrofa",
    "fox": "Vulpes vulpes",
    "badger": "Meles meles",
    "dog": "Canis familiaris",
    "cat": "Felis catus",
    "genet": "Genetta genetta",
    "lynx": "Lynx pardinus",
    "mongoose": "Herpestes ichneumon",
    "lagomorph": "Lepus granatensis",
    "micromammal": "Rodentia",
    "mustelid": "Mustelidae",
    "equid": "Equus",
    "cow": "Bos taurus",
    "bird": "Aves",
    "squirrel": "Sciurus vulgaris",
    "nutria": "Myocastor coypus",
    "wolf": "Canis lupus",
    "bear": "Ursus arctos",
    "chamois": "Rupicapra rupicapra",
    "ibex": "Capra pyrenaica",
    "roe deer": "Capreolus capreolus",
    "mouflon": "Ovis gmelini musimon",
    "rabbit": "Oryctolagus cuniculus",
    "hare": "Lepus europaeus",
    "marten": "Martes martes",
    "polecat": "Mustela putorius",
    "otter": "Lutra lutra",
    "mink": "Neovison vison",
    "raccoon": "Procyon lotor",
    "sheep": "Ovis aries",
    "goat": "Capra hircus",
    "pig": "Sus domesticus",
    "deer": "Cervidae",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def sanitize(name: str) -> str:
    """Replace non-alphanumeric characters with underscores.

    Used to produce safe filenames and DataFrame key suffixes from scientific
    names (e.g. ``'Vulpes vulpes'`` → ``'Vulpes_vulpes'``).

    Args:
        name: Arbitrary string to sanitize.

    Returns:
        String with every character outside ``[A-Za-z0-9]`` replaced by ``_``.
    """
    return re.sub(r"[^A-Za-z0-9]", "_", name)


_TZ_OFFSET_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def normalise_ts(x: str) -> str:
    """Convert an EXIF timestamp to a tz-naive ISO-8601 string.

    EXIF stores dates as ``'YYYY:MM:DD HH:MM:SS'``; this converts the date
    separator from ``:`` to ``-``. Already-ISO strings are returned unchanged
    other than the timezone stripping below.

    Also strips any trailing UTC offset or ``Z`` suffix (e.g. ``+01:00``,
    ``+0000``, ``Z``). Real-world Trapper/CamtrapDP exports can mix
    tz-aware and tz-naive timestamps in the same ``media.csv`` — e.g. some
    rows carry ``+00:00`` and others none at all — and pandas 2.x's
    ``to_datetime`` refuses to build one array out of a mix of aware/naive
    values ("Mixed timezones detected"). Every caller of this function
    only uses the resulting timestamp for its wall-clock date/time (sampling
    occasion assignment, burst gaps, display) via ``utc=False``, never as an
    absolute instant, so dropping the offset and keeping the recorded local
    time is the correct behavior here, not just a crash workaround.

    Args:
        x: Timestamp string, either EXIF (``'YYYY:MM:DD …'``) or ISO-8601,
            optionally with a UTC offset or ``Z`` suffix.

    Returns:
        Tz-naive ISO-8601 timestamp string ``'YYYY-MM-DD HH:MM:SS'``.
    """
    s = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", str(x))
    return _TZ_OFFSET_RE.sub("", s)


# ─── CamtrapDP I/O ────────────────────────────────────────────────────────────

def find_datapackage(camtrap_dir: Path) -> Optional[Path]:
    """Return the path to ``datapackage.json`` if present, at the root or one subdir down.

    One level of subdirectory is checked because a Trapper ZIP extracts into
    a named subfolder.
    """
    if not camtrap_dir.exists() or not camtrap_dir.is_dir():
        return None
    for base in (camtrap_dir, *[d for d in camtrap_dir.iterdir() if d.is_dir()]):
        candidate = base / "datapackage.json"
        if candidate.exists():
            return candidate
    return None


def resolve_camtrapdp_resource(camtrap_dir: Path, name: str) -> Optional[Path]:
    """Locate one of the CamtrapDP tables (``deployments``, ``media`` or ``observations``).

    When a ``datapackage.json`` is present, the Data Package spec requires
    each resource to declare where its data lives via ``path`` -- so that's
    used first, resolved relative to the datapackage.json's own directory
    (not necessarily ``camtrap_dir`` itself, since it may be one subdir
    down). This is what lets non-standard file names (e.g. a Trapper export
    named ``deployments.csv.gz`` or something else entirely) still be found.

    Falls back to the ``{name}.csv`` / ``{name}.csv.gz`` naming convention
    (checked at ``camtrap_dir``'s root or one subdir down) when there's no
    datapackage.json, the resource is missing from it, or its declared path
    doesn't actually exist on disk.
    """
    dp_path = find_datapackage(camtrap_dir)
    if dp_path is not None:
        try:
            descriptor = json.loads(dp_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read %s while resolving resource %r", dp_path, name)
        else:
            for resource in descriptor.get("resources", []):
                if resource.get("name") == name:
                    path = resource.get("path")
                    if isinstance(path, str):
                        candidate = (dp_path.parent / path).resolve()
                        if candidate.exists():
                            return candidate
                    break

    if not camtrap_dir.exists() or not camtrap_dir.is_dir():
        return None
    for base in (camtrap_dir, *[d for d in camtrap_dir.iterdir() if d.is_dir()]):
        for suffix in ("csv", "csv.gz"):
            candidate = base / f"{name}.{suffix}"
            if candidate.exists():
                return candidate
    return None


def load_camtrapdp(camtrap_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the three core CamtrapDP tables from a directory.

    All columns are kept as ``str`` to avoid silent type coercions on IDs.
    File locations are resolved via :func:`resolve_camtrapdp_resource`, so a
    ``datapackage.json`` declaring non-standard file names (or ``.csv.gz``
    compression) is honoured; missing tables raise the same
    ``FileNotFoundError`` pandas would for a plain ``{name}.csv`` lookup.

    Args:
        camtrap_dir: Path to the directory containing ``deployments.csv``,
            ``media.csv`` and ``observations.csv`` (or a ``datapackage.json``
            pointing at differently-named equivalents).

    Returns:
        Tuple of ``(deployments, media, observations)`` DataFrames.
    """
    def _load(name: str) -> pd.DataFrame:
        path = resolve_camtrapdp_resource(camtrap_dir, name)
        if path is None:
            path = camtrap_dir / f"{name}.csv"  # let pandas raise a familiar error
        return pd.read_csv(path, dtype=str)

    dep = _load("deployments")
    med = _load("media")
    obs = _load("observations")
    if "fileName" not in med.columns:
        med["fileName"] = med["filePath"].apply(
            lambda x: Path(str(x)).name if pd.notna(x) else ""
        )
    return dep, med, obs


def validate_camtrapdp_datapackage(datapackage_path: Path) -> list[str]:
    """Validate a ``datapackage.json`` with ``frictionless``, as its own CLI does.

    Checks the descriptor is well-formed and that each declared resource's
    data matches its own schema (types, required fields, missing files).
    Returns a list of human-readable error strings (empty when valid). This
    only applies to a *pre-existing* CamtrapDP package (e.g. from Trapper or
    another tool) that already ships a ``datapackage.json`` -- packages this
    app generates itself from a DeepFaune/generic CSV don't have one yet, so
    callers should skip validation rather than treat its absence as an error.
    """
    import frictionless

    report = frictionless.validate(str(datapackage_path))
    if report.valid:
        return []

    def _describe(err) -> str:
        # Some error types (e.g. missing-label) leave .note empty and put the
        # actual detail in .message instead.
        return err.note or err.message or err.title

    errors = [_describe(err) for err in report.errors]
    for task in report.tasks:
        for err in task.errors:
            row, field = getattr(err, "row_number", None), getattr(err, "field_name", None)
            detail = _describe(err)
            if row is not None and field is not None:
                errors.append(f"{task.name}: fila {row}, campo '{field}': {detail}")
            else:
                errors.append(f"{task.name}: {detail}")
    return errors


CAMTRAPDP_PROFILE = "https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/camtrap-dp-profile.json"


def generate_default_datapackage(
    dep: pd.DataFrame, med: pd.DataFrame, obs: pd.DataFrame,
) -> dict:
    """Build a best-effort ``datapackage.json`` descriptor for a package that has none.

    Fills in whatever can be derived from the data itself (``resources``,
    ``temporal`` from ``media.csv`` timestamps, ``taxonomic`` from
    ``observations.csv`` species, ``spatial`` from ``deployments.csv``
    coordinates when present, ``project.observationLevel`` when
    ``observations.csv`` uses a single consistent value) and invents a
    placeholder for everything else the app has no way to know
    (``contributors``, sampling/capture method, whether individuals are
    tracked, a project title, and ``spatial`` when no coordinates exist).

    The invented keys are listed under the non-standard ``wildintelGenerated``
    property so a caller can warn the user which parts are placeholders, not
    real study metadata -- this descriptor is a starting point to edit, not a
    citable/archival-ready one as-is.
    """
    from datetime import datetime, timezone

    fabricated: list[str] = []

    def resource(name: str) -> dict:
        # Camtrap DP requires deployments/media/observations to reference the
        # official versioned Table Schema by URL, not an inline schema.
        return {
            "name": name,
            "path": f"{name}.csv",
            "profile": "tabular-data-resource",
            "schema": f"https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/{name}-table-schema.json",
        }

    ts = pd.to_datetime(med.get("timestamp", pd.Series(dtype=str)).apply(normalise_ts), errors="coerce").dropna()
    if not ts.empty:
        temporal = {"start": ts.min().date().isoformat(), "end": ts.max().date().isoformat()}
    else:
        temporal = {"start": None, "end": None}
        fabricated.append("temporal")

    species = sorted({s for s in obs.get("scientificName", pd.Series(dtype=str)).dropna().tolist() if s})
    if species:
        taxonomic = [{"scientificName": s} for s in species]
    else:
        taxonomic = []
        fabricated.append("taxonomic")

    lat = pd.to_numeric(dep.get("latitude", pd.Series(dtype=str)), errors="coerce").dropna()
    lon = pd.to_numeric(dep.get("longitude", pd.Series(dtype=str)), errors="coerce").dropna()
    if not lat.empty and not lon.empty:
        spatial = {
            "type": "Polygon",
            "coordinates": [[
                [lon.min(), lat.min()], [lon.max(), lat.min()],
                [lon.max(), lat.max()], [lon.min(), lat.max()],
                [lon.min(), lat.min()],
            ]],
        }
    else:
        spatial = {"type": "Point", "coordinates": [0.0, 0.0]}
        fabricated.append("spatial")

    levels = obs.get("observationLevel", pd.Series(dtype=str)).dropna().unique().tolist()
    if len(levels) == 1 and levels[0] in ("media", "event"):
        observation_level = [levels[0]]
    else:
        observation_level = ["media"]
        fabricated.append("project.observationLevel")

    fabricated += [
        "contributors", "project.title", "project.samplingDesign",
        "project.captureMethod", "project.individualAnimals",
    ]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "name": "camtrap-dp-export",
        "profile": CAMTRAPDP_PROFILE,
        "created": now,
        "resources": [resource("deployments"), resource("media"), resource("observations")],
        "contributors": [{"title": "Unknown", "role": "contributor"}],
        "project": {
            "title": "Untitled camera trap project",
            "samplingDesign": "opportunistic",
            "captureMethod": ["activityDetection"],
            "individualAnimals": False,
            "observationLevel": observation_level,
        },
        "spatial": spatial,
        "temporal": temporal,
        "taxonomic": taxonomic,
        "wildintelGenerated": {
            "generated": True,
            "generatedAt": now,
            "fabricatedFields": fabricated,
            "note": (
                "Auto-generated by CamTrap Verify because the source package had no "
                "datapackage.json. Fields listed in fabricatedFields are placeholders, "
                "not derived from the data -- review and correct them before treating "
                "this as a citable/archival package."
            ),
        },
    }


def _exists_or_denied(path: Path) -> bool:
    """Like ``Path.exists()`` but treats a permission error as "exists".

    ``Path.exists()`` re-raises ``PermissionError`` instead of returning
    ``False`` (unlike a missing file, which it swallows). When the OS denies
    access to a candidate path, we still want callers to pick it: the real
    error should surface later, when the file is actually opened for reading.
    """
    try:
        return path.exists()
    except PermissionError:
        logger.warning("Permission denied checking %s", path)
        return True


@lru_cache(maxsize=8)
def _flat_image_index(image_base_dir: str) -> dict[str, tuple[str, ...]]:
    """Recursively index every file under ``image_base_dir`` by lowercase basename.

    Mirrors the "flat" search in R's ``resolve_media_files()``: when the
    structured ``deploymentID/fileName`` layout doesn't hold, images may sit
    loose in a single folder (a common TRAPPER download), so we fall back to
    a name-only lookup across the whole tree. Cached per ``image_base_dir``
    for the lifetime of the process so it is scanned once, not per image.
    """
    index: dict[str, list[str]] = {}
    for root, _dirs, files in os.walk(image_base_dir):
        for f in files:
            index.setdefault(f.lower(), []).append(os.path.join(root, f))
    return {k: tuple(v) for k, v in index.items()}


def clear_media_caches() -> None:
    """Drop the cached flat-search file index.

    ``_flat_image_index`` never invalidates on its own (no mtime/TTL check),
    so a new session reusing the same ``image_base_dir`` after files were
    added, moved, or removed on disk would otherwise keep seeing the old
    listing for as long as this backend process stays alive. Call this once
    per new setup so each session starts from a fresh scan.
    """
    _flat_image_index.cache_clear()


def is_remote_path(file_path: str) -> bool:
    """True if a media record's ``filePath`` is a remote HTTP(S) URL rather
    than a local (absolute or relative) path."""
    return file_path.startswith("http://") or file_path.startswith("https://")


def resolve_media_path(
    file_path: str,
    deployment_id: str,
    file_name: str,
    image_base_dir: str,
    fallback_base: Path,
    flat_search: bool = False,
) -> Path:
    """Resolve a media record to a local file path.

    When ``image_base_dir`` is set, it takes precedence over ``filePath``:
    the image is first looked up at ``image_base_dir/deploymentID/fileName``
    (matching R's structured ``resolve_media_files()``), regardless of
    whether ``filePath`` is absolute, relative, or a remote URL -- a common
    TRAPPER export has a remote ``filePath`` but the files were downloaded
    locally under that layout.

    If that misses and ``flat_search`` is enabled, ``fileName`` is looked up
    case-insensitively anywhere under ``image_base_dir`` (R's "flat" mode).
    Ties are broken by keeping only hits whose path contains
    ``deployment_id``; if more than one candidate remains, the match is
    ambiguous and is logged as such (not raised -- a single image failing to
    resolve should not interrupt review of the rest), and resolution falls
    through to the next rule.

    Otherwise falls back to the previous rule (``filePath`` used as-is if
    absolute, otherwise joined to ``fallback_base``) when nothing above
    matched, or when ``image_base_dir`` is not set.

    Args:
        file_path: The record's ``filePath`` value (may be absolute,
            relative, or a remote URL).
        deployment_id: The record's ``deploymentID``.
        file_name: The record's ``fileName`` (or a basename derived from
            ``filePath`` when the source has no dedicated column).
        image_base_dir: User-supplied image root, or ``""`` if not set.
        fallback_base: Base directory used to resolve a relative
            ``file_path`` when ``image_base_dir`` is not set (normally
            ``camtrap_dir`` itself).
        flat_search: If True, search ``image_base_dir`` recursively by
            ``fileName`` when the structured path misses. Defaults to False.

    Returns:
        The resolved path (existence is not checked here).
    """
    if image_base_dir:
        structured = Path(image_base_dir) / deployment_id / file_name
        if _exists_or_denied(structured):
            return structured

        if flat_search and file_name:
            hits = _flat_image_index(str(image_base_dir)).get(file_name.lower(), ())
            if len(hits) == 1:
                return Path(hits[0])
            if len(hits) > 1:
                by_dep = [h for h in hits if deployment_id and deployment_id in h]
                if len(by_dep) == 1:
                    return Path(by_dep[0])
                logger.warning(
                    "Ambiguous flat match for %s: %d candidates (%s)",
                    file_name, len(hits), ", ".join(hits),
                )

    p = Path(file_path)
    if not p.is_absolute():
        base = Path(image_base_dir) if image_base_dir else fallback_base
        p = (base / p).resolve()
    return p


def gallery_frame_img_url(
    file_path: str,
    media_id: str,
    deployment_id: str,
    file_name: str,
    image_base_dir: str,
    fallback_base: Path,
    flat_search: bool = False,
) -> str:
    """Pick the URL a gallery frame should load its image from.

    A remote ``filePath`` doesn't necessarily mean the file has to be
    fetched over the network: when ``image_base_dir`` is set, the same
    TRAPPER-style layout ``resolve_media_path`` already knows how to find
    (deploymentID/fileName, or flat search) may have the file downloaded
    locally. Only proxy the remote URL when that local lookup misses --
    otherwise reviewers without access to the remote server always get a
    404 on data that's already on disk for exactly this reason.
    """
    if is_remote_path(file_path):
        if image_base_dir:
            local_path = resolve_media_path(
                file_path, deployment_id, file_name, image_base_dir, fallback_base,
                flat_search=flat_search,
            )
            if _exists_or_denied(local_path):
                return f'/api/image/{media_id}'
        return f'/api/proxy-image?url={quote(file_path, safe="")}'
    return f'/api/image/{media_id}'


def find_flat_search_ambiguities(med: pd.DataFrame, image_base_dir: str) -> list[dict]:
    """Find media records whose flat-search-by-fileName match would be ambiguous.

    For each record not resolved by the structured
    ``image_base_dir/deploymentID/fileName`` path, looks up ``fileName`` in
    the flat index; if more than one file shares that name and
    ``deploymentID`` does not disambiguate it, the record is reported.
    Mirrors the abort condition in R's ``resolve_media_files()``: an
    ambiguous match risks silently associating the wrong photo with a
    site/occasion, contaminating an occupancy cell -- callers should stop
    and ask the user to fix the folder layout rather than guess.

    Args:
        med: Media DataFrame with at least ``deploymentID`` and ``fileName``
            columns (as ensured by ``load_camtrapdp``).
        image_base_dir: Image root to search under. Returns ``[]`` if empty,
            since there is nothing to search.

    Returns:
        List of dicts with ``mediaID``, ``fileName``, ``deploymentID`` and
        the conflicting candidate paths, one per ambiguous record.
    """
    if not image_base_dir:
        return []
    index = _flat_image_index(str(image_base_dir))
    ambiguous: list[dict] = []
    for _, row in med.iterrows():
        dep_id = str(row.get("deploymentID", "") or "")
        file_name = str(row.get("fileName", "") or "")
        if not file_name:
            continue
        structured = Path(image_base_dir) / dep_id / file_name
        if structured.exists():
            continue
        hits = index.get(file_name.lower(), ())
        if len(hits) <= 1:
            continue
        by_dep = [h for h in hits if dep_id and dep_id in h]
        if len(by_dep) == 1:
            continue
        ambiguous.append({
            "mediaID": str(row.get("mediaID", "")),
            "fileName": file_name,
            "deploymentID": dep_id,
            "candidates": list(hits),
        })
    return ambiguous


def detect_site_col(dep: pd.DataFrame) -> str:
    """Detect the site identifier column in a deployments DataFrame.

    Prefers ``locationID`` when the column exists and contains at least one
    non-empty value; otherwise falls back to ``deploymentID``.

    Args:
        dep: Deployments DataFrame as read from ``deployments.csv``.

    Returns:
        Column name: ``'locationID'`` or ``'deploymentID'``.
    """
    if "locationID" in dep.columns:
        valid = dep["locationID"].dropna()
        valid = valid[valid != ""]
        if len(valid) > 0:
            return "locationID"
    return "deploymentID"


# ─── DeepFaune → CamtrapDP ────────────────────────────────────────────────────

def deepfaune_to_camtrapdp(
    df: pd.DataFrame,
    species_map: dict,
    out_dir: Path,
    label_col: str = "top1",
    score_col: str = "score",
    min_score: float = 0.0,
) -> Path:
    """Convert a DeepFaune results CSV to CamtrapDP format.

    Writes ``deployments.csv``, ``media.csv`` and ``observations.csv`` to
    ``out_dir``. Non-animal labels (empty, human, undefined) are mapped to the
    appropriate CamtrapDP ``observationType`` values. Rows below ``min_score``
    are included but with ``scientificName=None``.

    ``filePath`` is written as the ``filename`` column value as-is (only
    backslashes normalised to forward slashes) -- it is not resolved or
    made absolute here. Locating the actual image files is left entirely to
    ``resolve_media_path()``, exactly like a CamtrapDP directory picked
    directly in Step 1: the caller sets ``image_base_dir`` on the session
    (structured ``image_base_dir/deploymentID/fileName`` lookup, or flat
    search by ``fileName``), rather than this conversion baking a base
    directory into the CSV once and for all.

    Args:
        df: DeepFaune results DataFrame (one row per image).
        species_map: Mapping from DeepFaune label (lowercase) to scientific name.
        out_dir: Destination directory for the CamtrapDP files.
        label_col: Column in ``df`` holding the predicted label. Defaults to
            ``'top1'``.
        score_col: Column in ``df`` holding the confidence score. Defaults to
            ``'score'``.
        min_score: Minimum confidence score to assign a scientific name.
            Rows below this threshold get ``scientificName=None``.

    Returns:
        Path to ``out_dir`` (the written CamtrapDP directory).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    nonanimal = {
        "empty": "blank", "vide": "blank", "human": "human",
        "humain": "human", "undefined": "unclassified",
    }

    def site_from_path(p: str) -> str:
        return re.sub(r"^R\d+-", "", Path(p).parent.name)

    paths = df["filename"].astype(str).str.replace("\\", "/", regex=False)
    file_names = paths.apply(lambda p: Path(p).name)
    sites = df["site"].astype(str) if "site" in df.columns else paths.apply(site_from_path)
    labels = df[label_col].astype(str).str.lower().str.strip()
    scores = pd.to_numeric(df.get(score_col, pd.Series([None] * len(df))), errors="coerce")
    timestamps = df["date"].astype(str).apply(normalise_ts)

    n = len(df)
    media_ids = [f"m{i:07d}" for i in range(1, n + 1)]
    obs_ids = [f"o{i:07d}" for i in range(1, n + 1)]

    sci_names, obs_types = [], []
    for label, score in zip(labels, scores):
        if label in nonanimal:
            sci_names.append(None)
            obs_types.append(nonanimal[label])
        else:
            sn = species_map.get(label, label)
            obs_types.append("animal")
            if min_score > 0 and (pd.isna(score) or score < min_score):
                sci_names.append(None)
            else:
                sci_names.append(sn)

    unique_sites = sorted(set(sites))
    pd.DataFrame({"deploymentID": unique_sites, "locationID": unique_sites,
                  "locationName": unique_sites}).to_csv(out_dir / "deployments.csv", index=False)
    pd.DataFrame({"mediaID": media_ids, "deploymentID": list(sites),
                  "timestamp": list(timestamps), "filePath": list(paths),
                  "fileName": list(file_names)}).to_csv(
        out_dir / "media.csv", index=False)
    pd.DataFrame({
        "observationID": obs_ids, "deploymentID": list(sites), "mediaID": media_ids,
        "observationLevel": "media", "observationType": obs_types,
        "scientificName": sci_names, "classificationProbability": list(scores),
        "classificationMethod": "machine", "classifiedBy": "DeepFaune",
        "classificationTimestamp": None,
    }).to_csv(out_dir / "observations.csv", index=False)
    return out_dir


def generic_csv_to_camtrapdp(
    df: pd.DataFrame,
    out_dir: Path,
    col_filename: str,
    col_datetime: str,
    col_label: str,
    col_score: Optional[str] = None,
    col_site: Optional[str] = None,
    species_map: Optional[dict] = None,
    image_base_dir: Optional[Path] = None,
) -> Path:
    """Convert any classifier CSV to CamtrapDP using user-defined column mapping."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if species_map is None:
        species_map = {}

    nonanimal = {
        "empty": "blank", "vide": "blank", "blank": "blank",
        "human": "human", "humain": "human", "person": "human",
        "undefined": "unclassified", "unknown": "unclassified",
    }

    def abs_path(p: str) -> str:
        p = p.replace("\\", "/")
        if image_base_dir and not (p.startswith("/") or (len(p) > 1 and p[1] == ":")):
            p = str(image_base_dir / p)
        return str(Path(p).resolve())

    def site_from_path(p: str) -> str:
        return re.sub(r"^R\d+-", "", Path(p).parent.name)

    paths = df[col_filename].astype(str).apply(abs_path)
    sites = (
        df[col_site].astype(str)
        if col_site and col_site in df.columns
        else paths.apply(site_from_path)
    )
    labels = df[col_label].astype(str).str.lower().str.strip()
    scores = (
        pd.to_numeric(df[col_score], errors="coerce")
        if col_score and col_score in df.columns
        else pd.Series([None] * len(df))
    )
    timestamps = df[col_datetime].astype(str).apply(normalise_ts)

    n = len(df)
    media_ids = [f"m{i:07d}" for i in range(1, n + 1)]
    obs_ids   = [f"o{i:07d}" for i in range(1, n + 1)]

    sci_names, obs_types = [], []
    for label in labels:
        if label in nonanimal:
            sci_names.append(None)
            obs_types.append(nonanimal[label])
        else:
            sn = species_map.get(label, label)
            obs_types.append("animal")
            sci_names.append(sn if sn else label)

    unique_sites = sorted(set(sites))
    pd.DataFrame({
        "deploymentID": unique_sites,
        "locationID":   unique_sites,
        "locationName": unique_sites,
    }).to_csv(out_dir / "deployments.csv", index=False)
    pd.DataFrame({
        "mediaID":      media_ids,
        "deploymentID": list(sites),
        "timestamp":    list(timestamps),
        "filePath":     list(paths),
    }).to_csv(out_dir / "media.csv", index=False)
    pd.DataFrame({
        "observationID":             obs_ids,
        "deploymentID":              list(sites),
        "mediaID":                   media_ids,
        "observationLevel":          "media",
        "observationType":           obs_types,
        "scientificName":            sci_names,
        "classificationProbability": list(scores),
        "classificationMethod":      "machine",
        "classifiedBy":              "custom",
        "classificationTimestamp":   None,
    }).to_csv(out_dir / "observations.csv", index=False)
    return out_dir


# ─── Build candidate manifest ─────────────────────────────────────────────────

def build_candidates(
    dep: pd.DataFrame,
    med: pd.DataFrame,
    obs: pd.DataFrame,
    target_species: list[str],
    study_start: date,
    study_end: date,
    occasion_days: int,
    total_iterations: int,
    gap_seconds: int = 60,
    include_burst_context: bool = False,
    min_score: float = 0.0,
) -> pd.DataFrame:
    """Build the verification candidate manifest from CamtrapDP tables.

    Filters observations to ``target_species`` within the study window, demotes
    (excludes) any individual frame whose own classification probability falls
    below ``min_score`` -- mirroring ``to_camtrapdp()``'s per-frame threshold --
    assigns each surviving frame to a sampling occasion (fixed-width breaks of
    ``occasion_days``), groups frames into detection events (bursts separated by more
    than ``gap_seconds``), and ranks bursts by maximum classification
    probability within each site × occasion × species cell (rank 1 = highest
    confidence).

    When ``include_burst_context`` is True, neighbouring frames from ``media.csv``
    (same deployment, within ``gap_seconds`` of each burst boundary) are appended
    as context-only rows (``is_context=True``). Context frames share the
    ``site_occasion_key``, ``burst_id`` and ``rank`` of their parent burst but
    are never used as the representative observation for decisions.

    Args:
        dep: Deployments DataFrame (from ``load_camtrapdp``).
        med: Media DataFrame (from ``load_camtrapdp``).
        obs: Observations DataFrame (from ``load_camtrapdp``).
        target_species: Scientific names to include.
        study_start: First date of the study period (inclusive).
        study_end: Last date of the study period (inclusive).
        occasion_days: Width of each sampling occasion in days.
        total_iterations: Maximum number of bursts to keep per cell (caps rank).
        gap_seconds: Maximum gap in seconds between frames of the same burst.
            Defaults to 60.
        include_burst_context: If True, adds neighbouring frames around each burst
            as context (``is_context=True``). Defaults to False.
        min_score: Minimum classification probability an individual frame must
            reach to remain a candidate. A frame with no score at all is never
            demoted -- only a known score below this excludes it. Defaults to
            0.0 (no filtering).

    Returns:
        DataFrame with one row per candidate frame, including columns
        ``site_occasion_key``, ``rank``, ``burst_id``, ``burst_seq``,
        ``observationID``, ``mediaID``, ``filePath``, ``fileName``, ``classificationProbability``,
        ``scientificName``, ``siteID``, ``occasion``, ``species_safe``,
        ``ts``, ``timestamp_display`` and ``is_context``.
        Returns an empty DataFrame if no candidates match the filters.
    """
    site_col = detect_site_col(dep)

    med = med.copy()
    med["ts"] = pd.to_datetime(
        med["timestamp"].apply(normalise_ts), errors="coerce", utc=False
    )
    if "fileName" not in med.columns:
        med["fileName"] = med["filePath"].apply(
            lambda x: Path(str(x)).name if pd.notna(x) else ""
        )

    target_obs = obs[
        (obs["observationLevel"] == "media")
        & (obs["observationType"] == "animal")
        & (obs["scientificName"].isin(target_species))
    ].copy()

    # Collapse multiple observation rows for the same (mediaID, scientificName)
    # -- e.g. several bounding boxes for the same species in one frame -- to a
    # single representative row (highest classificationProbability), mirroring
    # R's prepare_camtrapdp_dir(). Otherwise the same photo would show up
    # twice as separate candidates.
    target_obs["_prob_sort"] = pd.to_numeric(
        target_obs["classificationProbability"], errors="coerce"
    ).fillna(-1)
    target_obs = (
        target_obs.sort_values("_prob_sort", ascending=False)
        .drop_duplicates(subset=["mediaID", "scientificName"], keep="first")
        .drop(columns="_prob_sort")
    )

    # Demote frames whose own classification score falls below min_score, mirroring
    # to_camtrapdp()'s per-frame threshold: a frame with no score at all is never
    # demoted (only a known low score excludes it), and this runs before burst
    # grouping, so a demoted frame no longer counts toward a burst's gap-based grouping.
    if min_score > 0:
        target_prob = pd.to_numeric(target_obs["classificationProbability"], errors="coerce")
        target_obs = target_obs[~(target_prob.notna() & (target_prob < min_score))]

    joined = (
        target_obs
        .merge(med[["mediaID", "filePath", "fileName", "ts"]], on="mediaID", how="left")
        .merge(
            dep[["deploymentID", site_col]].rename(columns={site_col: "siteID"}),
            on="deploymentID", how="left",
        )
    )

    joined = joined[
        joined["ts"].notna()
        & (joined["ts"].dt.date >= study_start)
        & (joined["ts"].dt.date <= study_end)
    ].copy()

    if joined.empty:
        return pd.DataFrame()

    # Build occasion breaks
    breaks = []
    d = study_start
    while d <= study_end + timedelta(days=1):
        breaks.append(d)
        d += timedelta(days=occasion_days)
    n_occ = len(breaks) - 1

    def assign_occ(ts: pd.Timestamp) -> int:
        dt = ts.date()
        for i in range(len(breaks) - 1):
            if breaks[i] <= dt < breaks[i + 1]:
                return i + 1
        return n_occ if dt == breaks[-1] else -1

    joined["occasion"] = joined["ts"].apply(assign_occ)
    joined = joined[joined["occasion"] >= 1].copy()

    joined["species_safe"] = joined["scientificName"].apply(sanitize)
    joined["site_occasion_key"] = (
        joined["siteID"].astype(str)
        + "_occ" + joined["occasion"].astype(str)
        + "_" + joined["species_safe"]
    )
    joined["prob"] = pd.to_numeric(
        joined["classificationProbability"], errors="coerce"
    ).fillna(0)
    # Tiebreaker for same-timestamp burst frames: some exports (e.g. Wildlife
    # Insights) only carry second-resolution timestamps, so several frames of
    # the same burst can tie; a trailing numeric suffix in the file name
    # (e.g. "..._1.JPEG" -> 1) recovers true capture order. Matches the
    # reference R tool; unparseable/absent suffixes sort last.
    joined["capture_seq"] = pd.to_numeric(
        joined["filePath"].astype(str).str.extract(r"_(\d+)\.[^/]*$")[0],
        errors="coerce",
    )
    joined = joined.sort_values(
        ["site_occasion_key", "ts", "capture_seq"], na_position="last"
    )

    # Assign burst IDs (consecutive frames within gap_seconds form one burst)
    records = []
    for _, group in joined.groupby("site_occasion_key", sort=False):
        group = group.copy().reset_index(drop=True)
        burst_id = 0
        bids = [0]
        for i in range(1, len(group)):
            prev, curr = group["ts"].iloc[i - 1], group["ts"].iloc[i]
            if pd.isna(prev) or pd.isna(curr) or (curr - prev).total_seconds() > gap_seconds:
                burst_id += 1
            bids.append(burst_id)
        group["burst_id"] = bids
        records.append(group)

    if not records:
        return pd.DataFrame()

    joined = pd.concat(records, ignore_index=True)

    # Rank bursts by max prob within each cell (highest prob = rank 1)
    burst_max = (
        joined.groupby(["site_occasion_key", "burst_id"])["prob"]
        .max()
        .reset_index(name="burst_max_prob")
    )
    burst_max["rank"] = (
        burst_max.groupby("site_occasion_key")["burst_max_prob"]
        .rank(method="first", ascending=False)
        .astype(int)
    )

    joined = joined.merge(burst_max[["site_occasion_key", "burst_id", "rank"]],
                          on=["site_occasion_key", "burst_id"])
    joined["burst_seq"] = (
        joined.groupby(["site_occasion_key", "burst_id"]).cumcount() + 1
    )

    candidates = joined[joined["rank"] <= total_iterations].copy()
    candidates["timestamp_display"] = candidates["ts"].dt.strftime("%Y-%m-%d %H:%M")
    candidates["is_context"] = False

    if include_burst_context and not candidates.empty:
        candidate_media_ids = set(candidates["mediaID"].astype(str))
        context_rows: list[dict] = []

        for (key, burst_id_val), burst in candidates.groupby(
            ["site_occasion_key", "burst_id"], sort=False
        ):
            dep_id = str(burst["deploymentID"].iloc[0])
            # Pad by gap_seconds on each side so a burst with a single detection
            # (min == max) still gets a real window instead of collapsing to a
            # zero-width instant, while frames from adjacent visits (further away
            # than gap_seconds) stay excluded. Matches the reference R tool.
            pad = pd.Timedelta(seconds=gap_seconds)
            t0 = burst["ts"].min() - pad
            t1 = burst["ts"].max() + pad

            neighbors = med[
                (med["deploymentID"].astype(str) == dep_id)
                & med["ts"].notna()
                & (med["ts"] >= t0)
                & (med["ts"] <= t1)
                & (~med["mediaID"].astype(str).isin(candidate_media_ids))
            ]

            for _, row in neighbors.iterrows():
                ts_val: pd.Timestamp = row["ts"]
                context_rows.append({
                    "site_occasion_key":         key,
                    "rank":                      int(burst["rank"].iloc[0]),
                    "burst_id":                  int(burst_id_val),
                    "burst_seq":                 None,
                    "observationID":             f"ctx_{row['mediaID']}",
                    "mediaID":                   str(row["mediaID"]),
                    "filePath":                  str(row["filePath"]),
                    "fileName":                  str(row["fileName"]),
                    "classificationProbability": None,
                    "scientificName":            burst["scientificName"].iloc[0],
                    "deploymentID":              dep_id,
                    "siteID":                    str(burst["siteID"].iloc[0]),
                    "occasion":                  int(burst["occasion"].iloc[0]),
                    "species_safe":              burst["species_safe"].iloc[0],
                    "ts":                        ts_val,
                    "timestamp_display":         ts_val.strftime("%Y-%m-%d %H:%M") if pd.notna(ts_val) else "",
                    "is_context":                True,
                })

        if context_rows:
            ctx_df = pd.DataFrame(context_rows)
            candidates = pd.concat([candidates, ctx_df], ignore_index=True)
            candidates = candidates.sort_values(
                ["site_occasion_key", "burst_id", "ts"]
            ).reset_index(drop=True)

    return candidates[[
        "site_occasion_key", "rank", "burst_id", "burst_seq",
        "observationID", "mediaID", "filePath", "fileName",
        "classificationProbability", "scientificName", "deploymentID",
        "siteID", "occasion", "species_safe", "ts", "timestamp_display",
        "is_context",
    ]]


# ─── Decision persistence ─────────────────────────────────────────────────────

def load_all_decisions(decisions_dir: Path) -> pd.DataFrame:
    """Concatenate all ``decisions_*.csv`` files from the decisions directory.

    Args:
        decisions_dir: Directory containing per-species, per-round decision CSVs.

    Returns:
        Single DataFrame with all decisions, or an empty DataFrame with the
        expected columns if no files exist.
    """
    files = list(decisions_dir.glob("decisions_*.csv"))
    if not files:
        return pd.DataFrame(columns=[
            "observationID", "site_occasion_key", "mediaID",
            "scientificName", "siteID", "occasion",
        ])
    return pd.concat([pd.read_csv(f, dtype=str) for f in files], ignore_index=True)


def confirmed_keys_set(decisions_dir: Path) -> set[str]:
    """Return the set of confirmed ``site_occasion_key`` values across all decision files.

    Args:
        decisions_dir: Directory containing decision CSVs.

    Returns:
        Set of confirmed keys, empty if no decisions exist.
    """
    dec = load_all_decisions(decisions_dir)
    if dec.empty:
        return set()
    return set(dec["site_occasion_key"].dropna().unique())


def save_decisions(
    decisions_dir: Path,
    candidates: pd.DataFrame,
    species_safe: str,
    iteration: int,
    confirmed_ids: list[str],
) -> pd.DataFrame:
    """Persist confirmed observation IDs to ``decisions_{species_safe}_iter{N}.csv``.

    Writes an empty file when ``confirmed_ids`` is empty so the round is
    recorded and the species does not regress to a previous state.

    Args:
        decisions_dir: Directory where decision CSVs are stored.
        candidates: Full candidate manifest (used to look up metadata by ID).
        species_safe: Sanitized species name used in the filename.
        iteration: Round number used in the filename.
        confirmed_ids: List of ``observationID`` values confirmed by the expert.

    Returns:
        DataFrame of the confirmed rows that was written to disk.
    """
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_dir / f"decisions_{species_safe}_iter{iteration}.csv"
    cols = ["observationID", "site_occasion_key", "mediaID",
            "scientificName", "siteID", "occasion"]
    if not confirmed_ids:
        df = candidates.iloc[0:0][cols]
    else:
        df = candidates[candidates["observationID"].isin(confirmed_ids)][cols]
    df.to_csv(path, index=False)
    return df


# ─── Species stats for index page ─────────────────────────────────────────────

def species_stats(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    total_iterations: int,
) -> list[dict]:
    """Compute per-species progress statistics for the index page.

    A cell is considered *resolved* when it is confirmed OR all of its available
    ranks have been reviewed (``max_rank <= rounds_done``). ``n_resolved`` drives
    the progress bar and the "Completo" badge.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        total_iterations: Maximum number of rounds configured for the session.

    Returns:
        List of dicts, one per species, with keys ``species_name``,
        ``species_safe``, ``n_total_combos``, ``n_confirmed_combos``,
        ``n_resolved`` and ``current_iteration``.
    """
    conf_keys = confirmed_keys_set(decisions_dir)

    iter_by_sp: dict[str, int] = {}
    for f in decisions_dir.glob("*.csv"):
        m = re.match(r"decisions_(.+)_iter(\d+)\.csv", f.name)
        if m:
            sp, it = m.group(1), int(m.group(2))
            iter_by_sp[sp] = max(iter_by_sp.get(sp, 0), it)

    result = []
    for sp_safe, grp in candidates.groupby("species_safe"):
        sp_name = grp["scientificName"].iloc[0]
        all_keys = set(grp["site_occasion_key"].unique())
        max_rank = grp.groupby("site_occasion_key")["rank"].max()
        R = iter_by_sp.get(str(sp_safe), 0)
        resolved = sum(
            1 for k in all_keys
            if k in conf_keys or max_rank.get(k, 0) <= R
        )
        result.append({
            "species_name": sp_name,
            "species_safe": str(sp_safe),
            "n_total_combos": len(all_keys),
            "n_confirmed_combos": sum(1 for k in all_keys if k in conf_keys),
            "n_resolved": resolved,
            "current_iteration": R + 1,
        })
    return result


# ─── Events for gallery ───────────────────────────────────────────────────────

def get_events(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    rejected_media: set[str],
    species_safe: str,
    iteration: int,
    image_base_dir: str = "",
    fallback_base: Path = Path("."),
    flat_search: bool = False,
) -> list[dict]:
    """Return pending gallery events for a species in a given verification round.

    Only returns cells at the requested rank that are not yet confirmed and whose
    media have not been manually rejected. Each event carries all frames of the
    representative burst plus metadata for the UI card.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        rejected_media: Set of ``mediaID`` values excluded from the gallery.
        species_safe: Sanitized species name to filter by.
        iteration: Round number (equals the burst rank to show).
        image_base_dir: User-supplied image root, forwarded to
            :func:`gallery_frame_img_url` so a remote ``filePath`` already
            downloaded locally is served from disk instead of the network.
        fallback_base: Base directory for resolving relative ``filePath``
            values when ``image_base_dir`` is not set.
        flat_search: If True, also search ``image_base_dir`` recursively by
            ``fileName`` when the structured path misses.

    Returns:
        List of event dicts with keys ``key``, ``siteId``, ``occasion``,
        ``rank``, ``totalSeqs``, ``repObsId``, ``maxProb`` and ``frames``
        (list of frame dicts with ``obsId``, ``mediaId``, ``img``, ``ts``,
        ``prob``).
    """
    conf_keys = confirmed_keys_set(decisions_dir)

    sp_cands = candidates[
        (candidates["species_safe"] == species_safe)
        & (candidates["rank"] == iteration)
        & (~candidates["site_occasion_key"].isin(conf_keys))
        & (~candidates["mediaID"].isin(rejected_media))
    ].copy()

    # Total de secuencias disponibles por período (sin filtrar por ronda)
    all_sp = candidates[candidates["species_safe"] == species_safe]
    total_seqs_by_key = all_sp.groupby("site_occasion_key")["rank"].max().to_dict()

    events = []
    for key, group in sp_cands.sort_values(["burst_id", "ts"]).groupby(
        "site_occasion_key", sort=False
    ):
        group = group.sort_values(["burst_id", "ts"])

        # Context frames (is_context=True) are not used for repObsId / maxProb
        is_ctx = group.get("is_context", pd.Series(False, index=group.index)).fillna(False)
        decision_rows = group[~is_ctx]

        prob_col = pd.to_numeric(
            decision_rows["classificationProbability"], errors="coerce"
        ).fillna(0)
        rep_idx = prob_col.idxmax()
        rep_obs = decision_rows.loc[rep_idx, "observationID"]
        max_prob = float(prob_col.max())

        frames = []
        for _, row in group.iterrows():
            fp = str(row["filePath"])
            img_url = gallery_frame_img_url(
                fp, str(row["mediaID"]), str(row.get("deploymentID", "")), str(row.get("fileName", "")),
                image_base_dir, fallback_base, flat_search=flat_search,
            )
            row_is_ctx = bool(row.get("is_context", False))
            row_prob = pd.to_numeric(row.get("classificationProbability"), errors="coerce")
            frames.append({
                "obsId":     row["observationID"],
                "mediaId":   str(row["mediaID"]),
                "img":       img_url,
                "ts":        row["timestamp_display"] if pd.notna(row.get("timestamp_display")) else "",
                "prob":      round(float(row_prob), 3) if pd.notna(row_prob) else None,
                "isContext": row_is_ctx,
            })

        events.append({
            "key":       key,
            "siteId":    str(group["siteID"].iloc[0]),
            "occasion":  int(group["occasion"].iloc[0]),
            "rank":      int(group["rank"].iloc[0]),
            "totalSeqs": int(total_seqs_by_key.get(key, 1)),
            "repObsId":  rep_obs,
            "maxProb":   max_prob,
            "frames":    frames,
        })

    return events


def get_review_events(
    species_cands: pd.DataFrame,
    decisions_dir: Path,
    image_base_dir: str = "",
    fallback_base: Path = Path("."),
    flat_search: bool = False,
) -> list[dict]:
    """Return all cells for a completed species with their decision status.

    Uses rank-1 frames for display (highest-confidence burst per cell). Each
    event includes a ``status`` field so the review screen can pre-mark cards
    as confirmed or not confirmed without reloading decisions separately.

    Used by the locked review screen so the expert can audit or correct
    decisions without starting a new session.

    Args:
        species_cands: Candidate manifest already filtered to a single species.
        decisions_dir: Directory containing decision CSVs.
        image_base_dir: User-supplied image root, forwarded to
            :func:`gallery_frame_img_url` so a remote ``filePath`` already
            downloaded locally is served from disk instead of the network.
        fallback_base: Base directory for resolving relative ``filePath``
            values when ``image_base_dir`` is not set.
        flat_search: If True, also search ``image_base_dir`` recursively by
            ``fileName`` when the structured path misses.

    Returns:
        List of event dicts (same structure as :func:`get_events`) with an
        additional ``status`` key: ``'confirmed'`` or ``'not_confirmed'``.
        Sorted by ``siteId`` then ``occasion``.
    """
    conf_keys = confirmed_keys_set(decisions_dir)
    rank1 = species_cands[species_cands["rank"] == 1].copy()
    total_seqs_by_key = species_cands.groupby("site_occasion_key")["rank"].max().to_dict()

    events = []
    for key, group in rank1.sort_values(["burst_id", "ts"]).groupby(
        "site_occasion_key", sort=False
    ):
        group = group.sort_values(["burst_id", "ts"])

        is_ctx = group.get("is_context", pd.Series(False, index=group.index)).fillna(False)
        decision_rows = group[~is_ctx]

        prob_col = pd.to_numeric(
            decision_rows["classificationProbability"], errors="coerce"
        ).fillna(0)
        rep_idx = prob_col.idxmax()
        rep_obs = decision_rows.loc[rep_idx, "observationID"]
        max_prob = float(prob_col.max())

        frames = []
        for _, row in group.iterrows():
            fp = str(row["filePath"])
            img_url = gallery_frame_img_url(
                fp, str(row["mediaID"]), str(row.get("deploymentID", "")), str(row.get("fileName", "")),
                image_base_dir, fallback_base, flat_search=flat_search,
            )
            row_is_ctx = bool(row.get("is_context", False))
            row_prob = pd.to_numeric(row.get("classificationProbability"), errors="coerce")
            frames.append({
                "obsId":     row["observationID"],
                "mediaId":   str(row["mediaID"]),
                "img":       img_url,
                "ts":        row["timestamp_display"] if pd.notna(row.get("timestamp_display")) else "",
                "prob":      round(float(row_prob), 3) if pd.notna(row_prob) else None,
                "isContext": row_is_ctx,
            })

        events.append({
            "key": key,
            "siteId": str(group["siteID"].iloc[0]),
            "occasion": int(group["occasion"].iloc[0]),
            "rank": 1,
            "totalSeqs": int(total_seqs_by_key.get(key, 1)),
            "repObsId": rep_obs,
            "maxProb": max_prob,
            "frames": frames,
            "status": "confirmed" if key in conf_keys else "not_confirmed",
        })

    events.sort(key=lambda e: (e["siteId"], e["occasion"]))
    return events


# ─── Export verified CamtrapDP ────────────────────────────────────────────────

def export_verified_camtrapdp(
    camtrap_dir: Path,
    out_dir: Path,
    decisions_dir: Path,
    rejected_media: set,
    classified_by_label: str = "expert_review",
    extended_confirmation: bool = False,
    candidates: Optional["pd.DataFrame"] = None,
) -> None:
    """Write ``camtrap_dp_verified/``, replicating R's ``update_metadata()`` + ``export_results()``.

    ``deployments.csv`` and ``media.csv`` are copied unchanged, as is
    ``datapackage.json`` when the source package has one (only the values in
    ``observations.csv`` change, not its schema, so the original descriptor
    still describes the exported package correctly). When the source has no
    ``datapackage.json`` -- e.g. it was converted from a DeepFaune/generic CSV,
    or it came from Trapper/elsewhere without one -- a best-effort default is
    generated instead via ``generate_default_datapackage()``, so the exported
    package is never missing the file outright; callers can check
    ``datapackage.json``'s ``wildintelGenerated.fabricatedFields`` to warn the
    user which parts are placeholders. In ``observations.csv`` the
    representative observation of each confirmed detection event is updated:
    ``classificationMethod='human'``,
    ``classificationProbability=1.0``, ``classifiedBy``, and
    ``classificationTimestamp`` (UTC). When ``extended_confirmation=True`` all
    observations that belong to the same burst as each confirmed representative
    are updated too. No ``verificationStatus`` column is added.

    Args:
        camtrap_dir: Source CamtrapDP directory.
        out_dir: Destination directory (created if absent).
        decisions_dir: Directory containing decision CSVs.
        rejected_media: Set of manually rejected ``mediaID`` values (not used
            for the export itself, kept for API symmetry).
        classified_by_label: Value written to ``classifiedBy`` on confirmed
            observations. Defaults to ``'expert_review'``.
        extended_confirmation: When True, all observations in each confirmed
            burst (not just the representative) are updated. Requires
            ``candidates``.
        candidates: Candidate manifest DataFrame (needed when
            ``extended_confirmation=True``).
    """
    import shutil
    from datetime import datetime, timezone

    out_dir.mkdir(parents=True, exist_ok=True)

    # deployments y media se copian sin cambios, bajo su nombre real (para no
    # romper el path declarado en datapackage.json si éste se copia tal cual)
    for src in (
        resolve_camtrapdp_resource(camtrap_dir, "deployments"),
        resolve_camtrapdp_resource(camtrap_dir, "media"),
    ):
        if src is not None:
            shutil.copy2(src, out_dir / src.name)

    # Cargar deployments/media (para el datapackage.json) y observaciones originales
    dep, med, obs = load_camtrapdp(camtrap_dir)

    # IDs de observaciones confirmadas (repObsId de cada decisión)
    confirmed_ids: set[str] = set()
    if decisions_dir.exists():
        for f in decisions_dir.glob("decisions_*_iter*.csv"):
            df = pd.read_csv(f, dtype=str)
            if "observationID" in df.columns:
                confirmed_ids.update(df["observationID"].dropna().tolist())

    # Modo extendido: expande al resto de observaciones del mismo burst
    if extended_confirmation and candidates is not None and confirmed_ids:
        real_cands = candidates[~candidates.get("is_context", pd.Series(False, index=candidates.index)).fillna(False)]
        rep_rows = real_cands[real_cands["observationID"].isin(confirmed_ids)]
        burst_keys = rep_rows[["site_occasion_key", "burst_id"]].drop_duplicates()
        burst_mates = real_cands.merge(burst_keys, on=["site_occasion_key", "burst_id"])
        confirmed_ids = set(burst_mates["observationID"].dropna().tolist())

    if confirmed_ids:
        # build_candidates() collapses duplicate observation rows for the same
        # (mediaID, scientificName) to one representative, so confirmed_ids
        # only names that representative's observationID. Expand back to every
        # sibling row sharing that (mediaID, scientificName) here, against the
        # original observations.csv, so all of them get marked confirmed too.
        conf_rows = obs[obs["observationID"].isin(confirmed_ids)]
        conf_pairs = set(zip(conf_rows["mediaID"], conf_rows["scientificName"]))
        pairs = pd.Series(list(zip(obs["mediaID"], obs["scientificName"])), index=obs.index)
        mask = pairs.isin(conf_pairs)

        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        obs.loc[mask, "classificationMethod"] = "human"
        obs.loc[mask, "classificationProbability"] = "1.0"
        obs.loc[mask, "classifiedBy"] = classified_by_label
        obs.loc[mask, "classificationTimestamp"] = now_ts

    obs.to_csv(out_dir / "observations.csv", index=False)

    dp_src = find_datapackage(camtrap_dir)
    if dp_src is not None:
        shutil.copy2(dp_src, out_dir / "datapackage.json")
    else:
        descriptor = generate_default_datapackage(dep, med, obs)
        (out_dir / "datapackage.json").write_text(json.dumps(descriptor, indent=2))


# ─── Occasion windows helper ──────────────────────────────────────────────────

def _occasion_windows(
    study_start: date, study_end: date, occasion_days: int
) -> list[tuple[date, date]]:
    """Split the study period into consecutive fixed-width windows.

    Args:
        study_start: First day of the study period.
        study_end: Last day of the study period (inclusive).
        occasion_days: Width of each window in days.

    Returns:
        List of ``(lo, hi)`` date tuples. The last window is clipped to
        ``study_end`` so it may be shorter than ``occasion_days``.
    """
    windows: list[tuple[date, date]] = []
    d = study_start
    while d <= study_end:
        hi = min(d + timedelta(days=occasion_days - 1), study_end)
        windows.append((d, hi))
        d += timedelta(days=occasion_days)
    return windows


# ─── Occupancy inputs ─────────────────────────────────────────────────────────

def build_occupancy_inputs(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    config: dict,
    out_dir: Path,
) -> None:
    """Generate occupancy-model input files, replicating R's ``build_occupancy_inputs()``.

    Outputs written to ``out_dir``:

    * ``camera_operation.csv`` — days active per site × occasion, computed from
      ``deploymentStart``/``deploymentEnd`` in ``deployments.csv`` when available;
      falls back to the full occasion length otherwise.
    * ``dethist_naive_<sp>.csv`` — 1/0/NA detection history trusting the classifier.
    * ``dethist_verified_<sp>.csv`` — 1/0/NA detection history using only
      human-confirmed detections.
    * ``verification_summary.csv`` — per-species summary with ``psi_obs`` naive
      vs. verified.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        config: Session configuration dict (requires keys ``study_start``,
            ``study_end``, ``occasion_days``, ``target_species``,
            ``camtrap_dir``).
        out_dir: Destination directory (created if absent).
    """
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)

    study_start    = date.fromisoformat(config["study_start"])
    study_end      = date.fromisoformat(config["study_end"])
    occasion_days  = int(config["occasion_days"])
    target_species = config["target_species"]

    windows   = _occasion_windows(study_start, study_end, occasion_days)
    n_occ     = len(windows)
    occ_cols  = [f"occ{j + 1}" for j in range(n_occ)]

    # Universo de sitios: todo despliegue CLASIFICADO (presente en deployments.csv),
    # incluyendo cámaras sin ninguna detección del target (ceros verdaderos). Usar
    # solo los siteID de candidates infla psi_obs porque excluye esas cámaras.
    dep_path = resolve_camtrapdp_resource(Path(config["camtrap_dir"]), "deployments")
    if dep_path is not None:
        dep = pd.read_csv(dep_path, dtype=str)
        site_col = detect_site_col(dep)
        sites = sorted(dep[site_col].astype(str).unique())
    else:
        sites = sorted(candidates["siteID"].astype(str).unique())
    n_sites   = len(sites)

    # ── Camera operation matrix (días activos por sitio × ocasión) ──────────
    op = np.zeros((n_sites, n_occ), dtype=int)

    activity: dict[str, list[tuple[date, date]]] = {}
    if dep_path is not None:
        if "deploymentStart" in dep.columns and "deploymentEnd" in dep.columns:
            for _, row in dep.iterrows():
                s = str(row[site_col])
                try:
                    s_d = date.fromisoformat(str(row["deploymentStart"])[:10])
                    e_d = date.fromisoformat(str(row["deploymentEnd"])[:10])
                    activity.setdefault(s, []).append((s_d, e_d))
                except Exception:
                    pass

    for i, site in enumerate(sites):
        periods = activity.get(site, [])
        for j, (lo, hi) in enumerate(windows):
            full = (hi - lo).days + 1
            if not periods:
                op[i, j] = full
            else:
                active = 0
                for ps, pe in periods:
                    a = max(lo, ps)
                    b = min(hi, pe)
                    if b >= a:
                        active += (b - a).days + 1
                op[i, j] = min(active, full)

    op_df = pd.DataFrame(op, columns=occ_cols)
    op_df.insert(0, "siteID", sites)
    op_df.to_csv(out_dir / "camera_operation.csv", index=False)

    # ── Cargar decisiones ────────────────────────────────────────────────────
    dec = load_all_decisions(decisions_dir) if decisions_dir.exists() else pd.DataFrame(
        columns=["observationID", "site_occasion_key", "scientificName"]
    )

    # ── Historiales de detección por especie ─────────────────────────────────
    summary_rows = []

    for sp in target_species:
        sp_safe   = sanitize(sp)
        sp_cands  = candidates[candidates["scientificName"] == sp]
        naive_keys = set(sp_cands["site_occasion_key"].unique())

        if not dec.empty and "scientificName" in dec.columns:
            verif_keys: set[str] = set(
                dec[dec["scientificName"] == sp]["site_occasion_key"].dropna()
            )
        else:
            verif_keys = {k for k in (dec["site_occasion_key"].dropna() if not dec.empty else [])
                          if k.endswith(f"_{sp_safe}")}

        yN = np.full((n_sites, n_occ), np.nan)
        yV = np.full((n_sites, n_occ), np.nan)
        for i, site in enumerate(sites):
            for j in range(n_occ):
                if op[i, j] == 0:
                    continue
                key = f"{site}_occ{j + 1}_{sp_safe}"
                yN[i, j] = 1.0 if key in naive_keys else 0.0
                yV[i, j] = 1.0 if key in verif_keys else 0.0

        def _to_df(y: "np.ndarray") -> pd.DataFrame:
            rows = []
            for si, sname in enumerate(sites):
                r: dict = {"siteID": sname}
                for j, col in enumerate(occ_cols):
                    v = y[si, j]
                    r[col] = "" if np.isnan(v) else int(v)
                rows.append(r)
            return pd.DataFrame(rows)

        _to_df(yN).to_csv(out_dir / f"dethist_naive_{sp_safe}.csv", index=False)
        _to_df(yV).to_csv(out_dir / f"dethist_verified_{sp_safe}.csv", index=False)

        naive_det = int(np.nansum(yN == 1))
        verif_det = int(np.nansum(yV == 1))
        fp_cells  = int(np.nansum((yN == 1) & (yV == 0)))
        psi_naive = float(np.mean(
            [any(yN[i, j] == 1 for j in range(n_occ) if not np.isnan(yN[i, j]))
             for i in range(n_sites)]
        )) if n_sites else 0.0
        psi_verif = float(np.mean(
            [any(yV[i, j] == 1 for j in range(n_occ) if not np.isnan(yV[i, j]))
             for i in range(n_sites)]
        )) if n_sites else 0.0

        summary_rows.append({
            "species":              sp,
            "candidate_frames":     len(sp_cands),
            "candidate_combos":     len(naive_keys),
            "naive_detections":     naive_det,
            "verified_detections":  verif_det,
            "false_positive_cells": fp_cells,
            "psi_obs_naive":        round(psi_naive, 3),
            "psi_obs_verified":     round(psi_verif, 3),
        })

    pd.DataFrame(summary_rows).to_csv(out_dir / "verification_summary.csv", index=False)


# ─── Review effort ────────────────────────────────────────────────────────────

def build_review_effort(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    config: dict,
    out_dir: Path,
) -> None:
    """Generate ``review_effort.csv``, replicating R's ``review_effort()``.

    Measures how many detection events the expert actually inspected:

    * **Confirmed cells**: cost = rank of the confirmed detection event (expert stopped
      at the first "yes").
    * **Rejected cells**: cost = maximum rank available (expert exhausted all
      detection events without confirming).

    Also reports percentages relative to the full candidate set and the original
    classified archive.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        config: Session configuration dict (requires keys ``camtrap_dir`` and
            ``target_species``).
        out_dir: Destination directory (created if absent).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    dec = load_all_decisions(decisions_dir) if decisions_dir.exists() else pd.DataFrame()

    conf_obs_by_key: dict[str, set[str]] = {}
    if not dec.empty and "site_occasion_key" in dec.columns:
        for key, grp in dec.groupby("site_occasion_key"):
            conf_obs_by_key[str(key)] = set(grp["observationID"].dropna())

    keys = candidates["site_occasion_key"].unique()
    n_conf = 0; n_rej = 0; ins_conf = 0; ins_rej = 0

    for key in keys:
        sub  = candidates[candidates["site_occasion_key"] == key]
        conf = conf_obs_by_key.get(str(key), set())
        if conf:
            n_conf += 1
            confirmed_ranks = sub[sub["observationID"].isin(conf)]["rank"]
            ins_conf += int(confirmed_ranks.min()) if not confirmed_ranks.empty else 1
        else:
            n_rej += 1
            ins_rej += int(sub["rank"].max())

    inspected = ins_conf + ins_rej
    n_candidates = len(candidates)
    n_cells = len(keys)

    total_media: Optional[int] = None
    target_assigned: Optional[int] = None
    obs_path = resolve_camtrapdp_resource(Path(config["camtrap_dir"]), "observations")
    if obs_path is not None:
        obs_all = pd.read_csv(obs_path, dtype=str)
        total_media = len(obs_all)
        target_assigned = int(
            obs_all["scientificName"].isin(config["target_species"]).sum()
        )

    def pct(x: int, d: Optional[int]) -> Optional[float]:
        return round(100 * x / d, 1) if d else None

    row = {
        "candidate_cells":         n_cells,
        "confirmed_cells":         n_conf,
        "rejected_cells":          n_rej,
        "candidate_images":        n_candidates,
        "images_inspected":        inspected,
        "inspected_in_confirmed":  ins_conf,
        "inspected_in_rejected":   ins_rej,
        "mean_per_confirmed":      round(ins_conf / n_conf, 2) if n_conf else None,
        "mean_per_rejected":       round(ins_rej  / n_rej,  2) if n_rej  else None,
        "target_assigned_images":  target_assigned,
        "total_classified_images": total_media,
        "pct_of_candidates":       pct(inspected, n_candidates),
        "pct_of_target_assigned":  pct(inspected, target_assigned),
        "pct_of_archive":          pct(inspected, total_media),
    }
    pd.DataFrame([row]).to_csv(out_dir / "review_effort.csv", index=False)
