import logging
from pathlib import Path

from fastapi import APIRouter, Depends

from api.deps import require_candidates
from camtrap_workflow import get_events, get_review_events, species_stats
from schemas.requests import ReviewDecisionsRequest
from services import session_service, workflow_service

router = APIRouter(
    prefix="/api/species",
    tags=["species"],
    dependencies=[Depends(require_candidates)],
)
logger = logging.getLogger(__name__)


def _media_resolution_config() -> tuple[str, Path, bool]:
    """Return (image_base_dir, fallback_base, flat_search) for the active
    session, matching how /api/image/{mediaID} resolves the same fields."""
    config = session_service.get_config()
    image_base_dir = config.get("image_base_dir", "")
    fallback_base = Path(image_base_dir) if image_base_dir else Path(config["camtrap_dir"]).parent
    return image_base_dir, fallback_base, bool(config.get("flat_search", False))


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
    image_base_dir, fallback_base, flat_search = _media_resolution_config()
    return get_events(
        session_service.get_candidates(),
        p["decisions"],
        session_service.get_rejected_media(),
        species_safe,
        iteration,
        image_base_dir,
        fallback_base,
        flat_search,
    )


@router.get("/{species_safe}/review")
def get_species_review(species_safe: str) -> list[dict]:
    """Return all cells for a completed species with their confirmation status."""
    p = session_service.paths()
    candidates = session_service.get_candidates()
    sp_cands = candidates[candidates["species_safe"] == species_safe]
    if sp_cands.empty:
        return []
    image_base_dir, fallback_base, flat_search = _media_resolution_config()
    return get_review_events(sp_cands, p["decisions"], image_base_dir, fallback_base, flat_search)


@router.put("/{species_safe}/decisions")
def update_species_decisions(species_safe: str, req: ReviewDecisionsRequest) -> dict:
    """Replace all decisions for a species with a corrected set, then regenerate outputs."""
    logger.info(
        "Updating decisions for %s: %d confirmed keys", species_safe, len(req.confirmed_keys)
    )
    confirmed = workflow_service.replace_species_decisions(species_safe, req.confirmed_keys)
    return {"success": True, "confirmed": confirmed}
