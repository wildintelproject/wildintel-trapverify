import logging

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
    return get_events(
        session_service.get_candidates(),
        p["decisions"],
        session_service.get_rejected_media(),
        species_safe,
        iteration,
    )


@router.get("/{species_safe}/review")
def get_species_review(species_safe: str) -> list[dict]:
    """Return all cells for a completed species with their confirmation status."""
    p = session_service.paths()
    candidates = session_service.get_candidates()
    sp_cands = candidates[candidates["species_safe"] == species_safe]
    if sp_cands.empty:
        return []
    return get_review_events(sp_cands, p["decisions"])


@router.put("/{species_safe}/decisions")
def update_species_decisions(species_safe: str, req: ReviewDecisionsRequest) -> dict:
    """Replace all decisions for a species with a corrected set, then regenerate outputs."""
    logger.info(
        "Updating decisions for %s: %d confirmed keys", species_safe, len(req.confirmed_keys)
    )
    confirmed = workflow_service.replace_species_decisions(species_safe, req.confirmed_keys)
    return {"success": True, "confirmed": confirmed}
