"""
Session state management for CamTrap Verify.

Owns the in-memory cache, derives well-known paths, and handles
persistence (last_session.json) and startup rehydration.

All external code must use the public functions below; never access
_state directly from outside this module.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import HTTPException

from settings import settings

logger = logging.getLogger(__name__)

APP_DIR = settings.app_dir
SESSION_FILE = APP_DIR / "last_session.json"
RECENT_SESSIONS_FILE = APP_DIR / "recent_sessions.json"
MAX_RECENT_SESSIONS = 8
DEFAULT_OUTPUT_DIR = settings.default_output_dir

_state: dict = {}


# ── Readers ───────────────────────────────────────────────────────────────────

def session_dir() -> Path | None:
    return _state.get("session_dir")


def get_candidates() -> pd.DataFrame | None:
    return _state.get("candidates")


def get_config() -> dict | None:
    return _state.get("config")


def get_rejected_media() -> set[str]:
    return _state.get("rejected_media", set())


from camtrap_workflow import media_extra_bases  # noqa: E402,F401  (also the home of the helper the fork keeps here)


def get_resolver():
    """``MediaResolver`` of the active session: one listing per photo folder, kept while the session and
    where its photos are looked up stay the same (opening another session or relinking the folders makes a new one)."""
    config = get_config()
    if config is None:
        return None
    from camtrap_workflow import MediaResolver
    image_base_dir = config.get("image_base_dir", "") or ""
    camtrap_dir = config.get("camtrap_dir", "")
    flat_search = bool(config.get("flat_search", False))
    key = (str(session_dir()), camtrap_dir, image_base_dir, flat_search)
    cur = _state.get("_resolver")
    if cur is None or cur[0] != key:
        fallback = Path(image_base_dir) if image_base_dir else Path(camtrap_dir or ".")
        cur = (key, MediaResolver(image_base_dir, fallback, flat_search, media_extra_bases(camtrap_dir, image_base_dir)), {})
        _state["_resolver"] = cur
    return cur[1]


def resolve_image_path(media_id: str) -> Optional[Path]:
    """Local path of a candidate image by mediaID (None when the ID is unknown), remembered per resolver."""
    row = media_lookup(media_id)
    if row is None:
        return None
    resolver = get_resolver()
    cache = _state["_resolver"][2]
    if media_id not in cache:
        cache[media_id] = resolver.resolve(str(row["filePath"]), str(row.get("deploymentID", "")), str(row.get("fileName", "")))
    return cache[media_id]


def media_lookup(media_id: str) -> Optional[dict]:
    """``filePath`` / ``deploymentID`` / ``fileName`` of a media file, from an in-memory index.

    Built once per loaded manifest (a pandas scan of every candidate per image request does not
    scale to archives of millions of rows). The first row of a mediaID wins, as before.
    """
    candidates = get_candidates()
    if candidates is None:
        return None
    idx = _state.get("_media_index")
    if idx is None or idx[0] is not candidates:
        first = candidates.drop_duplicates("mediaID")
        cols = [c for c in ("filePath", "deploymentID", "fileName") if c in first.columns]
        records = first[["mediaID"] + cols].to_dict("records")
        idx = (candidates, {str(r["mediaID"]): r for r in records})
        _state["_media_index"] = idx
    return idx[1].get(media_id)


def observation_boxes(observation_id: str) -> Optional[str]:
    """Raw ``bboxes`` text of an observation (None when it has none), from an in-memory index."""
    candidates = get_candidates()
    if candidates is None or "bboxes" not in candidates.columns:
        return None
    idx = _state.get("_box_index")
    if idx is None or idx[0] is not candidates:
        with_boxes = candidates[candidates["bboxes"].notna() & (candidates["bboxes"].astype(str) != "")]
        with_boxes = with_boxes.drop_duplicates("observationID")
        idx = (candidates, dict(zip(with_boxes["observationID"].astype(str), with_boxes["bboxes"])))
        _state["_box_index"] = idx
    return idx[1].get(observation_id)


def image_token() -> str:
    """Short per-session token for image URLs (``?v=``): it changes when the session or where its
    photos are looked up changes, so a browser can keep the photos of a session cached."""
    import hashlib
    config = get_config() or {}
    raw = "|".join(str(x) for x in (
        session_dir(), config.get("camtrap_dir", ""), config.get("image_base_dir", ""), config.get("flat_search", False),
    ))
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def paths() -> dict[str, Path]:
    """Return well-known paths for the active session.

    Raises:
        HTTPException: 400 if no session is currently active.
    """
    sd = session_dir()
    if sd is None:
        raise HTTPException(400, "No hay sesión activa. POST /api/setup primero.")
    return {
        "config":        sd / "config.json",
        "manifest":      sd / "candidate_manifest.csv",
        "exclusions":    sd / "min_score_exclusions.csv",
        "corrections":   sd / "rejection_corrections.csv",
        "review_log":    sd / "review_log.csv",
        "rejected":      sd / "rejected_media.json",
        "decisions":     sd / "decisions",
        "camtrap_out":   sd / "camtrap_dp_verified",
        "occupancy_out": sd / "occupancy_inputs",
    }


def list_recent_sessions() -> list[dict]:
    """List recently opened sessions still valid on disk, most recent first.

    Entries whose directory or config.json have since disappeared are
    silently dropped and pruned from the persisted list.
    """
    entries = _read_recent()
    valid: list[dict] = []
    for entry in entries:
        cfg_file = Path(entry["session_dir"]) / "config.json"
        try:
            config = json.loads(cfg_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        valid.append({
            "session_dir":    entry["session_dir"],
            "last_opened":    entry["last_opened"],
            "session_name":   config.get("session_name", "") or "",
            "target_species": config.get("target_species", []),
            "study_start":    config.get("study_start"),
            "study_end":      config.get("study_end"),
        })

    if len(valid) != len(entries):
        _write_recent([{"session_dir": v["session_dir"], "last_opened": v["last_opened"]} for v in valid])

    return valid


# ── Writers ───────────────────────────────────────────────────────────────────

def clean_session_name(name: str) -> str:
    """A session name with its whitespace collapsed (an empty name means "no name")."""
    return " ".join((name or "").split())


def write_config_file(cfg_file: Path, config: dict) -> None:
    """Write ``config.json`` whole or not at all (temp file, then replace)."""
    tmp = cfg_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.replace(cfg_file)


def update_paths(camtrap_dir: str, image_base_dir: str, flat_search: bool) -> None:
    """Point the active session at its data and image folders on this computer."""
    config = get_config()
    sd = session_dir()
    if config is None or sd is None:
        raise HTTPException(400, "No hay sesión activa.")
    config["camtrap_dir"] = camtrap_dir
    config["image_base_dir"] = image_base_dir
    config["flat_search"] = flat_search
    write_config_file(sd / "config.json", config)
    from camtrap_workflow import clear_media_caches
    clear_media_caches()                                    # listings of the old folders are stale
    _state.pop("_resolver", None)
    logger.info("Session relinked: camtrap_dir=%s image_base_dir=%s flat=%s", camtrap_dir, image_base_dir, flat_search)


def relink_status() -> dict:
    """Whether the session's data and image folders are reachable on this computer.

    A session opened on another computer (or after moving the data) keeps the original absolute
    paths; the frontend uses this to ask for the right folders before anything needs them.
    """
    from camtrap_workflow import (
        MediaResolver, is_remote_path, media_extra_bases, resolve_camtrapdp_resource,
    )

    config = get_config() or {}
    camtrap_dir = config.get("camtrap_dir", "")
    image_base_dir = config.get("image_base_dir", "") or ""
    camtrap_ok = bool(camtrap_dir) and resolve_camtrapdp_resource(Path(camtrap_dir), "observations") is not None
    image_dir_ok = (not image_base_dir) or Path(image_base_dir).is_dir()

    # A few candidate photos: catches absolute filePaths from another computer even when no
    # images folder is configured. Remote addresses are skipped (they are fetched on demand).
    sample_ok: Optional[bool] = None
    candidates = _state.get("candidates")
    if candidates is not None and not candidates.empty and camtrap_ok and image_dir_ok:
        sample = candidates.drop_duplicates("mediaID")
        sample = sample[~sample["filePath"].astype(str).map(is_remote_path)].head(10)
        if len(sample):
            fallback = Path(image_base_dir) if image_base_dir else Path(camtrap_dir)
            resolver = MediaResolver(
                image_base_dir, fallback, bool(config.get("flat_search", False)),
                media_extra_bases(camtrap_dir, image_base_dir),
            )
            found = 0
            for r in sample.itertuples():
                path = resolver.resolve(str(r.filePath), str(getattr(r, "deploymentID", "")), str(getattr(r, "fileName", "")))
                if path.is_file():
                    found += 1
            sample_ok = found > 0
    images_ok = image_dir_ok and sample_ok is not False
    return {
        "camtrap_dir_ok": camtrap_ok,
        "images_ok": images_ok,
        "needs_relink": not (camtrap_ok and images_ok),
        "camtrap_dir": camtrap_dir,
        "image_base_dir": image_base_dir,
        "flat_search": bool(config.get("flat_search", False)),
    }


def auto_relink() -> dict:
    """If the active session's data is missing, reuse the folder of another local session on the same dataset."""
    status = relink_status()
    config = get_config() or {}
    fp = config.get("dataset_fingerprint")
    if not status["needs_relink"] or not fp:
        return status
    from camtrap_workflow import dataset_fingerprint

    current = session_dir()
    for entry in _read_recent():
        other = Path(entry.get("session_dir", ""))
        if current is not None and other == current:
            continue
        try:
            other_cfg = json.loads((other / "config.json").read_text())
        except (OSError, ValueError):
            continue
        cdir = other_cfg.get("camtrap_dir", "")
        if cdir and Path(cdir).is_dir() and dataset_fingerprint(Path(cdir)) == fp:
            update_paths(cdir, other_cfg.get("image_base_dir", "") or "", bool(other_cfg.get("flat_search", False)))
            return relink_status()
    return status


def rename_session(session_dir: str, name: str) -> dict:
    """Set (or clear, with an empty name) the name of a session.

    Only the active session or one in the recent-sessions list can be renamed, so this
    cannot be used to write ``config.json`` files elsewhere; the name is stored as
    ``session_name`` in the session's own ``config.json``.
    """
    active = _state.get("session_dir")
    target = Path(session_dir) if session_dir else active
    if target is None:
        raise HTTPException(400, "No hay sesión activa.")
    known = {os.path.normcase(str(Path(e["session_dir"]))) for e in _read_recent()}
    if active is not None:
        known.add(os.path.normcase(str(Path(active))))
    if os.path.normcase(str(Path(target))) not in known:
        raise HTTPException(400, f"No es una sesión conocida: {target}")
    cfg_file = Path(target) / "config.json"
    try:
        config = json.loads(cfg_file.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"No se puede leer {cfg_file}: {exc}") from exc
    clean = clean_session_name(name)
    config["session_name"] = clean
    write_config_file(cfg_file, config)
    if active is not None and os.path.normcase(str(Path(active))) == os.path.normcase(str(Path(target))):
        current = _state.get("config")
        if current is not None:
            current["session_name"] = clean
    logger.info("Session %s renamed to %r", target, clean)
    return {"session_dir": str(target), "session_name": clean}


def init_session(sd: Path, config: dict, candidates: pd.DataFrame) -> None:
    """Populate in-memory state for a newly created session."""
    _state["session_dir"] = sd
    _state["config"] = config
    _state["candidates"] = candidates
    _state.pop("_resolver", None)                             # a new session: new listings of the photo folders
    _state["rejected_media"] = set()
    _record_recent(sd)
    logger.info("Session initialized: %s (%d candidates)", sd, len(candidates))


def _read_recent() -> list[dict]:
    if not RECENT_SESSIONS_FILE.exists():
        return []
    try:
        return json.loads(RECENT_SESSIONS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _write_recent(entries: list[dict]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    RECENT_SESSIONS_FILE.write_text(json.dumps(entries))


def _record_recent(sd: Path) -> None:
    """Move sd to the front of the recent-sessions list, capped at MAX_RECENT_SESSIONS."""
    entries = [e for e in _read_recent() if e["session_dir"] != str(sd)]
    entries.insert(0, {"session_dir": str(sd), "last_opened": datetime.now().isoformat()})
    _write_recent(entries[:MAX_RECENT_SESSIONS])


def add_rejected_media(media_ids: list[str]) -> set[str]:
    """Add IDs to the rejected set, persist to disk, return the updated set."""
    rm = _state.setdefault("rejected_media", set())
    rm.update(media_ids)
    _persist_rejected(rm)
    logger.info("Rejected %d media IDs (total rejected: %d)", len(media_ids), len(rm))
    return rm


def discard_rejected_media(media_ids: list[str]) -> None:
    """Remove IDs from the rejected set and persist to disk."""
    rm = _state.get("rejected_media", set())
    for m in media_ids:
        rm.discard(m)
    _state["rejected_media"] = rm
    _persist_rejected(rm)
    logger.info("Unrejected %d media IDs (total rejected: %d)", len(media_ids), len(rm))


def _persist_rejected(rm: set[str]) -> None:
    sd = session_dir()
    if sd is None:
        return
    (sd / "rejected_media.json").write_text(json.dumps(list(rm)))


# ── Persistence / startup ─────────────────────────────────────────────────────

def load_from_dir(sd: Path) -> None:
    """Load an existing session directory into memory and update the session pointer.

    Raises:
        HTTPException: 400 if the directory is not a valid session.
    """
    logger.info("Loading session from %s", sd)
    cfg_file = sd / "config.json"
    manifest = sd / "candidate_manifest.csv"
    if not cfg_file.exists() or not manifest.exists():
        logger.warning("Invalid session directory (missing config or manifest): %s", sd)
        raise HTTPException(400, f"No es una sesión válida: faltan config.json o candidate_manifest.csv en {sd}")

    _state["session_dir"] = sd
    _state["config"] = json.loads(cfg_file.read_text())
    _state.pop("_resolver", None)
    _state["candidates"] = pd.read_csv(
        manifest,
        dtype={"mediaID": str, "observationID": str},
        parse_dates=["ts"],
    )
    rejected_file = sd / "rejected_media.json"
    _state["rejected_media"] = (
        set(json.loads(rejected_file.read_text()))
        if rejected_file.exists()
        else set()
    )
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps({"session_dir": str(sd)}))
    _record_recent(sd)
    logger.info(
        "Session loaded: %s (%d candidates, %d rejected)",
        sd, len(_state["candidates"]), len(_state["rejected_media"]),
    )


def reload() -> None:
    """Restore the last active session from disk into memory."""
    if not SESSION_FILE.exists():
        logger.debug("No previous session file found at %s", SESSION_FILE)
        return
    data = json.loads(SESSION_FILE.read_text())
    sd = Path(data["session_dir"])
    cfg_file = sd / "config.json"
    if not cfg_file.exists():
        logger.warning("Last session dir no longer valid (missing config): %s", sd)
        return
    logger.info("Rehydrating last session from %s", sd)

    _state["session_dir"] = sd
    _state["config"] = json.loads(cfg_file.read_text())

    manifest = sd / "candidate_manifest.csv"
    if manifest.exists():
        try:
            _state["candidates"] = pd.read_csv(
                manifest,
                dtype={"mediaID": str, "observationID": str},
                parse_dates=["ts"],
            )
        except Exception as exc:
            logger.warning("Could not load candidate manifest (%s): %s — skipping session", type(exc).__name__, sd)
            _state.clear()
            return

    rejected_file = sd / "rejected_media.json"
    _state["rejected_media"] = (
        set(json.loads(rejected_file.read_text()))
        if rejected_file.exists()
        else set()
    )


def on_startup() -> None:
    """FastAPI lifespan hook — rehydrate in-memory state from the last saved session."""
    reload()
