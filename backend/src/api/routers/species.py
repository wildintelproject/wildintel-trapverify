import logging
from pathlib import Path

from fastapi import APIRouter, Depends

from api.deps import require_candidates
from camtrap_workflow import get_events, get_review_events, media_extra_bases, species_stats
from fastapi import HTTPException
from camtrap_workflow import rounds_completed
from schemas.requests import ProgressRequest, ReviewDecisionsRequest
from services import progress_service, session_service, workflow_service

router = APIRouter(
    prefix="/api/species",
    tags=["species"],
    dependencies=[Depends(require_candidates)],
)
logger = logging.getLogger(__name__)


def _media_resolution_config() -> tuple[str, Path, bool, tuple]:
    """Return (image_base_dir, fallback_base, flat_search, extra_bases) for the active
    session, matching how /api/image/{mediaID} resolves the same fields."""
    config = session_service.get_config()
    image_base_dir = config.get("image_base_dir", "")
    fallback_base = Path(image_base_dir) if image_base_dir else Path(config["camtrap_dir"])
    return (image_base_dir, fallback_base, bool(config.get("flat_search", False)),
            media_extra_bases(config["camtrap_dir"], image_base_dir))


def _with_image_token(events: list[dict]) -> list[dict]:
    """Add the session token to the app's own image URLs so the browser may cache them."""
    token = session_service.image_token()
    for ev in events:
        for fr in ev["frames"]:
            if fr["img"].startswith("/api/image/") and "?" not in fr["img"]:
                fr["img"] = f"{fr['img']}?v={token}"
    return events


@router.get("")
def list_species() -> list[dict]:
    """Return per-species progress statistics and thumbnail URLs."""
    p = session_service.paths()
    p["decisions"].mkdir(parents=True, exist_ok=True)
    candidates = session_service.get_candidates()
    config = session_service.get_config()

    stats = species_stats(candidates, p["decisions"], config["total_iterations"])
    logger.debug("Species list requested: %d species returned", len(stats))
    for sp in stats:
        media_ids = (
            candidates[candidates["species_safe"] == sp["species_safe"]]
            ["mediaID"]
            .drop_duplicates()
            .head(4)
            .tolist()
        )
        sp["thumbnails"] = [f"/api/image/{mid}" for mid in media_ids]
    return stats


@router.get("/{species_safe}/events")
def get_species_events(species_safe: str, iteration: int = 1) -> list[dict]:
    """Return pending gallery events for a species in a given round."""
    logger.info("Events requested: species=%s iteration=%d", species_safe, iteration)
    p = session_service.paths()
    p["decisions"].mkdir(parents=True, exist_ok=True)
    image_base_dir, fallback_base, flat_search, extra_bases = _media_resolution_config()
    events = get_events(
        session_service.get_candidates(),
        p["decisions"],
        session_service.get_rejected_media(),
        species_safe,
        iteration,
        image_base_dir,
        fallback_base,
        flat_search,
        extra_bases,
    )
    return _with_image_token(events)


@router.get("/{species_safe}/review")
def get_species_review(species_safe: str) -> list[dict]:
    """Return all cells for a completed species with their confirmation status."""
    p = session_service.paths()
    candidates = session_service.get_candidates()
    sp_cands = candidates[candidates["species_safe"] == species_safe]
    if sp_cands.empty:
        return []
    image_base_dir, fallback_base, flat_search, extra_bases = _media_resolution_config()
    return _with_image_token(
        get_review_events(sp_cands, p["decisions"], image_base_dir, fallback_base, flat_search, extra_bases))


@router.put("/{species_safe}/decisions")
def update_species_decisions(species_safe: str, req: ReviewDecisionsRequest) -> dict:
    """Replace all decisions for a species with a corrected set, then regenerate outputs."""
    logger.info(
        "Updating decisions for %s: %d confirmed keys", species_safe, len(req.confirmed_keys)
    )
    confirmed = workflow_service.replace_species_decisions(species_safe, req.confirmed_keys)
    return {"success": True, "confirmed": confirmed}


@router.get("/{species_safe}/progress")
def get_progress(species_safe: str, iteration: int) -> dict:
    """Saved progress of an unfinished round (``{"progress": null}`` when there is none)."""
    d = session_service.paths()["decisions"]
    return {"progress": progress_service.load_progress(d, species_safe, iteration)}


@router.put("/{species_safe}/progress")
def save_progress(species_safe: str, req: ProgressRequest) -> dict:
    """Save the decisions made so far in a round; changes no result."""
    d = session_service.paths()["decisions"]
    if req.iteration <= rounds_completed(d).get(species_safe, 0):
        raise HTTPException(400, "Esa ronda ya está terminada.")
    n = progress_service.save_progress(
        d, species_safe, req.iteration, req.decisions, req.corrections, req.decision_times,
    )
    saved = progress_service.load_progress(d, species_safe, req.iteration)
    return {"success": True, "n": n, "saved_at": saved["saved_at"] if saved else None}


@router.post("/{species_safe}/reopen")
def reopen_round(species_safe: str) -> dict:
    """Re-open the last finished round of a species to correct it."""
    return workflow_service.reopen_last_round(species_safe)
