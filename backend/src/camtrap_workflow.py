"""
CamTrap Verify — backend workflow.

Port of the R verification pipeline to Python/pandas. Handles loading a
CamtrapDP dataset, building the ranked candidate manifest, persisting expert
decisions, and generating the verified CamtrapDP and occupancy-model inputs.
"""
import json
import logging
import math
import os
import re
from datetime import date, datetime, timedelta
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


# Columns the review workflow needs from the two big tables. Creating a session reads only these
# (instead of every column as ``str``), which cuts load time and memory on large exports (e.g.
# 1.4 M observations / 550 k media rows). The verified CamtrapDP is written from a full read.
WORKFLOW_MEDIA_COLUMNS = frozenset(("mediaID", "deploymentID", "timestamp", "filePath", "fileName"))
WORKFLOW_OBS_COLUMNS = frozenset((
    "observationID", "deploymentID", "mediaID", "observationLevel", "observationType", "scientificName",
    "classificationProbability", "observationTags", "bboxX", "bboxY", "bboxWidth", "bboxHeight",
))


def load_camtrapdp(
    camtrap_dir: Path, minimal: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
        minimal: Read only the columns of ``media.csv`` and ``observations.csv`` that building the
            candidates needs (:data:`WORKFLOW_MEDIA_COLUMNS`, :data:`WORKFLOW_OBS_COLUMNS`). The
            default reads everything, as the verified export and the converters need.

    Returns:
        Tuple of ``(deployments, media, observations)`` DataFrames.
    """
    def _load(name: str, wanted: Optional[frozenset] = None) -> pd.DataFrame:
        path = resolve_camtrapdp_resource(camtrap_dir, name)
        if path is None:
            path = camtrap_dir / f"{name}.csv"  # let pandas raise a familiar error
        if wanted is None:
            return pd.read_csv(path, dtype=str)
        return pd.read_csv(path, dtype=str, usecols=lambda c: c in wanted)

    dep = _load("deployments")
    med = _load("media", WORKFLOW_MEDIA_COLUMNS if minimal else None)
    obs = _load("observations", WORKFLOW_OBS_COLUMNS if minimal else None)
    if "fileName" not in med.columns:
        med["fileName"] = med["filePath"].apply(
            lambda x: Path(str(x)).name if pd.notna(x) else ""
        )
    return dep, med, dedupe_observation_ids(obs)


# Column that keeps the original ``observationID`` when it had to be made unique.
ORIG_OBSERVATION_ID = "_observationID_original"


def dedupe_observation_ids(obs: pd.DataFrame) -> pd.DataFrame:
    """Make ``observationID`` unique, as CamtrapDP requires but some exports break.

    Decisions, *unsure* marks, tags and the verified export all look observations up by
    ``observationID``. Some exports reuse the same ID for different observations (e.g. a Trapper
    export where detector and classifier rows, of different photos and species, share numbers):
    a decision on one event then also landed on the cells of the others. Repeated IDs get the
    ``mediaID`` appended (``"165960#8896728"``), plus a counter if that is still not unique. The
    rule is deterministic, so a reopened session finds the same IDs. The original value is kept in
    :data:`ORIG_OBSERVATION_ID` and put back by :func:`restore_observation_ids` before a CamtrapDP
    is written. Archives with unique IDs are returned unchanged.
    """
    if "observationID" not in obs.columns:
        return obs
    ids = obs["observationID"]
    dup = ids.duplicated(keep=False) & ids.notna()
    if not dup.any():
        return obs
    obs = obs.copy()
    media = obs["mediaID"].fillna("") if "mediaID" in obs.columns else pd.Series("", index=obs.index)
    new = ids.where(~dup, ids + "#" + media)
    still = new.duplicated(keep=False) & new.notna()
    if still.any():
        n = new[still].groupby(new[still]).cumcount().add(1).astype(str)
        new.loc[still] = new[still] + "#" + n
    obs[ORIG_OBSERVATION_ID] = ids
    obs["observationID"] = new
    return obs


def restore_observation_ids(obs: pd.DataFrame) -> pd.DataFrame:
    """Undo :func:`dedupe_observation_ids` before writing ``observations.csv``."""
    if ORIG_OBSERVATION_ID not in obs.columns:
        return obs
    obs = obs.copy()
    keep = obs[ORIG_OBSERVATION_ID].notna()
    obs.loc[keep, "observationID"] = obs.loc[keep, ORIG_OBSERVATION_ID]
    return obs.drop(columns=[ORIG_OBSERVATION_ID])


VALIDATION_ROW_LIMIT = 50_000


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

    # Only the first rows of each table are checked: validation runs at about 25 k rows/s, so the
    # whole observations table of a large archive would take minutes for no extra information.
    report = frictionless.validate(str(datapackage_path), limit_rows=VALIDATION_ROW_LIMIT)
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


# Extensions that name the same kind of file: a classifier export may call a photo
# ``x.JPEG`` while the file on disk is ``x.jpg``.
_EXT_ALIASES = {".jpeg": ".jpg", ".jpe": ".jpg", ".tiff": ".tif"}

# How many trailing parts of a ``filePath`` are tried under a base folder.
_MAX_SUFFIX_PARTS = 6

# How deep below the images folder a folder named like a deployment is looked for
# (``images/R0025/dep_0011`` is 2 levels down).
_DEPLOYMENT_DIR_DEPTH = 3


def _norm_name(name: str) -> str:
    """File name in lower case with equivalent image extensions folded (``x.JPEG`` -> ``x.jpg``)."""
    stem, ext = os.path.splitext(name.lower())
    return stem + _EXT_ALIASES.get(ext, ext)


def _path_parts(file_path: str) -> list[str]:
    """Components of a path written on any operating system (a drive letter is dropped)."""
    parts = [p for p in re.split(r"[\\/]+", file_path) if p and p not in (".", "..")]
    if parts and re.fullmatch(r"[A-Za-z]:", parts[0]):
        parts = parts[1:]
    return parts


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _suffix_match(file_path: str, base: Path) -> Optional[Path]:
    """First existing ``base / <last k parts of file_path>``, longest k first.

    ``file_path`` may come from another computer, so both ``/`` and ``\\`` separate its
    parts. Only suffixes of at least two parts (``parent/fileName``) are tried, so a bare
    file name is never matched at the root of ``base``.
    """
    if not file_path or is_remote_path(file_path):
        return None
    parts = _path_parts(file_path)
    for k in range(min(len(parts), _MAX_SUFFIX_PARTS), 1, -1):
        candidate = base.joinpath(*parts[-k:])
        if _is_file(candidate):
            return candidate
    return None


@lru_cache(maxsize=8)
def _flat_image_index_norm(image_base_dir: str) -> dict[str, tuple[str, ...]]:
    """The flat index keyed by :func:`_norm_name` (``x.JPEG`` finds ``x.jpg``)."""
    index: dict[str, list[str]] = {}
    for name, paths in _flat_image_index(image_base_dir).items():
        index.setdefault(_norm_name(name), []).extend(paths)
    return {k: tuple(v) for k, v in index.items()}


@lru_cache(maxsize=4096)
def _folder_names(directory: str) -> tuple[frozenset[str], dict[str, str]]:
    """(exact file names, normalised name -> real name) of one folder; empty if unreadable."""
    try:
        names = os.listdir(directory)
    except OSError:
        return frozenset(), {}
    norm: dict[str, str] = {}
    for n in sorted(names):
        norm.setdefault(_norm_name(n), n)
    return frozenset(names), norm


class _DeploymentFolders:
    """Folders named like a deployment, up to ``_DEPLOYMENT_DIR_DEPTH`` levels below a base.

    The tree is explored one level at a time and only as deep as needed, so an archive laid
    out as ``images/<group>/<deploymentID>/`` costs a couple of folder listings, not a walk
    over every photo.
    """

    def __init__(self, base: str):
        self.by_name: dict[str, list[str]] = {}
        self.frontier = [base]
        self.depth = 0

    def find(self, deployment_id: str) -> list[str]:
        want = deployment_id.lower()
        while want not in self.by_name and self.frontier and self.depth < _DEPLOYMENT_DIR_DEPTH:
            level: list[str] = []
            for directory in self.frontier:
                try:
                    with os.scandir(directory) as entries:
                        subdirs = [e.path for e in entries if e.is_dir()]
                except OSError:
                    continue
                for sub in subdirs:
                    self.by_name.setdefault(os.path.basename(sub).lower(), []).append(sub)
                    level.append(sub)
            self.frontier = level
            self.depth += 1
        return self.by_name.get(want, [])


_DEPLOYMENT_TREES: dict[str, _DeploymentFolders] = {}


def _by_deployment_folder(image_base_dir: str, deployment_id: str, file_name: str) -> Optional[Path]:
    """The photo in a folder named like its deployment anywhere below the images folder.

    The folder name is matched ignoring case and the file name ignoring case and
    ``.JPEG``/``.jpg``. Covers classifier exports (e.g. from TRAPPER) whose ``filePath`` is a
    web address and whose file names differ in extension from the files on disk, with the
    photos stored as ``images/<group>/<deploymentID>/``. A name found in more than one folder
    is ambiguous and is not used.
    """
    if not image_base_dir or not deployment_id or not file_name:
        return None
    tree = _DEPLOYMENT_TREES.setdefault(image_base_dir, _DeploymentFolders(image_base_dir))
    folders = [os.path.join(image_base_dir, deployment_id), *tree.find(deployment_id)]
    hits: dict[str, str] = {}
    for folder in folders:
        exact, norm = _folder_names(folder)
        name = file_name if file_name in exact else norm.get(_norm_name(file_name))
        if name is not None:
            path = os.path.join(folder, name)
            hits.setdefault(os.path.normcase(os.path.normpath(path)), path)
    if len(hits) == 1:
        return Path(next(iter(hits.values())))
    if len(hits) > 1:
        logger.warning("Photo %s of %s found in %d folders; not used", file_name, deployment_id, len(hits))
    return None


def dataset_fingerprint(camtrap_dir: Path) -> Optional[str]:
    """Content hash of a CamtrapDP's deployments table, or None if it cannot be read.

    It identifies "the same dataset" across computers regardless of where it is stored, so a
    session imported from another computer can find the data folder automatically when this
    computer already used the same dataset in another session.
    """
    import hashlib

    dep = resolve_camtrapdp_resource(Path(camtrap_dir), "deployments")
    if dep is None:
        return None
    try:
        return hashlib.sha1(dep.read_bytes()).hexdigest()
    except OSError:
        return None


def media_extra_bases(camtrap_dir: str, image_base_dir: str) -> tuple[Path, ...]:
    """Folders also searched by the end of ``filePath`` when a photo is not under the images folder.

    With an Images directory set these are the CamtrapDP folder and the parent of the Images
    directory (so choosing the ``camtrapDP`` folder itself, one level too deep, does not hide
    every photo). Without one the CamtrapDP folder is already the base, so none are needed.
    """
    if not image_base_dir:
        return ()
    bases: list[Path] = []
    for b in (Path(camtrap_dir) if camtrap_dir else None, Path(image_base_dir).parent):
        if b is not None and b != Path(image_base_dir) and b not in bases:
            bases.append(b)
    return tuple(bases)


def clear_media_caches() -> None:
    """Drop the cached file indexes and folder listings.

    They never invalidate on their own (no mtime/TTL check), so a new session reusing the
    same ``image_base_dir`` after files were added, moved, or removed on disk would otherwise
    keep seeing the old listing for as long as this backend process stays alive. Call this
    once per new setup so each session starts from a fresh scan.
    """
    _flat_image_index.cache_clear()
    _flat_image_index_norm.cache_clear()
    _folder_names.cache_clear()
    _DEPLOYMENT_TREES.clear()


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
    extra_bases: tuple = (),
) -> Path:
    """Resolve a media record to a local file path.

    When ``image_base_dir`` is set, it takes precedence over ``filePath``:
    the image is first looked up at ``image_base_dir/deploymentID/fileName``
    (matching R's structured ``resolve_media_files()``), regardless of
    whether ``filePath`` is absolute, relative, or a remote URL -- a common
    TRAPPER export has a remote ``filePath`` but the files were downloaded
    locally under that layout.

    If that misses, the trailing part of ``filePath`` is looked up under
    ``image_base_dir`` (longest first, down to ``parent/fileName``). This finds photos
    whose ``filePath`` points at another computer -- e.g.
    ``/Volumes/Disk/2023/R0025/dep_0011/x.jpg`` exported on a Mac -- when
    ``image_base_dir`` is the local folder holding ``R0025/``, without scanning
    the whole image tree.

    Then a folder named like the ``deploymentID`` is searched up to three levels
    below ``image_base_dir`` and ``fileName`` is looked up in it ignoring case and
    equivalent extensions (``x.JPEG`` is found as ``x.jpg``). A name found in more
    than one such folder is ambiguous and is not used.

    If that misses and ``flat_search`` is enabled, ``fileName`` is looked up
    case-insensitively anywhere under ``image_base_dir`` (R's "flat" mode), also
    ignoring equivalent extensions. Ties are broken by keeping only hits whose
    path contains ``deployment_id``; if more than one candidate remains, the match
    is ambiguous and is logged as such (not raised -- a single image failing to
    resolve should not interrupt review of the rest), and resolution falls
    through to the next rule.

    Then the end of ``filePath`` is tried under each of ``extra_bases`` (see
    :func:`media_extra_bases`) if the file does not exist as written.

    Otherwise falls back to the previous rule (``filePath`` used as-is if
    absolute, otherwise joined to ``fallback_base``) when nothing above
    matched, or when ``image_base_dir`` is not set. In the latter case, if that
    file does not exist, the end of ``filePath`` is tried under ``fallback_base``
    (the CamtrapDP folder), so photos stored below the data folder are found even
    when no images folder was configured.

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
        extra_bases: Folders whose layout may hold the photo under the end of
            ``filePath`` when it is not under ``image_base_dir``.

    Returns:
        The resolved path (existence is not checked here).
    """
    if image_base_dir:
        structured = Path(image_base_dir) / deployment_id / file_name
        if _exists_or_denied(structured):
            return structured

        suffix_hit = _suffix_match(file_path, Path(image_base_dir))
        if suffix_hit is not None:
            return suffix_hit

        deployment_hit = _by_deployment_folder(str(image_base_dir), deployment_id, file_name)
        if deployment_hit is not None:
            return deployment_hit

        if flat_search and file_name:
            hits = _flat_image_index(str(image_base_dir)).get(file_name.lower(), ())
            if not hits:
                hits = _flat_image_index_norm(str(image_base_dir)).get(_norm_name(file_name), ())
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
    if file_path and not is_remote_path(file_path) and not _is_file(p):
        # The photo is not where filePath says: try its end under the other folders.
        for base in (extra_bases if image_base_dir else (fallback_base,)):
            suffix_hit = _suffix_match(file_path, Path(base))
            if suffix_hit is not None:
                return suffix_hit
    return p


def gallery_frame_img_url(
    file_path: str,
    media_id: str,
    deployment_id: str,
    file_name: str,
    image_base_dir: str,
    fallback_base: Path,
    flat_search: bool = False,
    extra_bases: tuple = (),
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
                flat_search=flat_search, extra_bases=extra_bases,
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
) -> Path:
    """Convert any classifier CSV to CamtrapDP using user-defined column mapping.

    ``filePath`` is written as the ``col_filename`` column value as-is (only
    backslashes normalised to forward slashes) -- see ``deepfaune_to_camtrapdp``
    for why: locating the images is ``resolve_media_path()``'s job at review
    time via ``image_base_dir``, same as any other CamtrapDP directory, not
    something this conversion bakes in once and for all.

    If the CSV has the CamtrapDP columns ``bboxX``, ``bboxY``, ``bboxWidth`` and
    ``bboxHeight`` (relative 0-1 coordinates), they are kept in ``observations.csv``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if species_map is None:
        species_map = {}

    nonanimal = {
        "empty": "blank", "vide": "blank", "blank": "blank",
        "human": "human", "humain": "human", "person": "human",
        "undefined": "unclassified", "unknown": "unclassified",
    }

    def site_from_path(p: str) -> str:
        return re.sub(r"^R\d+-", "", Path(p).parent.name)

    paths = df[col_filename].astype(str).str.replace("\\", "/", regex=False)
    file_names = paths.apply(lambda p: Path(p).name)
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
        "fileName":     list(file_names),
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
        # CamtrapDP bounding box columns, kept when the CSV has them (relative 0-1 coordinates
        # of the top-left corner and size); the review draws them on the photo.
        **{c: list(df[c]) for c in BOX_COLS if c in df.columns},
    }).to_csv(out_dir / "observations.csv", index=False)
    return out_dir


# ─── Frame order ──────────────────────────────────────────────────────────────

_CAPTURE_SEQ = r"_(\d+)\.[^./\\]+$"


def capture_seq(df: pd.DataFrame) -> pd.Series:
    """Capture number from the trailing ``_<n>`` of the file name (``..._127.JPEG`` -> 127).

    It orders frames that share a timestamp (many cameras and exports keep whole
    seconds only). ``fileName`` is tried first because ``filePath`` may be a web
    address that does not contain the name (e.g. Trapper's ``.../media/4897674/file/``);
    ``filePath`` is the fallback. Frames without a number get NaN and sort last.
    """
    seq = pd.Series(float("nan"), index=df.index)
    for col in ("fileName", "filePath"):
        if col in df:
            n = pd.to_numeric(df[col].astype(str).str.extract(_CAPTURE_SEQ)[0], errors="coerce")
            seq = seq.fillna(n)
    return seq


def _sort_frames(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Sort by ``by`` and then by capture number, keeping the order of rows that still tie."""
    return (df.assign(_seq=capture_seq(df))
              .sort_values(by + ["_seq"], kind="stable", na_position="last")
              .drop(columns="_seq"))


def _frame_times(df: pd.DataFrame) -> pd.Series:
    """Vectorised :func:`_frame_time`: time to the second from ``ts``, else the stored text, else ''."""
    shown = df["ts"].dt.strftime("%Y-%m-%d %H:%M:%S") if "ts" in df.columns else pd.Series(index=df.index, dtype=object)
    if "timestamp_display" in df.columns:
        shown = shown.where(df["ts"].notna(), df["timestamp_display"])
    return shown.fillna("")


def _frame_time(row) -> str:
    """Time shown for a frame, to the second (from ``ts``; the stored text is the fallback)."""
    ts = row.get("ts")
    if ts is not None and pd.notna(ts):
        return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    shown = row.get("timestamp_display")
    return shown if pd.notna(shown) else ""


# ─── Minimum score per species ────────────────────────────────────────────────

def species_min_scores(
    target_species: list[str],
    min_score: float,
    min_score_by_species: Optional[dict[str, float]] = None,
) -> dict[str, float]:
    """Cut-off that applies to each target species: its own value if it has one, else ``min_score``.

    A value ``<= 0`` means no cut-off for that species (also when the general one is higher).
    """
    own = {sp: float(v) for sp, v in (min_score_by_species or {}).items() if v is not None}
    return {sp: own.get(sp, float(min_score)) for sp in target_species}


# ─── Sampling occasion length ─────────────────────────────────────────────────

def occasion_length_hours(occasion_days: int, occasion_hours: Optional[int] = None) -> int:
    """Length of a sampling occasion in hours.

    ``occasion_hours`` when it is set (occasions shorter than a day, e.g. 1 hour
    for activity patterns); otherwise ``occasion_days`` x 24. Sessions made
    before ``occasion_hours`` existed only have ``occasion_days``.
    """
    return int(occasion_hours) if occasion_hours else int(occasion_days) * 24


def config_occasion_hours(config: dict) -> int:
    """Occasion length in hours of a session ``config`` (older ones: days only)."""
    return occasion_length_hours(int(config.get("occasion_days") or 1), config.get("occasion_hours"))


def occasion_windows_dt(study_start: date, study_end: date, hours: int) -> list[tuple[datetime, datetime]]:
    """Consecutive ``[lo, hi)`` windows of ``hours`` from ``study_start`` 00:00 to the end of ``study_end``.

    The last window is clipped to the end of the study period, so it may be shorter.
    """
    lo = datetime.combine(study_start, datetime.min.time())
    end = datetime.combine(study_end, datetime.min.time()) + timedelta(days=1)
    step = timedelta(hours=hours)
    out: list[tuple[datetime, datetime]] = []
    while lo < end:
        out.append((lo, min(lo + step, end)))
        lo += step
    return out


# ─── Bounding boxes ───────────────────────────────────────────────────────────

BOX_COLS = ["bboxX", "bboxY", "bboxWidth", "bboxHeight"]


def collect_boxes(obs: pd.DataFrame) -> dict[tuple[str, str], str]:
    """Bounding boxes of each (mediaID, scientificName), as JSON ``[[x, y, w, h], ...]``.

    Uses the CamtrapDP columns ``bboxX``, ``bboxY``, ``bboxWidth`` and ``bboxHeight``:
    the top-left corner and size of the box, **relative to the image** (0 to 1).
    Boxes that are missing, not numeric, empty or outside the image are ignored.
    The boxes of a photo and species are listed best first (highest
    ``classificationProbability``), so the first one is the one of the
    representative observation. Returns ``{}`` when the box columns are absent.
    """
    if not all(c in obs.columns for c in BOX_COLS):
        return {}
    b = obs[BOX_COLS].apply(pd.to_numeric, errors="coerce")
    eps = 1e-3
    ok = (
        b.notna().all(axis=1)
        & (b["bboxWidth"] > 0) & (b["bboxHeight"] > 0)
        & (b["bboxX"] >= -eps) & (b["bboxY"] >= -eps)
        & (b["bboxX"] + b["bboxWidth"] <= 1 + eps) & (b["bboxY"] + b["bboxHeight"] <= 1 + eps)
    )
    if not ok.any():
        return {}
    sub = obs.loc[ok, ["mediaID", "scientificName"]].copy()
    sub["_p"] = pd.to_numeric(obs.loc[ok, "classificationProbability"], errors="coerce").fillna(-1)
    sub["_box"] = [
        [round(float(max(x, 0)), 5), round(float(max(y, 0)), 5), round(float(w), 5), round(float(h), 5)]
        for x, y, w, h in zip(b.loc[ok, "bboxX"], b.loc[ok, "bboxY"], b.loc[ok, "bboxWidth"], b.loc[ok, "bboxHeight"])
    ]
    sub = sub.sort_values("_p", ascending=False, kind="stable")
    grouped = sub.groupby(["mediaID", "scientificName"], sort=False)["_box"].agg(list)
    return {(str(m), str(sp)): json.dumps(boxes) for (m, sp), boxes in grouped.items()}


def count_boxes(value) -> int:
    """Number of boxes in a candidate's ``bboxes`` cell (JSON text, empty or NaN)."""
    if not isinstance(value, str) or not value:
        return 0
    try:
        return len(json.loads(value))
    except (ValueError, TypeError):
        return 0


# ─── Build candidate manifest ─────────────────────────────────────────────────

def _assign_burst_ids(joined: pd.DataFrame, gap_seconds: int) -> pd.DataFrame:
    """Add ``burst_id``: within each ``site_occasion_key`` (rows sorted by time), a new burst
    starts at every gap longer than ``gap_seconds`` (or around a missing time)."""
    if joined.empty:
        return joined
    joined = joined.reset_index(drop=True)
    key = joined["site_occasion_key"]
    ts = joined["ts"]
    gap = ts.groupby(key, sort=False).diff()
    same_cell = key.eq(key.shift())
    new_burst = ~same_cell | ts.isna() | ts.shift().isna() | gap.gt(pd.Timedelta(seconds=gap_seconds))
    # the first row of a cell starts burst 0, so only later rows count as a new burst
    joined["burst_id"] = (new_burst & same_cell).groupby(key, sort=False).cumsum().astype(int)
    return joined


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
    seed: int = 42,
    occasion_hours: Optional[int] = None,
    min_score_by_species: Optional[dict[str, float]] = None,
    review_order: str = "score",
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
        seed: Seed of the pseudo-random order of detection events that have the
            same score within a cell (for example when no frame has a score). The
            same seed gives the same order; the order does not depend on the
            chronology or on the row order. Defaults to 42.
        occasion_hours: Width of each sampling occasion in hours instead of days
            (e.g. 1 for activity patterns). ``None`` or 0 uses ``occasion_days``.
        min_score_by_species: Optional ``scientificName`` -> cut-off that replaces
            ``min_score`` for that species (``<= 0`` for no cut-off). Species not
            listed use ``min_score``.
        review_order: ``"score"`` (default) ranks the events of a cell from the most
            confident one; ``"time"`` ranks them from the earliest one, so the first
            confirmed event is the first true detection (needed for time-to-detection).
            Detection histories are the same either way.

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

    # Detection events that "Classifiers and reference" removed stay in its observations.csv
    # (tagged) so the dataset is complete, but they are not reviewed.
    not_filtered = ~has_tag(obs["observationTags"], TAG_FILTERED) if "observationTags" in obs \
        else pd.Series(True, index=obs.index)
    target_obs = obs[
        not_filtered
        & (obs["observationLevel"] == "media")
        & (obs["observationType"] == "animal")
        & (obs["scientificName"].isin(target_species))
    ].copy()

    # Keep the bounding boxes of every (mediaID, scientificName) before the collapse
    # below, so the review can show which animal(s) of the species is being verified.
    boxes_by_key = collect_boxes(target_obs)

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
    target_obs["bboxes"] = [
        boxes_by_key.get((str(m), str(sp)), "")
        for m, sp in zip(target_obs["mediaID"], target_obs["scientificName"])
    ]

    # Demote frames whose own classification score falls below min_score, mirroring
    # to_camtrapdp()'s per-frame threshold: a frame with no score at all is never
    # demoted (only a known low score excludes it), and this runs before burst
    # grouping, so a demoted frame no longer counts toward a burst's gap-based grouping.
    overrides = {sp: float(v) for sp, v in (min_score_by_species or {}).items() if v is not None}
    if min_score > 0 or any(v > 0 for v in overrides.values()):
        target_prob = pd.to_numeric(target_obs["classificationProbability"], errors="coerce")
        threshold = target_obs["scientificName"].map(overrides).fillna(float(min_score)).astype(float)
        target_obs = target_obs[~(target_prob.notna() & (threshold > 0) & (target_prob < threshold))]

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

    # Occasion = consecutive fixed-length windows from study_start 00:00 (the last one
    # clipped to the end of study_end). Same windows as the occupancy inputs, so every
    # candidate cell has a matching column there, including a trailing shorter window.
    occ_len = pd.Timedelta(hours=occasion_length_hours(occasion_days, occasion_hours))
    joined["occasion"] = ((joined["ts"] - pd.Timestamp(study_start)) // occ_len + 1).astype(int)
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
    joined = _sort_frames(joined, ["site_occasion_key", "ts"])

    # Assign burst IDs (consecutive frames within gap_seconds form one burst)
    joined = _assign_burst_ids(joined, gap_seconds)
    if joined.empty:
        return pd.DataFrame()

    # Rank bursts by max prob within each cell (highest prob = rank 1). Bursts with
    # the same score -- all of them when no frame has a score -- are put in a
    # pseudo-random order that depends only on ``seed``, the cell and the burst
    # (not on the row order), so it is reproducible and not chronological.
    burst_max = (
        joined.groupby(["site_occasion_key", "burst_id"])["prob"]
        .max()
        .reset_index(name="burst_max_prob")
    )
    burst_max["_tie"] = pd.util.hash_pandas_object(
        burst_max[["site_occasion_key", "burst_id"]].assign(_seed=seed), index=False
    )
    if review_order == "time":
        # Earliest event first. Bursts of a cell are numbered in time order, so burst_id breaks any tie.
        burst_max = burst_max.sort_values(["site_occasion_key", "burst_id"])
    else:
        burst_max = burst_max.sort_values(
            ["site_occasion_key", "burst_max_prob", "_tie"], ascending=[True, False, True]
        )
    burst_max["rank"] = burst_max.groupby("site_occasion_key").cumcount() + 1

    joined = joined.merge(burst_max[["site_occasion_key", "burst_id", "rank"]],
                          on=["site_occasion_key", "burst_id"])
    joined["burst_seq"] = (
        joined.groupby(["site_occasion_key", "burst_id"]).cumcount() + 1
    )

    candidates = joined[joined["rank"] <= total_iterations].copy()
    candidates["timestamp_display"] = candidates["ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
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
                    "timestamp_display":         ts_val.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ts_val) else "",
                    "is_context":                True,
                })

        if context_rows:
            ctx_df = pd.DataFrame(context_rows)
            candidates = pd.concat([candidates, ctx_df], ignore_index=True)
            candidates = _sort_frames(
                candidates, ["site_occasion_key", "burst_id", "ts"]
            ).reset_index(drop=True)

    return candidates[[
        "site_occasion_key", "rank", "burst_id", "burst_seq",
        "observationID", "mediaID", "filePath", "fileName",
        "classificationProbability", "scientificName", "deploymentID",
        "siteID", "occasion", "species_safe", "ts", "timestamp_display",
        "is_context", "bboxes",
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


def confirmed_observations(decisions_dir: Path, species_cands: pd.DataFrame) -> dict[str, str]:
    """``site_occasion_key`` -> confirmed ``observationID`` for the cells of one species.

    Only confirmations whose observation belongs to ``species_cands`` are returned,
    so a cell can be shown with the detection event that was actually confirmed
    (which may come from a later round), not just with its rank-1 event.
    """
    dec = load_all_decisions(decisions_dir)
    if dec.empty:
        return {}
    keys = set(species_cands["site_occasion_key"])
    obs = set(species_cands["observationID"].astype(str))
    dec = dec[dec["site_occasion_key"].isin(keys) & dec["observationID"].astype(str).isin(obs)]
    dec = dec.drop_duplicates("site_occasion_key", keep="last")
    return dict(zip(dec["site_occasion_key"], dec["observationID"].astype(str)))


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
    # Only this species' rows: an observationID repeated in another species' cells must never
    # confirm those cells.
    if "species_safe" in candidates.columns:
        candidates = candidates[candidates["species_safe"] == species_safe]
    if not confirmed_ids:
        df = candidates.iloc[0:0][cols]
    else:
        df = candidates[candidates["observationID"].isin(confirmed_ids)][cols]
    df.to_csv(path, index=False)
    return df


def save_unsure(
    decisions_dir: Path,
    candidates: pd.DataFrame,
    species_safe: str,
    iteration: int,
    unsure_ids: list[str],
) -> pd.DataFrame:
    """Persist the events marked *unsure* in a round to ``unsure_{species}_iter{N}.csv``.

    An unsure event is a rejection as far as occupancy is concerned: nothing
    here feeds ``decisions_*.csv``, detection histories or cell status. The file
    only records the flag so unsure decisions can be counted and restored. It
    is always (over)written, even when empty, so a changed round leaves no stale flags.

    Args:
        decisions_dir: Directory where decision CSVs are stored.
        candidates: Full candidate manifest (used to look up metadata by ID).
        species_safe: Sanitized species name used in the filename.
        iteration: Round number used in the filename.
        unsure_ids: ``observationID`` values of the events marked unsure.

    Returns:
        DataFrame of the rows that was written to disk.
    """
    decisions_dir.mkdir(parents=True, exist_ok=True)
    cols = ["observationID", "site_occasion_key", "mediaID",
            "scientificName", "siteID", "occasion"]
    if "species_safe" in candidates.columns:                 # see save_decisions
        candidates = candidates[candidates["species_safe"] == species_safe]
    df = candidates[candidates["observationID"].isin(unsure_ids)][cols] \
        if unsure_ids else candidates.iloc[0:0][cols]
    df.to_csv(decisions_dir / f"unsure_{species_safe}_iter{iteration}.csv", index=False)
    return df


def load_all_unsure(decisions_dir: Path) -> pd.DataFrame:
    """Concatenate all ``unsure_*.csv`` files (empty frame with the columns if none)."""
    cols = ["observationID", "site_occasion_key", "mediaID",
            "scientificName", "siteID", "occasion"]
    files = list(decisions_dir.glob("unsure_*.csv")) if decisions_dir.exists() else []
    if not files:
        return pd.DataFrame(columns=cols)
    return pd.concat([pd.read_csv(f, dtype=str) for f in files], ignore_index=True)


NO_ANIMAL_LABEL = "No animal / empty"
CORRECTION_COLS = ["observationID", "site_occasion_key", "mediaID", "scientificName",
                   "species_safe", "iteration", "actual_species"]


def save_rejection_corrections(
    path: Path,
    candidates: pd.DataFrame,
    species_safe: str,
    iteration: int,
    corrections: dict[str, str],
) -> pd.DataFrame:
    """Record the "actual species" typed for rejected events of one round.

    Writes ``rejection_corrections.csv``. The rows of this species and round are
    replaced (so editing a round leaves no stale entries) and the rest are kept.
    Purely informational: nothing here feeds decisions, detection histories or
    cell status. Empty values and unknown observation IDs are ignored.

    Args:
        path: ``rejection_corrections.csv`` in the session folder.
        candidates: Full candidate manifest (used to look up metadata by ID).
        species_safe: Sanitized species name of the reviewed species.
        iteration: Round number.
        corrections: ``observationID`` -> actual species (free text).

    Returns:
        The full contents of the file after the update.
    """
    clean = {k: str(v).strip() for k, v in corrections.items() if str(v).strip()}
    meta = candidates[candidates["observationID"].isin(clean)].drop_duplicates("observationID")
    new = meta[["observationID", "site_occasion_key", "mediaID", "scientificName", "species_safe"]].copy()
    new["iteration"] = iteration
    new["actual_species"] = new["observationID"].map(clean)
    old = load_rejection_corrections(path)
    if not old.empty:
        same = (old["species_safe"] == species_safe) & (old["iteration"].astype(int) == iteration)
        old = old[~same]
    out = pd.concat([old, new[CORRECTION_COLS]], ignore_index=True)
    out.to_csv(path, index=False)
    return out


def load_rejection_corrections(path: Path) -> pd.DataFrame:
    """Read ``rejection_corrections.csv`` (empty frame with the columns if absent)."""
    if not path.exists():
        return pd.DataFrame(columns=CORRECTION_COLS)
    return pd.read_csv(path, dtype=str).fillna("")


def build_false_positive_sources(
    effort: pd.DataFrame,
    decisions_dir: Path,
    corrections_path: Path,
    out_dir: Path,
) -> Optional[pd.DataFrame]:
    """Write ``false_positive_sources.csv``: what rejected events actually were, per species.

    One row per (species, actual species) with the number of rejected events and
    their share of **all** the rejected events of that species, plus a
    ``(not recorded)`` row for rejected events with no correction, so the shares
    add up to 100 % and the coverage of the recording is visible. A rejected
    event is any inspected event that was not confirmed (unsure events
    included, since they behave as rejections).

    Args:
        effort: Per-species rows of :func:`build_species_effort` (``TOTAL`` is ignored).
        decisions_dir: Directory with the decision CSVs (to drop corrections of
            events that were confirmed afterwards).
        corrections_path: ``rejection_corrections.csv``.
        out_dir: Destination directory.

    Returns:
        The table, or ``None`` when no corrections file exists (feature never used).
    """
    if not corrections_path.exists():
        return None
    corr = load_rejection_corrections(corrections_path)
    dec = load_all_decisions(decisions_dir) if decisions_dir.exists() else pd.DataFrame()
    if not dec.empty and not corr.empty:
        corr = corr[~corr["observationID"].isin(set(dec["observationID"].dropna()))]
    rows = []
    for _, e in effort[effort["species"] != "TOTAL"].iterrows():
        rejected = int(e["events_inspected"] - e["cells_detection"])
        sub = corr[corr["scientificName"] == e["species"]]
        counts = sub["actual_species"].value_counts()
        for actual, n in counts.items():
            rows.append({"species": e["species"], "actual_species": actual, "rejected_events": int(n),
                         "pct_of_rejected_events": round(100 * int(n) / rejected, 1) if rejected else None})
        missing = max(rejected - int(counts.sum()), 0)
        if rejected:
            rows.append({"species": e["species"], "actual_species": "(not recorded)",
                         "rejected_events": missing,
                         "pct_of_rejected_events": round(100 * missing / rejected, 1)})
    df = pd.DataFrame(rows, columns=["species", "actual_species", "rejected_events", "pct_of_rejected_events"])
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "false_positive_sources.csv", index=False)
    return df


REVIEW_LOG_COLS = ["observationID", "site_occasion_key", "species_safe", "scientificName",
                   "iteration", "decision", "decided_at"]


def save_review_log(
    path: Path,
    candidates: pd.DataFrame,
    species_safe: str,
    iteration: int,
    confirmed: list[str],
    unsure: list[str],
    times_ms: dict[str, int],
) -> pd.DataFrame:
    """Record when each decision of a round was made, in ``review_log.csv``.

    ``times_ms`` maps ``observationID`` -> epoch milliseconds taken in the browser
    when the reviewer clicked. The decision is ``confirmed`` or ``unsure`` when
    the ID is in those lists and ``rejected`` otherwise. Rows of this species and
    round are replaced; an event that has no new time (it was restored from an
    earlier save and not touched) keeps its previous timestamp. Purely
    informational: nothing here feeds decisions, histories or cell status.

    Returns:
        The full contents of the file after the update.
    """
    old = load_review_log(path)
    prev = {}
    if not old.empty:
        same = (old["species_safe"] == species_safe) & (old["iteration"].astype(int) == iteration)
        prev = dict(zip(old.loc[same, "observationID"], old.loc[same, "decided_at"]))
        old = old[~same]
    conf, unc = set(confirmed), set(unsure)
    meta = candidates[candidates["observationID"].isin(set(times_ms) | set(prev))] \
        .drop_duplicates("observationID")
    rows = []
    for _, r in meta.iterrows():
        oid = r["observationID"]
        if oid in times_ms:
            at = pd.Timestamp(int(times_ms[oid]), unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        else:
            at = prev[oid]
        rows.append({
            "observationID": oid, "site_occasion_key": r["site_occasion_key"],
            "species_safe": species_safe, "scientificName": r["scientificName"],
            "iteration": iteration,
            "decision": "confirmed" if oid in conf else "unsure" if oid in unc else "rejected",
            "decided_at": at,
        })
    out = pd.concat([old, pd.DataFrame(rows, columns=REVIEW_LOG_COLS)], ignore_index=True)
    out.to_csv(path, index=False)
    return out


def load_review_log(path: Path) -> pd.DataFrame:
    """Read ``review_log.csv`` (empty frame with the columns if absent: older sessions)."""
    if not path.exists():
        return pd.DataFrame(columns=REVIEW_LOG_COLS)
    return pd.read_csv(path, dtype=str).fillna("")


def review_time_by_species(log: pd.DataFrame, idle_seconds: int = 120) -> dict:
    """Active review time from the decision timestamps, per species and in total.

    Decisions of the whole session are put in time order. Each decision is
    credited with the time since the previous one **if that gap is at most
    ``idle_seconds``**; a longer gap is idle time (a break) and is not counted.
    The time before the first decision of each work block is not observable, so
    the result is a slight underestimate (about one decision per block).

    Returns:
        ``{"by_species": {scientificName: {"seconds", "credited", "timed"}},
        "seconds", "credited", "timed", "idle_seconds"}``; ``timed`` is the number of
        decisions with a timestamp and ``credited`` those that received time.
        Empty ``by_species`` and zeros when there is no log (sessions made
        before this was recorded).
    """
    out = {"by_species": {}, "seconds": 0.0, "credited": 0, "timed": 0, "idle_seconds": idle_seconds}
    if log.empty:
        return out
    t = pd.to_datetime(log["decided_at"], errors="coerce", utc=True)
    df = log.assign(_t=t).dropna(subset=["_t"]).sort_values("_t")
    if df.empty:
        return out
    gap = df["_t"].diff().dt.total_seconds()
    df["_credit"] = gap.where((gap >= 0) & (gap <= idle_seconds))
    for sp, g in df.groupby("scientificName"):
        out["by_species"][sp] = {"seconds": float(g["_credit"].fillna(0).sum()),
                                 "credited": int(g["_credit"].notna().sum()), "timed": int(len(g))}
    out["seconds"] = float(df["_credit"].fillna(0).sum())
    out["credited"] = int(df["_credit"].notna().sum())
    out["timed"] = int(len(df))
    return out


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
    extra_bases: tuple = (),
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

    # Per-frame display values for the whole selection at once (not row by row).
    sp_cands = _sort_frames(sp_cands, ["burst_id", "ts"])
    sp_cands["_ts_shown"] = _frame_times(sp_cands)
    sp_cands["_p"] = pd.to_numeric(sp_cands["classificationProbability"], errors="coerce")
    sp_cands["_ctx"] = (sp_cands["is_context"].fillna(False).astype(bool)
                        if "is_context" in sp_cands.columns else False)
    has_deployment = "deploymentID" in sp_cands.columns
    has_file_name = "fileName" in sp_cands.columns
    has_boxes = "bboxes" in sp_cands.columns

    events = []
    for key, group in sp_cands.groupby("site_occasion_key", sort=False):
        # (``group`` keeps the order of the frames sorted above.)
        # Context frames (is_context=True) are not used for repObsId / maxProb
        decision_rows = group[~group["_ctx"]]

        prob_col = pd.to_numeric(
            decision_rows["classificationProbability"], errors="coerce"
        ).fillna(0)
        rep_idx = prob_col.idxmax()
        rep_obs = decision_rows.loc[rep_idx, "observationID"]
        max_prob = float(prob_col.max())

        frames = []
        for obs_id, media_id, fp, dep_id, fname, ts_shown, prob, is_ctx_row, bboxes in zip(
            group["observationID"], group["mediaID"], group["filePath"],
            group["deploymentID"] if has_deployment else [""] * len(group),
            group["fileName"] if has_file_name else [""] * len(group),
            group["_ts_shown"], group["_p"], group["_ctx"],
            group["bboxes"] if has_boxes else [None] * len(group),
        ):
            img_url = gallery_frame_img_url(
                str(fp), str(media_id), str(dep_id), str(fname),
                image_base_dir, fallback_base, flat_search=flat_search, extra_bases=extra_bases,
            )
            frames.append({
                "obsId":     obs_id,
                "mediaId":   str(media_id),
                "img":       img_url,
                "ts":        ts_shown,
                "prob":      round(float(prob), 3) if pd.notna(prob) else None,
                "isContext": bool(is_ctx_row),
                # Boxes can only be drawn on images the app serves itself, not on remote ones.
                "boxes":     count_boxes(bboxes) if img_url.startswith("/api/image/") else 0,
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
    extra_bases: tuple = (),
) -> list[dict]:
    """Return all cells for a completed species with their decision status.

    A confirmed cell is shown with the detection event that was confirmed (which
    may come from a later round); an unconfirmed one with its rank-1 event
    (highest-confidence burst). Each event includes a ``status`` field so the
    review screen can pre-mark cards as confirmed or not confirmed without
    reloading decisions separately.

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
        extra_bases: Other folders searched by the end of ``filePath`` (see
            :func:`media_extra_bases`).

    Returns:
        List of event dicts (same structure as :func:`get_events`) with an
        additional ``status`` key: ``'confirmed'`` or ``'not_confirmed'``.
        Sorted by ``siteId`` then ``occasion``.
    """
    conf_keys = confirmed_keys_set(decisions_dir)
    total_seqs_by_key = species_cands.groupby("site_occasion_key")["rank"].max().to_dict()

    # Confirmed cells show the confirmed event; the others their rank-1 event.
    confirmed_obs = confirmed_observations(decisions_dir, species_cands)
    conf_bursts = (
        species_cands[species_cands["observationID"].astype(str).isin(set(confirmed_obs.values()))]
        [["site_occasion_key", "burst_id"]].drop_duplicates("site_occasion_key")
    )
    rank1_bursts = species_cands.loc[species_cands["rank"] == 1, ["site_occasion_key", "burst_id"]] \
        .drop_duplicates("site_occasion_key")
    rank1_bursts = rank1_bursts[~rank1_bursts["site_occasion_key"].isin(set(conf_bursts["site_occasion_key"]))]
    bursts = pd.concat([conf_bursts, rank1_bursts], ignore_index=True)
    shown = species_cands.merge(bursts, on=["site_occasion_key", "burst_id"])

    events = []
    for key, group in _sort_frames(shown, ["burst_id", "ts"]).groupby(
        "site_occasion_key", sort=False
    ):
        # (already sorted above; ``group`` keeps that order)

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
                image_base_dir, fallback_base, flat_search=flat_search, extra_bases=extra_bases,
            )
            row_is_ctx = bool(row.get("is_context", False))
            row_prob = pd.to_numeric(row.get("classificationProbability"), errors="coerce")
            frames.append({
                "obsId":     row["observationID"],
                "mediaId":   str(row["mediaID"]),
                "img":       img_url,
                "ts":        _frame_time(row),
                "prob":      round(float(row_prob), 3) if pd.notna(row_prob) else None,
                "isContext": row_is_ctx,
                # Boxes can only be drawn on images the app serves itself, not on remote ones.
                "boxes":     count_boxes(row.get("bboxes")) if img_url.startswith("/api/image/") else 0,
            })

        events.append({
            "key": key,
            "siteId": str(group["siteID"].iloc[0]),
            "occasion": int(group["occasion"].iloc[0]),
            "rank": int(group["rank"].iloc[0]),
            "totalSeqs": int(total_seqs_by_key.get(key, 1)),
            "repObsId": confirmed_obs[key] if confirmed_obs.get(key) in {str(f["obsId"]) for f in frames} else rep_obs,
            "maxProb": max_prob,
            "frames": frames,
            "status": "confirmed" if key in conf_keys else "not_confirmed",
        })

    events.sort(key=lambda e: (e["siteId"], e["occasion"]))
    return events


# ─── Export verified CamtrapDP ────────────────────────────────────────────────

TAG_FILTERED = "camtrapverify:filtered"    # removed by "Classifiers and reference": not reviewed
TAG_REFERENCE = "camtrapverify:reference"  # the reference (e.g. Zooniverse) confirmed it
TAG_CONFIRMED = "camtrapverify:confirmed"
TAG_REJECTED = "camtrapverify:rejected"
TAG_UNCERTAIN = "camtrapverify:unsure"
TAG_ACTUAL_SPECIES = "camtrapverify-actual-species:"


def _rep_confirmed(decisions_dir: Path) -> set:
    """``observationID`` of the confirmed representative of every confirmed event (decision files)."""
    ids: set = set()
    if decisions_dir.exists():
        for f in decisions_dir.glob("decisions_*_iter*.csv"):
            df = pd.read_csv(f, dtype=str)
            if "observationID" in df.columns:
                ids.update(df["observationID"].dropna())
    return ids


def reviewed_event_tags(
    candidates: pd.DataFrame,
    conf_ids: set,
    unc_ids: set,
    rounds_done: dict[str, int],
    corrections: Optional[dict[str, str]] = None,
) -> dict[str, list[str]]:
    """Tags for the events the reviewer rejected, by the ``observationID`` that represents each event.

    An event was *inspected and not confirmed* when its cell has a confirmation at a later rank,
    or has none and the species finished a round at that rank or later. Such an event is tagged
    ``camtrapverify:rejected``, or ``camtrapverify:unsure`` when it was marked unsure (which
    behaves as a rejection in the histories). With a recorded actual species the event also gets
    ``camtrapverify-actual-species:<name>``. Events never inspected get no tag.
    """
    cand = candidates
    if "is_context" in cand.columns:
        cand = cand[~cand["is_context"].fillna(False).astype(bool)]
    if cand.empty:
        return {}
    cell, burst = "site_occasion_key", "burst_id"
    cr = cand.loc[cand["observationID"].isin(conf_ids)].groupby(cell)["rank"].min()
    rows = cand.assign(
        _p=pd.to_numeric(cand["classificationProbability"], errors="coerce").fillna(0),
        _cr=cand[cell].map(cr),
        _done=cand["species_safe"].map(rounds_done).fillna(0),
    ).sort_values([cell, burst, "ts"], kind="stable")
    limit = rows["_cr"].where(rows["_cr"].notna(), rows["_done"] + 1)       # exclusive: ranks below it were inspected
    rows = rows[rows["rank"] < limit]
    if rows.empty:
        return {}
    reps = rows.loc[rows.groupby([cell, burst], sort=False)["_p"].idxmax(), "observationID"]
    tags: dict[str, list[str]] = {}
    for oid in reps:
        t = [TAG_UNCERTAIN if oid in unc_ids and oid not in conf_ids else TAG_REJECTED]
        actual = (corrections or {}).get(oid, "").strip().replace("|", " ")
        if actual:
            t.append(TAG_ACTUAL_SPECIES + actual)
        tags[str(oid)] = t
    return tags


def export_verified_camtrapdp(
    camtrap_dir: Path,
    out_dir: Path,
    decisions_dir: Path,
    rejected_media: set,
    classified_by_label: str = "expert_review",
    extended_confirmation: bool = False,
    candidates: Optional["pd.DataFrame"] = None,
    corrections: Optional[dict[str, str]] = None,
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
    else:
        mask = pd.Series(False, index=obs.index)

    # Record the review in observationTags (``key:value`` pairs separated by ``|``): confirmed,
    # rejected, unsure (a rejection that is counted apart) and, when recorded, the actual species.
    # Only the observations the reviewer looked at get a tag; existing tags are kept.
    tag_by_row: dict[int, list[str]] = {}
    if mask.any():
        for i in obs.index[mask]:
            tag_by_row[i] = [TAG_CONFIRMED]
    if candidates is not None and not candidates.empty:
        unc = load_all_unsure(decisions_dir) if decisions_dir.exists() else pd.DataFrame()
        unc_ids = set(unc["observationID"].dropna()) if not unc.empty else set()
        rev = reviewed_event_tags(candidates, _rep_confirmed(decisions_dir), unc_ids, rounds_completed(decisions_dir), corrections)
        if rev:
            rep_rows = obs[obs["observationID"].isin(rev)]
            by_pair = {(m, s): rev[str(o)] for o, m, s in zip(rep_rows["observationID"], rep_rows["mediaID"], rep_rows["scientificName"])}
            pairs = pd.Series(list(zip(obs["mediaID"], obs["scientificName"])), index=obs.index)
            for i, pair in pairs[pairs.isin(by_pair)].items():
                if i not in tag_by_row:                       # a confirmed photo is not also "rejected"
                    tag_by_row[i] = by_pair[pair]
    if tag_by_row:
        if "observationTags" not in obs.columns:
            obs["observationTags"] = ""
        new = pd.Series({i: "|".join(t) for i, t in tag_by_row.items()})
        old = obs.loc[new.index, "observationTags"].fillna("").astype(str).str.strip()
        obs.loc[new.index, "observationTags"] = (old + "|" + new).str.strip("|")

    obs = restore_observation_ids(obs)
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


def _deployment_interval(start, end) -> tuple[Optional[datetime], Optional[datetime]]:
    """Operating interval of a deployment as datetimes, or ``(None, None)`` if it cannot be read.

    A date without a time covers the whole day: the interval starts at 00:00 of the
    start date and ends at the end of the end date.
    """
    try:
        s, e = str(start).strip(), str(end).strip()
        start_dt = pd.Timestamp(normalise_ts(s)).to_pydatetime()
        end_dt = pd.Timestamp(normalise_ts(e)).to_pydatetime()
    except Exception:
        return None, None
    if len(e) <= 10:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


# ─── Occupancy inputs ─────────────────────────────────────────────────────────

def _ttd_to_df(y, sites: list[str], occ_cols: list[str]) -> pd.DataFrame:
    """A sites x occasions matrix of hours (NaN = NA) as a table with a ``siteID`` column."""
    df = pd.DataFrame(y, columns=occ_cols).round(3)
    df.insert(0, "siteID", sites)
    return df


def _time_to_detection(
    sp_cands: pd.DataFrame,
    dec: pd.DataFrame,
    sp: str,
    sp_safe: str,
    sites: list[str],
    windows_dt: list[tuple[datetime, datetime]],
    op,
    naive_keys: set,
    verif_keys: set,
    rounds_done: int,
):
    """Time to first detection per site x occasion, in hours from the start of the occasion.

    This is what ``unmarked::occuTTD`` expects: the **naive** matrix uses the earliest photo the
    classifier assigned to the species in the cell, the **verified** one the earliest photo of the
    confirmed event. A cell with no detection is *censored* at the length of its occasion (the last
    occasion may be shorter). ``NaN`` (NA) where the camera was not operating, and, in the verified
    matrix, where the cell is still pending (no confirmation and events left to review).

    The verified time is the **first true detection only when the events were reviewed in time
    order** (``review_order="time"``); in score order it is the time of the confirmed event, which
    may be later than an earlier detection that was never looked at.
    """
    import numpy as np

    n_sites, n_occ = op.shape
    tN = np.full((n_sites, n_occ), np.nan)
    tV = np.full((n_sites, n_occ), np.nan)
    real = sp_cands
    if "is_context" in real.columns:
        real = real[~real["is_context"].fillna(False).astype(bool)]
    first_naive = real.groupby("site_occasion_key")["ts"].min().to_dict()
    max_rank = sp_cands.groupby("site_occasion_key")["rank"].max().to_dict()
    # earliest photo of each confirmed event (a cell holds one confirmed event; take the earliest)
    first_verified: dict[str, "pd.Timestamp"] = {}
    if not dec.empty and verif_keys:
        conf_ids = set(dec["observationID"].dropna())
        conf_rows = real[real["observationID"].isin(conf_ids)][["site_occasion_key", "burst_id"]].drop_duplicates()
        events = real.groupby(["site_occasion_key", "burst_id"])["ts"].min()
        for key, burst in zip(conf_rows["site_occasion_key"], conf_rows["burst_id"]):
            t = events.get((key, burst))
            if t is not None and (key not in first_verified or t < first_verified[key]):
                first_verified[key] = t

    for i, site in enumerate(sites):
        for j, (lo, hi) in enumerate(windows_dt):
            if op[i, j] == 0:
                continue
            length = (hi - lo).total_seconds() / 3600
            key = f"{site}_occ{j + 1}_{sp_safe}"

            def hours(t) -> float:
                return float(min(max((t - lo).total_seconds() / 3600, 0.0), length))

            tN[i, j] = hours(first_naive[key]) if key in first_naive else length
            if key in verif_keys:
                tV[i, j] = hours(first_verified[key]) if key in first_verified else np.nan
            elif key in naive_keys and max_rank.get(key, 0) > rounds_done:
                tV[i, j] = np.nan                                   # pending: events left to review
            else:
                tV[i, j] = length                                   # all inspected and rejected, or no candidate
    return tN, tV


def build_occupancy_inputs(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    config: dict,
    out_dir: Path,
) -> None:
    """Generate occupancy-model input files, replicating R's ``build_occupancy_inputs()``.

    Outputs written to ``out_dir``:

    * ``camera_operation.csv`` — days active per site × occasion (**hours** active
      when the session uses ``occasion_hours``), computed from
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
            ``camtrap_dir``; optional ``occasion_hours`` for occasions shorter
            than a day).
        out_dir: Destination directory (created if absent).
    """
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)

    study_start    = date.fromisoformat(config["study_start"])
    study_end      = date.fromisoformat(config["study_end"])
    occasion_days  = int(config["occasion_days"])
    target_species = config["target_species"]
    # Occasions in hours (occasion_hours): windows to the hour and camera operation in hours.
    hours_mode     = bool(config.get("occasion_hours"))

    windows   = _occasion_windows(study_start, study_end, occasion_days)
    windows_dt = occasion_windows_dt(study_start, study_end, config_occasion_hours(config)) if hours_mode else []
    n_occ     = len(windows_dt) if hours_mode else len(windows)
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
    activity_dt: dict[str, list[tuple[datetime, datetime]]] = {}
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
                if hours_mode:
                    start_dt, end_dt = _deployment_interval(row["deploymentStart"], row["deploymentEnd"])
                    if start_dt is not None:
                        activity_dt.setdefault(s, []).append((start_dt, end_dt))

    if hours_mode:
        # Hours of operation per window, from deploymentStart/End. A date without a time
        # means the whole day: the start at 00:00 and the end at the end of that day.
        for i, site in enumerate(sites):
            periods_dt = activity_dt.get(site, [])
            for j, (lo, hi) in enumerate(windows_dt):
                full = (hi - lo).total_seconds() / 3600
                if not periods_dt:
                    op[i, j] = math.ceil(full)
                else:
                    active = sum(
                        max(0.0, (min(hi, pe) - max(lo, ps)).total_seconds()) for ps, pe in periods_dt
                    ) / 3600
                    op[i, j] = math.ceil(min(active, full))      # any operation in the window counts
    for i, site in enumerate(sites) if not hours_mode else ():
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

        # Time to detection (hours from the start of each occasion to its first detection)
        tN, tV = _time_to_detection(
            sp_cands, dec, sp, sp_safe, sites, occasion_windows_dt(
                study_start, study_end, config_occasion_hours(config)), op, naive_keys, verif_keys,
            rounds_completed(decisions_dir).get(sp_safe, 0),
        )
        _ttd_to_df(tN, sites, occ_cols).to_csv(out_dir / f"ttd_naive_{sp_safe}.csv", index=False)
        _ttd_to_df(tV, sites, occ_cols).to_csv(out_dir / f"ttd_verified_{sp_safe}.csv", index=False)

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

    keys = candidates["site_occasion_key"].unique()
    rank = pd.to_numeric(candidates["rank"], errors="coerce")
    key_str = candidates["site_occasion_key"].astype(str)
    conf_pairs = pd.DataFrame(columns=["_key", "observationID"])
    if not dec.empty and "site_occasion_key" in dec.columns:
        conf_pairs = (dec[["site_occasion_key", "observationID"]].dropna(subset=["observationID"])
                      .assign(_key=lambda d: d["site_occasion_key"].astype(str))[["_key", "observationID"]]
                      .drop_duplicates())
    conf_keys = set(conf_pairs["_key"])                    # cells with at least one confirmed event
    key_set = set(key_str)
    is_conf_cell = key_str.isin(conf_keys)
    n_conf = len(conf_keys & key_set)
    n_rej = len(key_set) - n_conf
    # a confirmed cell costs the rank of its confirmed event (1 when that event is not in the candidates)
    hit = pd.DataFrame({"_key": key_str, "observationID": candidates["observationID"], "rank": rank})
    hit = hit.merge(conf_pairs, on=["_key", "observationID"])
    ranks_of_conf = hit.groupby("_key")["rank"].min()
    conf_cells_present = sorted(conf_keys & key_set)
    ins_conf = int(ranks_of_conf.reindex(conf_cells_present).fillna(1).sum())
    # a cell with no confirmation costs its highest rank (every event was inspected)
    ins_rej = int(rank[~is_conf_cell].groupby(key_str[~is_conf_cell]).max().sum())

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


def compute_min_score_exclusions(
    candidates: pd.DataFrame,
    dep: pd.DataFrame,
    med: pd.DataFrame,
    obs: pd.DataFrame,
    target_species: list[str],
    study_start: date,
    study_end: date,
    occasion_days: int,
    total_iterations: int,
    gap_seconds: int,
    min_score: float,
    seed: int = 42,
    occasion_hours: Optional[int] = None,
    min_score_by_species: Optional[dict[str, float]] = None,
    review_order: str = "score",
) -> pd.DataFrame:
    """Count what the ``min_score`` cut-off removed from the review, per species.

    ``build_candidates`` drops frames whose classification probability is
    strictly below ``min_score`` (a frame scoring exactly ``min_score`` or with
    no score is kept), so those photos can never reach the reviewer. This
    rebuilds the candidates without the cut-off and compares them with the ones
    actually kept (``candidates``):

    * ``excluded_photos``: frames removed by the cut-off.
    * ``excluded_events``: detection events made only of removed frames.
    * ``excluded_cells``: site x occasion cells left with no candidate at all
      (a true detection there cannot be recovered).

    Args:
        candidates: Candidates built *with* the cut-off.
        dep, med, obs: Loaded CamtrapDP tables.
        target_species, study_start, study_end, occasion_days, total_iterations,
            gap_seconds: Same values used to build ``candidates``.
        min_score: The general cut-off. When ``<= 0`` nothing is excluded for the
            species without their own.
        min_score_by_species: Per-species cut-offs that replace ``min_score``.

    Returns:
        One row per target species with ``species``, ``min_score`` (the cut-off that
        applied to it, 0 for none), ``excluded_photos``, ``excluded_events`` and
        ``excluded_cells`` (all 0 without a cut-off).
    """
    cutoffs = species_min_scores(target_species, min_score, min_score_by_species)
    zero = pd.DataFrame({
        "species": list(target_species),
        "min_score": [max(cutoffs[sp], 0.0) for sp in target_species],
        "excluded_photos": 0, "excluded_events": 0, "excluded_cells": 0,
    })
    if not any(v > 0 for v in cutoffs.values()):
        return zero
    full = build_candidates(
        dep, med, obs,
        target_species=target_species, study_start=study_start, study_end=study_end,
        occasion_days=occasion_days, total_iterations=total_iterations,
        gap_seconds=gap_seconds, include_burst_context=False, min_score=0.0, seed=seed,
        occasion_hours=occasion_hours, review_order=review_order,
    )
    if full.empty:
        return zero
    kept = candidates
    if not kept.empty and "is_context" in kept.columns:
        kept = kept[~kept["is_context"].astype(bool)]
    kept_keys = set(zip(kept["species_safe"], kept["mediaID"])) if not kept.empty else set()
    full = full.copy()
    full["_kept"] = [k in kept_keys for k in zip(full["species_safe"], full["mediaID"])]

    rows = []
    for sp in target_species:
        sub = full[full["scientificName"] == sp]
        ev = sub.groupby(["site_occasion_key", "burst_id"])["_kept"].any()
        cell = sub.groupby("site_occasion_key")["_kept"].any()
        rows.append({
            "species": sp,
            "min_score": max(cutoffs[sp], 0.0),
            "excluded_photos": int((~sub["_kept"]).sum()),
            "excluded_events": int((~ev).sum()),
            "excluded_cells":  int((~cell).sum()),
        })
    return pd.DataFrame(rows)


def rounds_completed(decisions_dir: Path) -> dict[str, int]:
    """Return ``species_safe`` -> highest completed round, from ``decisions_*_iter<N>.csv``."""
    done: dict[str, int] = {}
    if decisions_dir.exists():
        for f in decisions_dir.glob("decisions_*_iter*.csv"):
            m = re.match(r"decisions_(.+)_iter(\d+)\.csv", f.name)
            if m:
                done[m.group(1)] = max(done.get(m.group(1), 0), int(m.group(2)))
    return done


def has_tag(tags: pd.Series, tag: str) -> pd.Series:
    """True where the ``|``-separated ``observationTags`` contain ``tag``."""
    pattern = r"(?:^|\|)\s*" + re.escape(tag) + r"\s*(?:\||$)"
    return tags.fillna("").astype(str).str.contains(pattern, regex=True)


def _effort_accumulate(sp_df: pd.DataFrame, conf_ids: set, unc_ids: set, done: Optional[int], acc: dict) -> dict:
    """Effort counters of one species, computed for all its cells at once (no per-cell loop).

    ``sp_df`` holds the species' candidate rows (context frames already removed) with a numeric
    ``_score``. A cell is a *detection* when one of its photos is in ``conf_ids`` (its events up
    to the confirmed rank were inspected), otherwise every event up to round ``done`` was
    inspected (all of them when ``done`` is None). Same results as walking the cells one by one.
    """
    cell, burst = "site_occasion_key", "burst_id"
    ev = sp_df.groupby([cell, burst], sort=False).agg(rank=("rank", "first"), score=("_score", "max")).reset_index()
    cr = sp_df.loc[sp_df["observationID"].isin(conf_ids)].groupby(cell)["rank"].min()
    n_unc = sp_df.loc[sp_df["observationID"].isin(unc_ids)].groupby(cell)[burst].nunique()

    ev["cr"] = ev[cell].map(cr)
    det_ev = ev["cr"].notna()
    limit = ev["cr"].where(det_ev, float("inf") if done is None else float(done))
    ev["seen"] = ev["rank"] <= limit

    per_cell = ev.groupby(cell, sort=False).agg(n_ev=("rank", "size"), n_seen=("seen", "sum"))
    det_cells = pd.Series(per_cell.index.isin(cr.index), index=per_cell.index)
    unv_cells = ~det_cells & (per_cell["n_seen"] < per_cell["n_ev"])
    non_cells = ~det_cells & ~unv_cells
    unc_per_cell = n_unc.reindex(per_cell.index).fillna(0)

    acc["events"] += len(ev)
    acc["photos"] += len(sp_df)
    acc["unc"] += int(unc_per_cell.sum())
    acc["det"] += int(det_cells.sum())
    acc["unv"] += int(unv_cells.sum())
    acc["non"] += int(non_cells.sum())
    acc["unc_cells"] += int((non_cells & (unc_per_cell > 0)).sum())
    acc["insp"] += int(ev["seen"].sum())
    acc["insp_det"] += int((ev["seen"] & det_ev).sum())
    acc["insp_non"] += int((ev["seen"] & ~det_ev).sum())

    before = det_ev & (ev["rank"] < ev["cr"])
    acc["before"] += ev.loc[before].groupby(cell).size().reindex(per_cell.index[det_cells], fill_value=0).tolist()
    acc["rej_scores"] += ev.loc[before | (~det_ev & ev["seen"]), "score"].dropna().tolist()
    acc["conf_scores"] += ev.loc[det_ev & (ev["rank"] == ev["cr"]), "score"].dropna().tolist()

    # photos of the inspected events: rows whose burst holds a photo at an inspected rank of its cell
    seen_ranks = ev.loc[ev["seen"], [cell, "rank"]].drop_duplicates().assign(_hit=True)
    rows = sp_df[[cell, burst, "rank"]].merge(seen_ranks, on=[cell, "rank"], how="left")
    rows["_hit"] = rows["_hit"].fillna(False).astype(bool)
    in_seen_burst = rows.groupby([cell, burst], sort=False)["_hit"].transform("max")
    acc["photos_insp"] += int(in_seen_burst.sum())
    return acc


def build_species_effort(
    candidates: pd.DataFrame,
    decisions_dir: Path,
    out_dir: Path,
    rounds_done: Optional[dict[str, int]] = None,
    exclusions: Optional[pd.DataFrame] = None,
    review_log: Optional[pd.DataFrame] = None,
    idle_seconds: int = 120,
) -> pd.DataFrame:
    """Generate ``effort_report.csv``: verification effort per species plus a total row.

    "Inspecting" a detection event means viewing its top-scoring photo, so
    ``photos_inspected`` equals ``events_inspected``; ``photos_in_inspected_events``
    counts every photo of those events for readers who review whole events.

    Columns (one row per species, then ``TOTAL``):

    * ``candidate_cells``, ``cells_detection``, ``cells_non_detection``,
      ``cells_unverified``: cells = site x occasion. A cell is a detection when
      any of its events was confirmed, a non-detection when all its events were
      inspected and rejected, unverified while rounds remain.
    * ``candidate_events``, ``events_inspected``, ``pct_events_inspected``:
      the event-level baseline is a full review of ``candidate_events``.
    * ``candidate_photos``, ``photos_inspected``, ``photos_in_inspected_events``.
    * ``events_inspected_in_detection_cells`` / ``events_inspected_in_non_detection_cells``:
      effort split by cell outcome.
    * ``rejections_before_confirm_{mean,median,max}``: rejected events before
      the confirmed one, over detection cells.
    * ``rejected_score_{min,median,max}``: score of every rejected event.
    * ``confirmed_score_{min,median,max}``: score of the confirmed event.
    * ``unsure_events``: events the reviewer marked *unsure* (not counting any
      later confirmed). They behave exactly as rejections in the histories.
      ``non_detection_cells_with_unsure``: non-detection cells holding at least one.
    * ``review_active_seconds``, ``review_decisions_timed``,
      ``review_seconds_per_decision``, ``review_est_full_seconds``,
      ``review_est_saved_seconds``: active review time from the decision timestamps
      (see :func:`review_time_by_species`; pauses over ``idle_seconds`` are not
      counted) and an **estimate** of a full event-level review (candidate events
      x the session's mean seconds per decision) and of the time saved. Empty for
      sessions without timestamps.
    * ``excluded_photos`` / ``excluded_events`` / ``excluded_cells``: what the
      ``min_score`` cut-off removed before review (see
      :func:`compute_min_score_exclusions`); empty when ``exclusions`` is not given.

    Args:
        candidates: Full candidate manifest DataFrame.
        decisions_dir: Directory containing decision CSVs.
        out_dir: Destination directory (created if absent).
        exclusions: Optional per-species output of
            :func:`compute_min_score_exclusions` to include in the report.
        review_log: Optional ``review_log.csv`` contents for the review-time columns.
        idle_seconds: Pause length (s) above which time between decisions is idle.
        rounds_done: Optional ``species_safe`` -> completed rounds. When given,
            a cell with no confirmation whose events are not all inspected yet
            is ``cells_unverified`` and only events of rank <= rounds count as
            effort. When omitted every non-confirmed cell is a non-detection.

    Returns:
        The DataFrame written to disk.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dec = load_all_decisions(decisions_dir) if decisions_dir.exists() else pd.DataFrame()
    conf_ids = set(dec["observationID"].dropna()) if not dec.empty else set()

    unc = load_all_unsure(decisions_dir)
    unc_ids = set(unc["observationID"].dropna()) - conf_ids

    cand = candidates.copy()
    if "is_context" in cand.columns:
        cand = cand[~cand["is_context"].astype(bool)]
    cand["_score"] = pd.to_numeric(cand["classificationProbability"], errors="coerce")

    def stats(values: list[float], prefix: str, names=("min", "median", "max")) -> dict:
        s_ = pd.Series(values, dtype=float).dropna()
        fn = {"min": s_.min, "median": s_.median, "max": s_.max, "mean": s_.mean}
        return {f"{prefix}_{n}": (round(float(fn[n]()), 3) if not s_.empty else None) for n in names}

    def build_row(label: str, acc: dict) -> dict:
        n_cells = acc["det"] + acc["non"] + acc["unv"]
        row = {
            "species": label,
            "candidate_cells": n_cells,
            "cells_detection": acc["det"],
            "cells_non_detection": acc["non"],
            "cells_unverified": acc["unv"],
            "candidate_events": acc["events"],
            "events_inspected": acc["insp"],
            "pct_events_inspected": round(100 * acc["insp"] / acc["events"], 1) if acc["events"] else None,
            "candidate_photos": acc["photos"],
            "photos_inspected": acc["insp"],
            "unsure_events": acc["unc"],
            "non_detection_cells_with_unsure": acc["unc_cells"],
            "photos_in_inspected_events": acc["photos_insp"],
            "events_inspected_in_detection_cells": acc["insp_det"],
            "events_inspected_in_non_detection_cells": acc["insp_non"],
        }
        row.update(stats(acc["before"], "rejections_before_confirm", ("mean", "median", "max")))
        row.update(stats(acc["rej_scores"], "rejected_score"))
        row.update(stats(acc["conf_scores"], "confirmed_score"))
        return row

    def new_acc() -> dict:
        return {"det": 0, "non": 0, "unv": 0, "events": 0, "insp": 0, "photos": 0,
                "unc": 0, "unc_cells": 0,
                "photos_insp": 0, "insp_det": 0, "insp_non": 0,
                "before": [], "rej_scores": [], "conf_scores": []}

    total = new_acc()
    rows = []
    for sp_safe, sp_df in cand.groupby("species_safe", sort=True):
        done = None if rounds_done is None else rounds_done.get(str(sp_safe), 0)
        acc = _effort_accumulate(sp_df, conf_ids, unc_ids, done, new_acc())
        rows.append(build_row(sp_df["scientificName"].iloc[0], acc))
        for k, v in acc.items():
            total[k] = total[k] + v
    if exclusions is not None:
        # A species whose photos were all removed by the cut-off has no candidates, but it must
        # still appear (with its excluded counts) instead of vanishing from the report.
        present = {r["species"] for r in rows}
        for sp in exclusions["species"]:
            if sp not in present:
                rows.append(build_row(sp, new_acc()))
        rows.sort(key=lambda r: str(r["species"]))
    if rows:
        rows.append(build_row("TOTAL", total))
    df = pd.DataFrame(rows)
    rt = review_time_by_species(review_log if review_log is not None else pd.DataFrame(), idle_seconds)
    rate = rt["seconds"] / rt["credited"] if rt["credited"] else None
    tcols = ["review_active_seconds", "review_decisions_timed", "review_seconds_per_decision",
             "review_est_full_seconds", "review_est_saved_seconds"]
    for c in tcols:
        df[c] = None
    if rt["timed"] and not df.empty:
        for i, r in df.iterrows():
            tot = r["species"] == "TOTAL"
            d = {"seconds": rt["seconds"], "timed": rt["timed"]} if tot else rt["by_species"].get(r["species"])
            if d is None:
                continue
            est = round(rate * r["candidate_events"]) if rate is not None else None
            df.loc[i, "review_active_seconds"] = round(d["seconds"])
            df.loc[i, "review_decisions_timed"] = d["timed"]
            df.loc[i, "review_seconds_per_decision"] = round(rate, 1) if rate is not None else None
            df.loc[i, "review_est_full_seconds"] = est
            df.loc[i, "review_est_saved_seconds"] = round(est - d["seconds"]) if est is not None else None
    cols = ["excluded_photos", "excluded_events", "excluded_cells"]
    df["min_score"] = None
    if exclusions is not None and not df.empty:
        ex = exclusions.set_index("species")
        for c in cols:
            df[c] = df["species"].map(ex[c])
            df.loc[df["species"] == "TOTAL", c] = int(ex[c].sum())
        if "min_score" in ex.columns:                       # absent in sessions made before the report had it
            df["min_score"] = df["species"].map(ex["min_score"])
    else:
        for c in cols:
            df[c] = None
    df.to_csv(out_dir / "effort_report.csv", index=False)
    return df
