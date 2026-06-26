"""
CamTrap Verify — FastAPI backend.

Exposes the REST API consumed by the React frontend. Manages a single active
session (persisted to disk) and delegates all workflow logic to camtrap_workflow.
"""
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from settings import configure_logging, settings

from camtrap_workflow import (
    build_candidates,
    build_occupancy_inputs,
    build_review_effort,
    confirmed_keys_set,
    export_verified_camtrapdp,
    get_events,
    get_review_events,
    load_all_decisions,
    load_camtrapdp,
    save_decisions,
    species_stats,
)

configure_logging()

app = FastAPI(title="Camera Trap Verification API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

APP_DIR = settings.app_dir
SESSION_FILE = APP_DIR / "last_session.json"
DEFAULT_OUTPUT_DIR = settings.default_output_dir

# In-memory cache — rebuilt from files on startup
_state: dict = {}


# ─── Helpers de sesión ────────────────────────────────────────────────────────

def _session_dir() -> Path | None:
    """Return the active session directory.

    Returns:
        Absolute path to the current session directory, or ``None`` if no
        session has been loaded yet.
    """
    return _state.get("session_dir")


def _paths() -> dict[str, Path]:
    """Return well-known paths derived from the active session directory.

    Raises:
        HTTPException: 400 if no session is currently active.

    Returns:
        Dict with keys ``config``, ``manifest``, ``rejected``, ``decisions``,
        ``camtrap_out`` and ``occupancy_out``, each mapped to an absolute
        ``Path``.
    """
    sd = _session_dir()
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


def _reload() -> None:
    """Restore the last active session from disk into ``_state``.

    Reads ``SESSION_FILE`` to find the session directory, then loads
    ``config.json``, ``candidate_manifest.csv`` and ``rejected_media.json``
    into memory. Silently returns if no session file exists or if the
    referenced session directory is missing.
    """
    if not SESSION_FILE.exists():
        return
    data = json.loads(SESSION_FILE.read_text())
    sd = Path(data["session_dir"])
    cfg_file = sd / "config.json"
    if not cfg_file.exists():
        return

    _state["session_dir"] = sd
    _state["config"] = json.loads(cfg_file.read_text())

    manifest = sd / "candidate_manifest.csv"
    if manifest.exists():
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


@app.on_event("startup")
def startup() -> None:
    """FastAPI lifespan hook — rehydrate in-memory state from the last saved session."""
    _reload()


# ─── Pydantic models ──────────────────────────────────────────────────────────

class SetupRequest(BaseModel):
    camtrap_dir: str
    output_dir: str = ""
    target_species: list[str]
    study_start: str
    study_end: str
    occasion_days: int = 5
    total_iterations: int = 100000
    gap_seconds: int = 60
    min_score: float = 0.5


class DecisionsRequest(BaseModel):
    species: str
    iteration: int
    confirmed: list[str]


class RejectRequest(BaseModel):
    mediaId: str


class UnrejectRequest(BaseModel):
    media: list[str]


class ReviewDecisionsRequest(BaseModel):
    confirmed_keys: list[str]


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict:
    """Health check endpoint.

    Returns:
        Dict ``{"status": "ok"}``.
    """
    return {"status": "ok"}


# ─── Filesystem browser ───────────────────────────────────────────────────────

@app.get("/api/fs/inspect")
def fs_inspect(path: str) -> dict:
    """Inspect a CamtrapDP directory.

    Reads ``observations.csv`` to list animal species and (optionally)
    ``media.csv`` to determine the timestamp range of the dataset.

    Args:
        path: Absolute path to the directory containing ``observations.csv``
            and (optionally) ``media.csv``.

    Raises:
        HTTPException: 400 if ``observations.csv`` is not found at ``path``.

    Returns:
        Dict with keys:

        * ``species``: Sorted list of animal ``scientificName`` values.
        * ``study_start``: ISO date string of the earliest media timestamp,
          or ``None`` if ``media.csv`` is absent.
        * ``study_end``: ISO date string of the latest media timestamp,
          or ``None``.
    """
    p = Path(path)
    obs_file = p / "observations.csv"
    med_file = p / "media.csv"

    if not obs_file.exists():
        raise HTTPException(400, f"No se encontró observations.csv en {path}")

    obs = pd.read_csv(obs_file, dtype=str)
    species = sorted(
        obs.loc[
            (obs.get("observationType", pd.Series()) == "animal")
            & obs["scientificName"].notna()
            & (obs["scientificName"] != ""),
            "scientificName",
        ].unique().tolist()
    )

    start_date, end_date = None, None
    if med_file.exists():
        from camtrap_workflow import normalise_ts
        med = pd.read_csv(med_file, dtype=str)
        ts = pd.to_datetime(
            med["timestamp"].apply(normalise_ts), errors="coerce", utc=False
        ).dropna()
        if not ts.empty:
            start_date = ts.min().date().isoformat()
            end_date = ts.max().date().isoformat()

    return {"species": species, "study_start": start_date, "study_end": end_date}


@app.get("/api/fs/browse")
def fs_browse(path: str = "") -> dict:
    """Return subdirectories of ``path`` for the filesystem picker.

    Hidden directories (names starting with ``'.'``) and unreadable paths are
    excluded. If the requested path does not exist, the function climbs to the
    nearest existing ancestor.

    Args:
        path: Absolute path to browse. Defaults to ``$HOME`` when empty.

    Raises:
        HTTPException: 403 if the directory cannot be read due to permissions.

    Returns:
        Dict with keys:

        * ``current``: Absolute path that was actually browsed.
        * ``parent``: Absolute path of the parent directory, or ``None`` at
          the filesystem root.
        * ``dirs``: List of ``{"name": str, "path": str}`` dicts, sorted
          case-insensitively.
    """
    p = Path(path).resolve() if path else Path.home()
    # Si el directorio no existe, subir al primer padre existente
    while not p.exists() or not p.is_dir():
        parent = p.parent
        if parent == p:          # raíz del sistema de ficheros
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
        raise HTTPException(403, "Sin permiso de acceso")


# ─── State ────────────────────────────────────────────────────────────────────

@app.get("/api/state")
def get_state() -> dict:
    """Return the current session state.

    Returns:
        Dict always containing ``ready`` (bool) and ``default_output_dir``
        (str). When ``ready`` is ``True``, also includes ``config`` (the
        session config dict) and ``session_dir`` (str).
    """
    if "config" not in _state:
        return {
            "ready": False,
            "default_output_dir": str(DEFAULT_OUTPUT_DIR),
        }
    return {
        "ready": True,
        "config": _state["config"],
        "default_output_dir": str(DEFAULT_OUTPUT_DIR),
        "session_dir": str(_session_dir()),
    }


# ─── Setup ────────────────────────────────────────────────────────────────────

@app.post("/api/setup")
def setup(req: SetupRequest) -> dict:
    """Create a new verification session.

    Loads the CamtrapDP dataset, builds the ranked candidate manifest, writes
    all session files to a timestamped subdirectory, and generates initial
    (empty) output files.

    Args:
        req: Setup parameters — CamtrapDP directory, output directory, target
            species, study period, sampling parameters.

    Raises:
        HTTPException: 400 if ``camtrap_dir`` does not exist.

    Returns:
        Dict with keys ``ok`` (True), ``session_dir`` (str),
        ``n_candidates`` (int) and ``n_combos`` (int).
    """
    camtrap_dir = Path(req.camtrap_dir)
    if not camtrap_dir.exists():
        raise HTTPException(400, f"camtrap_dir no encontrado: {camtrap_dir}")

    dep, med, obs = load_camtrapdp(camtrap_dir)
    candidates = build_candidates(
        dep, med, obs,
        target_species=req.target_species,
        study_start=date.fromisoformat(req.study_start),
        study_end=date.fromisoformat(req.study_end),
        occasion_days=req.occasion_days,
        total_iterations=req.total_iterations,
        gap_seconds=req.gap_seconds,
    )

    # Crear directorio de sesión con timestamp
    base_out = Path(req.output_dir) if req.output_dir else DEFAULT_OUTPUT_DIR
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    session_dir = base_out / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)

    config = req.model_dump()
    config["camtrap_dir"] = str(camtrap_dir.resolve())
    config["output_dir"] = str(base_out)
    config["session_dir"] = str(session_dir)

    (session_dir / "config.json").write_text(json.dumps(config, indent=2))
    candidates.to_csv(session_dir / "candidate_manifest.csv", index=False)

    # Guardar puntero a la sesión activa
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps({"session_dir": str(session_dir)}))

    _state["session_dir"] = session_dir
    _state["config"] = config
    _state["candidates"] = candidates
    _state["rejected_media"] = set()

    # Exportar salidas iniciales (sin decisiones aún)
    export_verified_camtrapdp(
        camtrap_dir, session_dir / "camtrap_dp_verified",
        session_dir / "decisions", set(),
    )
    build_occupancy_inputs(
        candidates, session_dir / "decisions", config, session_dir / "occupancy_inputs",
    )
    build_review_effort(
        candidates, session_dir / "decisions", config, session_dir / "occupancy_inputs",
    )

    return {
        "ok": True,
        "session_dir": str(session_dir),
        "n_candidates": len(candidates),
        "n_combos": int(candidates["site_occasion_key"].nunique()),
    }


# ─── Species ──────────────────────────────────────────────────────────────────

@app.get("/api/species")
def list_species() -> list[dict]:
    """Return per-species progress statistics and thumbnail URLs.

    Computes total/confirmed/resolved combo counts and the current round for
    each species in the candidate manifest, then appends up to four thumbnail
    URLs for the index page cards.

    Raises:
        HTTPException: 400 if the workflow has not been initialized.

    Returns:
        List of species dicts (see :func:`~camtrap_workflow.species_stats`)
        each extended with a ``thumbnails`` key (list of ``/api/image/<id>``
        URL strings).
    """
    if "candidates" not in _state:
        raise HTTPException(400, "Workflow not initialized. POST /api/setup first.")
    p = _paths()
    p["decisions"].mkdir(parents=True, exist_ok=True)
    stats = species_stats(
        _state["candidates"],
        p["decisions"],
        _state["config"]["total_iterations"],
    )
    cands = _state["candidates"]
    for sp in stats:
        media_ids = (
            cands[cands["species_safe"] == sp["species_safe"]]
            ["mediaID"]
            .drop_duplicates()
            .head(4)
            .tolist()
        )
        sp["thumbnails"] = [f"/api/image/{mid}" for mid in media_ids]
    return stats


@app.get("/api/species/{species_safe}/events")
def get_species_events(species_safe: str, iteration: int = 1) -> list[dict]:
    """Return pending gallery events for a species in a given verification round.

    Args:
        species_safe: Sanitized species name (URL path segment).
        iteration: Round number to fetch (equals the burst rank to show).
            Defaults to 1.

    Raises:
        HTTPException: 400 if the workflow has not been initialized.

    Returns:
        List of event dicts (see :func:`~camtrap_workflow.get_events`).
    """
    if "candidates" not in _state:
        raise HTTPException(400, "Workflow not initialized.")
    p = _paths()
    p["decisions"].mkdir(parents=True, exist_ok=True)
    return get_events(
        _state["candidates"],
        p["decisions"],
        _state.get("rejected_media", set()),
        species_safe,
        iteration,
    )


@app.get("/api/species/{species_safe}/review")
def get_species_review(species_safe: str) -> list[dict]:
    """Return all cells for a completed species with their confirmation status.

    Used by the locked review screen so the expert can audit or correct
    decisions without starting a new session.

    Args:
        species_safe: Sanitized species name (URL path segment).

    Raises:
        HTTPException: 400 if the workflow has not been initialized.

    Returns:
        List of event dicts (see :func:`~camtrap_workflow.get_review_events`),
        each including a ``status`` field (``'confirmed'`` or
        ``'not_confirmed'``). Empty list if the species is not in the manifest.
    """
    if "candidates" not in _state:
        raise HTTPException(400, "Workflow not initialized.")
    p = _paths()
    sp_cands = _state["candidates"][_state["candidates"]["species_safe"] == species_safe]
    if sp_cands.empty:
        return []
    return get_review_events(sp_cands, p["decisions"])


@app.put("/api/species/{species_safe}/decisions")
def update_species_decisions(species_safe: str, req: ReviewDecisionsRequest) -> dict:
    """Replace all decisions for a species with a corrected set, then regenerate outputs.

    Clears all existing ``decisions_{species_safe}_iter*.csv`` files, writes a
    fresh ``iter1.csv`` from the supplied confirmed keys (using the rank-1
    representative observation per key), and regenerates the verified CamtrapDP
    and all occupancy-model input files.

    Args:
        species_safe: Sanitized species name (URL path segment).
        req: Request body containing ``confirmed_keys`` — list of
            ``site_occasion_key`` values to mark as confirmed.

    Raises:
        HTTPException: 400 if the workflow has not been initialized.

    Returns:
        Dict with keys ``success`` (True) and ``confirmed`` (int count of
        keys saved).
    """
    if "candidates" not in _state:
        raise HTTPException(400, "Workflow not initialized.")
    p = _paths()
    p["decisions"].mkdir(parents=True, exist_ok=True)
    cands = _state["candidates"]
    sp_cands = cands[cands["species_safe"] == species_safe]

    # Borrar decisiones anteriores de esta especie
    for f in p["decisions"].glob(f"decisions_{species_safe}_iter*.csv"):
        f.unlink()

    if req.confirmed_keys:
        rank1 = sp_cands[sp_cands["rank"] == 1]
        confirmed_rows = []
        for key in req.confirmed_keys:
            key_cands = rank1[rank1["site_occasion_key"] == key]
            if not key_cands.empty:
                prob_col = pd.to_numeric(
                    key_cands["classificationProbability"], errors="coerce"
                ).fillna(0)
                rep_idx = prob_col.idxmax()
                confirmed_rows.append(key_cands.loc[rep_idx])
        if confirmed_rows:
            cols = ["observationID", "site_occasion_key", "mediaID",
                    "scientificName", "siteID", "occasion"]
            df = pd.DataFrame(confirmed_rows)[cols]
            path = p["decisions"] / f"decisions_{species_safe}_iter1.csv"
            df.to_csv(path, index=False)

    rejected = _state.get("rejected_media", set())
    export_verified_camtrapdp(
        Path(_state["config"]["camtrap_dir"]), p["camtrap_out"], p["decisions"], rejected,
    )
    build_occupancy_inputs(cands, p["decisions"], _state["config"], p["occupancy_out"])
    build_review_effort(cands, p["decisions"], _state["config"], p["occupancy_out"])

    return {"success": True, "confirmed": len(req.confirmed_keys)}


# ─── Decisions ────────────────────────────────────────────────────────────────

@app.get("/api/decisions")
def get_decisions_endpoint(species: str, iteration: int) -> dict:
    """Return confirmed ``observationID`` values for a species and round.

    Used by the gallery to restore UI state on page reload without re-fetching
    all events.

    Args:
        species: Sanitized species name.
        iteration: Round number.

    Returns:
        Dict with key ``confirmed`` — list of ``observationID`` strings, or an
        empty list if no decision file exists for that round.
    """
    p = _paths()
    path = p["decisions"] / f"decisions_{species}_iter{iteration}.csv"
    if not path.exists():
        return {"confirmed": []}
    df = pd.read_csv(path, dtype=str)
    return {"confirmed": df["observationID"].tolist()}


@app.post("/api/decisions")
def post_decisions(req: DecisionsRequest) -> dict:
    """Save confirmed observations for one round and regenerate all output files.

    Persists the expert's decisions, checks whether a subsequent round is
    needed (i.e. unconfirmed cells still have a next-rank candidate), and
    regenerates the verified CamtrapDP and occupancy-model inputs.

    Args:
        req: Body containing ``species`` (sanitized name), ``iteration``
            (round number) and ``confirmed`` (list of ``observationID`` strings).

    Raises:
        HTTPException: 400 if the workflow has not been initialized.

    Returns:
        Dict with keys:

        * ``success``: True.
        * ``saved``: Number of confirmed IDs written.
        * ``done``: True if no further rounds are needed.
        * ``next_iteration``: Next round number, or ``None`` when done.
        * ``remaining``: Number of unresolved cells in the next round, or 0
          when done.
    """
    if "candidates" not in _state:
        raise HTTPException(400, "Workflow not initialized.")
    p = _paths()
    p["decisions"].mkdir(parents=True, exist_ok=True)

    save_decisions(p["decisions"], _state["candidates"], req.species, req.iteration, req.confirmed)

    conf_keys = confirmed_keys_set(p["decisions"])
    rejected = _state.get("rejected_media", set())
    cands = _state["candidates"]
    next_iter = req.iteration + 1
    next_cands = cands[
        (cands["species_safe"] == req.species)
        & (cands["rank"] == next_iter)
        & (~cands["site_occasion_key"].isin(conf_keys))
        & (~cands["mediaID"].isin(rejected))
    ]
    done = len(next_cands) == 0 or next_iter > _state["config"]["total_iterations"]

    # Actualizar todas las salidas tras cada guardado
    export_verified_camtrapdp(
        Path(_state["config"]["camtrap_dir"]),
        p["camtrap_out"],
        p["decisions"],
        rejected,
    )
    build_occupancy_inputs(
        _state["candidates"], p["decisions"], _state["config"], p["occupancy_out"],
    )
    build_review_effort(
        _state["candidates"], p["decisions"], _state["config"], p["occupancy_out"],
    )

    return {
        "success": True,
        "saved": len(req.confirmed),
        "done": done,
        "next_iteration": next_iter if not done else None,
        "remaining": int(next_cands["site_occasion_key"].nunique()) if not done else 0,
    }


# ─── Images ───────────────────────────────────────────────────────────────────

@app.get("/api/image/{media_id}")
def serve_image(media_id: str) -> FileResponse:
    """Serve a camera-trap image from the local filesystem.

    Looks up the file path via ``mediaID`` in the candidate manifest.

    Args:
        media_id: ``mediaID`` value from the candidate manifest.

    Raises:
        HTTPException: 404 if no data is loaded, the media ID is unknown, or
            the file is not present on disk.

    Returns:
        :class:`~fastapi.responses.FileResponse` streaming the image file.
    """
    if "candidates" not in _state:
        raise HTTPException(404, "No data loaded")
    row = _state["candidates"][_state["candidates"]["mediaID"] == media_id]
    if row.empty:
        raise HTTPException(404, f"Media {media_id} not found")
    file_path = Path(str(row.iloc[0]["filePath"]))
    if not file_path.exists():
        raise HTTPException(404, f"File not found: {file_path}")
    return FileResponse(str(file_path))


@app.get("/api/proxy-image")
async def proxy_image(url: str) -> Response:
    """Proxy a remote image URL to bypass browser CORS restrictions.

    Useful when the CamtrapDP references images hosted on an external platform
    (e.g. the Trapper platform).

    Args:
        url: Full URL of the remote image to fetch.

    Returns:
        :class:`~fastapi.Response` with the image bytes and the original
        ``Content-Type`` header (defaults to ``image/jpeg``).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=30)
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/jpeg"),
    )


# ─── Reject burst ─────────────────────────────────────────────────────────────

@app.get("/api/rejected")
def get_rejected() -> dict:
    """Return the set of manually rejected ``mediaID`` values for the active session.

    Returns:
        Dict with key ``rejected`` — list of ``mediaID`` strings.
    """
    return {"rejected": list(_state.get("rejected_media", set()))}


@app.post("/api/reject")
def reject_burst(req: RejectRequest) -> dict:
    """Mark all frames in the same burst as the given mediaID as rejected.

    Rejected media are excluded from future gallery rounds without affecting
    decisions already saved.

    Args:
        req: Body containing ``mediaId`` — the ``mediaID`` of any frame in the
            burst to reject.

    Raises:
        HTTPException: 400 if the workflow has not been initialized.
        HTTPException: 404 if ``mediaId`` is not in the candidate manifest.

    Returns:
        Dict with keys ``success`` (True) and ``removed`` (list of rejected
        ``mediaID`` strings).
    """
    if "candidates" not in _state:
        raise HTTPException(400, "Workflow not initialized.")
    p = _paths()
    cands = _state["candidates"]
    row = cands[cands["mediaID"] == req.mediaId]
    if row.empty:
        raise HTTPException(404, "Media not found")
    key = row.iloc[0]["site_occasion_key"]
    burst_id = row.iloc[0]["burst_id"]
    burst_media = cands[
        (cands["site_occasion_key"] == key) & (cands["burst_id"] == burst_id)
    ]["mediaID"].tolist()
    rm = _state.setdefault("rejected_media", set())
    rm.update(burst_media)
    _session_dir().mkdir(parents=True, exist_ok=True)
    p["rejected"].write_text(json.dumps(list(rm)))
    return {"success": True, "removed": burst_media}


@app.post("/api/unreject")
def unreject(req: UnrejectRequest) -> dict:
    """Remove ``mediaID`` values from the rejected set.

    Makes those frames eligible for future gallery rounds again.

    Args:
        req: Body containing ``media`` — list of ``mediaID`` strings to
            un-reject.

    Returns:
        Dict with key ``success`` (True).
    """
    p = _paths()
    rm = _state.get("rejected_media", set())
    for m in req.media:
        rm.discard(m)
    _state["rejected_media"] = rm
    p["rejected"].write_text(json.dumps(list(rm)))
    return {"success": True}


# ─── Results ─────────────────────────────────────────────────────────────────

@app.get("/api/results")
def get_results() -> dict:
    """Aggregate verification results for the active session.

    Computes confirmed / rejected / unverified counts globally and per species
    by joining the candidate manifest with the saved decision CSVs and the
    rejected-media set.

    Raises:
        HTTPException: 400 if no session is active.

    Returns:
        Dict with keys ``session_dir``, ``output_dir``, ``occupancy_dir``,
        ``total``, ``confirmed``, ``rejected``, ``unverified`` (all ints), and
        ``by_species`` (list of per-species dicts with the same count keys plus
        ``species``).
    """
    p = _paths()
    if "candidates" not in _state:
        raise HTTPException(400, "Aún no hay sesión activa.")

    cands = _state["candidates"]
    decisions_dir = p["decisions"]

    # ── Rondas completadas por especie ───────────────────────────────────────
    iter_by_sp: dict[str, int] = {}
    if decisions_dir.exists():
        for f in decisions_dir.glob("*.csv"):
            m = re.match(r"decisions_(.+)_iter(\d+)\.csv", f.name)
            if m:
                sp, it = m.group(1), int(m.group(2))
                iter_by_sp[sp] = max(iter_by_sp.get(sp, 0), it)

    # ── Claves y bursts confirmados ──────────────────────────────────────────
    conf_keys = confirmed_keys_set(decisions_dir) if decisions_dir.exists() else set()

    confirmed_obs_ids: set[str] = set()
    if decisions_dir.exists():
        for f in decisions_dir.glob("decisions_*_iter*.csv"):
            df_dec = pd.read_csv(f, dtype=str)
            if "observationID" in df_dec.columns:
                confirmed_obs_ids.update(df_dec["observationID"].dropna())

    # burst confirmado y su rank por celda (para calcular qué secuencias se revisaron)
    conf_burst_by_key: dict[str, tuple[int, int]] = {}  # key → (burst_id, rank)
    if confirmed_obs_ids:
        conf_rows = cands[cands["observationID"].isin(confirmed_obs_ids)][
            ["site_occasion_key", "burst_id", "rank"]
        ].drop_duplicates("site_occasion_key")
        for _, r in conf_rows.iterrows():
            conf_burst_by_key[r["site_occasion_key"]] = (int(r["burst_id"]), int(r["rank"]))

    # ── Estadísticas por período (site_occasion_key) ─────────────────────────
    periods = (
        cands.groupby(["site_occasion_key", "species_safe"])
        .agg(scientificName=("scientificName", "first"), max_rank=("rank", "max"))
        .reset_index()
    )

    def _period_status(row) -> str:
        if row["site_occasion_key"] in conf_keys:
            return "confirmed"
        if row["max_rank"] <= iter_by_sp.get(row["species_safe"], 0):
            return "rejected"
        return "unverified"

    periods["status"] = periods.apply(_period_status, axis=1)
    p_total = len(periods)
    p_counts = periods["status"].value_counts().to_dict()

    by_species: list[dict] = []
    for sp_safe, grp in periods.groupby("species_safe", sort=True):
        c = grp["status"].value_counts().to_dict()
        sci_name = grp["scientificName"].iloc[0]
        by_species.append({
            "species":    sci_name,
            "confirmed":  int(c.get("confirmed", 0)),
            "rejected":   int(c.get("rejected", 0)),
            "unverified": int(c.get("unverified", 0)),
        })

    # ── Estadísticas por secuencia (burst) ───────────────────────────────────
    seqs = (
        cands.groupby(["site_occasion_key", "species_safe", "burst_id"])
        .agg(scientificName=("scientificName", "first"), rank=("rank", "first"))
        .reset_index()
    )

    def _seq_status(row) -> str:
        key = row["site_occasion_key"]
        bid = int(row["burst_id"])
        rank = int(row["rank"])
        sp = row["species_safe"]
        if key in conf_burst_by_key:
            conf_bid, conf_rank = conf_burst_by_key[key]
            if bid == conf_bid:
                return "confirmed"
            if rank < conf_rank:
                return "rejected"
            return "unverified"
        rounds_done = iter_by_sp.get(sp, 0)
        if rank <= rounds_done:
            return "rejected"
        return "unverified"

    seqs["status"] = seqs.apply(_seq_status, axis=1)
    s_total = len(seqs)
    s_counts = seqs["status"].value_counts().to_dict()

    by_species_seqs: list[dict] = []
    for sp_safe, grp in seqs.groupby("species_safe", sort=True):
        c = grp["status"].value_counts().to_dict()
        sci_name = grp["scientificName"].iloc[0]
        by_species_seqs.append({
            "species":    sci_name,
            "confirmed":  int(c.get("confirmed", 0)),
            "rejected":   int(c.get("rejected", 0)),
            "unverified": int(c.get("unverified", 0)),
        })

    return {
        "session_dir":   str(_session_dir()),
        "output_dir":    str(p["camtrap_out"]),
        "occupancy_dir": str(p["occupancy_out"]),
        # por período
        "total":      p_total,
        "confirmed":  int(p_counts.get("confirmed", 0)),
        "rejected":   int(p_counts.get("rejected", 0)),
        "unverified": int(p_counts.get("unverified", 0)),
        "by_species": by_species,
        # por secuencia
        "seq_total":      s_total,
        "seq_confirmed":  int(s_counts.get("confirmed", 0)),
        "seq_rejected":   int(s_counts.get("rejected", 0)),
        "seq_unverified": int(s_counts.get("unverified", 0)),
        "by_species_seqs": by_species_seqs,
    }


@app.post("/api/open-folder")
def open_folder() -> dict:
    """Open the session directory in the OS file manager.

    Tries ``xdg-open`` (Linux), ``open`` (macOS) and ``explorer`` (Windows)
    in order, stopping at the first that succeeds.

    Returns:
        Dict with keys ``ok`` (True) and ``path`` (str absolute path opened).
    """
    import subprocess
    folder = str(_session_dir())
    for cmd in (["xdg-open"], ["open"], ["explorer"]):
        try:
            subprocess.Popen(cmd + [folder])
            break
        except FileNotFoundError:
            continue
    return {"ok": True, "path": folder}


# ─── Static frontend (bundle / Docker-less production) ───────────────────────
def _static_dir() -> Path | None:
    """Locate the built frontend static directory.

    Checks the PyInstaller bundle location first (``_MEIPASS/static``), then
    falls back to ``frontend/dist/`` relative to this file.

    Returns:
        Absolute path to the static directory, or ``None`` if neither location
        exists.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "static"  # type: ignore[attr-defined]
    candidate = Path(__file__).parent.parent / "frontend" / "dist"
    return candidate if candidate.exists() else None


_docs_dir = Path(__file__).parent.parent / "site"
if _docs_dir.exists():
    app.mount("/docs", StaticFiles(directory=str(_docs_dir), html=True), name="docs")

_sd = _static_dir()
if _sd is not None:
    app.mount("/", StaticFiles(directory=str(_sd), html=True), name="static")
