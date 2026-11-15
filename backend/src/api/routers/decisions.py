import logging
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_candidates
from camtrap_workflow import (
    NO_ANIMAL_LABEL,
    confirmed_keys_set,
    load_rejection_corrections,
    resolve_camtrapdp_resource,
    save_decisions,
    save_rejection_corrections,
    save_review_log,
    save_uncertain,
)
from schemas.requests import DecisionsRequest, RejectRequest, UnrejectRequest
from services import session_service, workflow_service

router = APIRouter(prefix="/api", tags=["decisions"])
logger = logging.getLogger(__name__)


@router.get("/decisions")
def get_decisions(species: str, iteration: int) -> dict:
    """Return confirmed and uncertain observationID values for a species and round."""
    p = session_service.paths()
    path = p["decisions"] / f"decisions_{species}_iter{iteration}.csv"
    upath = p["decisions"] / f"uncertain_{species}_iter{iteration}.csv"
    confirmed = pd.read_csv(path, dtype=str)["observationID"].tolist() if path.exists() else []
    uncertain = pd.read_csv(upath, dtype=str)["observationID"].tolist() if upath.exists() else []
    corr = load_rejection_corrections(p["corrections"])
    corr = corr[(corr["species_safe"] == species) & (corr["iteration"] == str(iteration))]
    return {"confirmed": confirmed, "uncertain": uncertain,
            "corrections": dict(zip(corr["observationID"], corr["actual_species"]))}


@router.post("/decisions", dependencies=[Depends(require_candidates)])
def post_decisions(req: DecisionsRequest) -> dict:
    """Save confirmed observations for one round and regenerate all output files."""
    p = session_service.paths()
    p["decisions"].mkdir(parents=True, exist_ok=True)
    candidates = session_service.get_candidates()
    config = session_service.get_config()

    logger.info(
        "Saving decisions: species=%s iteration=%d confirmed=%d",
        req.species, req.iteration, len(req.confirmed),
    )
    save_decisions(p["decisions"], candidates, req.species, req.iteration, req.confirmed)
    save_uncertain(
        p["decisions"], candidates, req.species, req.iteration,
        [u for u in req.uncertain if u not in set(req.confirmed)],
    )

    save_review_log(
        p["review_log"], candidates, req.species, req.iteration,
        req.confirmed, [u for u in req.uncertain if u not in set(req.confirmed)], req.decision_times,
    )

    if config.get("record_rejection_species"):
        skip = set(req.confirmed) | set(req.uncertain)
        save_rejection_corrections(
            p["corrections"], candidates, req.species, req.iteration,
            {k: v for k, v in req.corrections.items() if k not in skip},
        )

    conf_keys = confirmed_keys_set(p["decisions"])
    rejected = session_service.get_rejected_media()
    next_iter = req.iteration + 1
    next_cands = candidates[
        (candidates["species_safe"] == req.species)
        & (candidates["rank"] == next_iter)
        & (~candidates["site_occasion_key"].isin(conf_keys))
        & (~candidates["mediaID"].isin(rejected))
    ]
    done = len(next_cands) == 0 or next_iter > config["total_iterations"]
    logger.info("Decisions saved: done=%s next_iteration=%s remaining=%d", done, next_iter if not done else None, int(next_cands["site_occasion_key"].nunique()) if not done else 0)

    workflow_service.rebuild_outputs()

    return {
        "success": True,
        "saved": len(req.confirmed),
        "done": done,
        "next_iteration": next_iter if not done else None,
        "remaining": int(next_cands["site_occasion_key"].nunique()) if not done else 0,
    }


_taxa_cache: dict[str, list[str]] = {}


@router.get("/taxa")
def get_taxa() -> dict:
    """Taxa found in the dataset's observations, for the "actual species" suggestions."""
    camtrap_dir = str((session_service.get_config() or {}).get("camtrap_dir", ""))
    if camtrap_dir not in _taxa_cache:
        path = resolve_camtrapdp_resource(Path(camtrap_dir), "observations") if camtrap_dir else None
        names: list[str] = []
        if path is not None:
            col = pd.read_csv(path, usecols=["scientificName"], dtype=str)["scientificName"]
            names = sorted(col.dropna().unique().tolist())
        _taxa_cache[camtrap_dir] = names
    return {"taxa": _taxa_cache[camtrap_dir], "extra": ["Homo sapiens", NO_ANIMAL_LABEL]}


@router.get("/rejected")
def get_rejected() -> dict:
    """Return the set of manually rejected mediaID values."""
    return {"rejected": list(session_service.get_rejected_media())}


@router.post("/reject", dependencies=[Depends(require_candidates)])
def reject_burst(req: RejectRequest) -> dict:
    """Mark all frames in the same burst as the given mediaID as rejected."""
    candidates = session_service.get_candidates()
    logger.info("Reject burst request for mediaId=%s", req.mediaId)
    row = candidates[candidates["mediaID"] == req.mediaId]
    if row.empty:
        logger.warning("Reject failed: mediaId=%s not found", req.mediaId)
        raise HTTPException(404, "Media not found")
    key = row.iloc[0]["site_occasion_key"]
    burst_id = row.iloc[0]["burst_id"]
    burst_media = candidates[
        (candidates["site_occasion_key"] == key) & (candidates["burst_id"] == burst_id)
    ]["mediaID"].tolist()
    session_service.add_rejected_media(burst_media)
    logger.info("Burst rejected: key=%s burst_id=%s frames=%d", key, burst_id, len(burst_media))
    return {"success": True, "removed": burst_media}


@router.post("/unreject")
def unreject(req: UnrejectRequest) -> dict:
    """Remove mediaID values from the rejected set."""
    logger.info("Unreject request for %d media IDs", len(req.media))
    session_service.discard_rejected_media(req.media)
    return {"success": True}
