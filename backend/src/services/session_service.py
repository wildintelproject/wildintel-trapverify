"""
Session state management for CamTrap Verify.

Owns the in-memory cache, derives well-known paths, and handles
persistence (last_session.json) and startup rehydration.

All external code must use the public functions below; never access
_state directly from outside this module.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

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
            "target_species": config.get("target_species", []),
            "study_start":    config.get("study_start"),
            "study_end":      config.get("study_end"),
        })

    if len(valid) != len(entries):
        _write_recent([{"session_dir": v["session_dir"], "last_opened": v["last_opened"]} for v in valid])

    return valid


# ── Writers ───────────────────────────────────────────────────────────────────

def init_session(sd: Path, config: dict, candidates: pd.DataFrame) -> None:
    """Populate in-memory state for a newly created session."""
    _state["session_dir"] = sd
    _state["config"] = config
    _state["candidates"] = candidates
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
