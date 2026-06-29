"""
Results aggregation for CamTrap Verify.

Computes confirmed / rejected / unverified counts at the period (site-occasion)
and sequence (burst) level, for the active session.
"""
import logging
import re

import pandas as pd
from fastapi import HTTPException

from camtrap_workflow import confirmed_keys_set
from services import session_service

logger = logging.getLogger(__name__)


def compute_results() -> dict:
    """Aggregate verification results for the active session.

    Raises:
        HTTPException: 400 if no session is active.

    Returns:
        Dict with session paths, global counts, and per-species breakdowns
        at both the period and sequence granularity.
    """
    candidates = session_service.get_candidates()
    if candidates is None:
        raise HTTPException(400, "Aún no hay sesión activa.")
    logger.info("Computing results for %d candidate rows", len(candidates))

    p = session_service.paths()
    decisions_dir = p["decisions"]

    # ── Rounds completed per species ──────────────────────────────────────────
    iter_by_sp: dict[str, int] = {}
    if decisions_dir.exists():
        for f in decisions_dir.glob("*.csv"):
            m = re.match(r"decisions_(.+)_iter(\d+)\.csv", f.name)
            if m:
                sp, it = m.group(1), int(m.group(2))
                iter_by_sp[sp] = max(iter_by_sp.get(sp, 0), it)

    # ── Confirmed keys and burst mapping ─────────────────────────────────────
    conf_keys = confirmed_keys_set(decisions_dir) if decisions_dir.exists() else set()

    confirmed_obs_ids: set[str] = set()
    if decisions_dir.exists():
        for f in decisions_dir.glob("decisions_*_iter*.csv"):
            df_dec = pd.read_csv(f, dtype=str)
            if "observationID" in df_dec.columns:
                confirmed_obs_ids.update(df_dec["observationID"].dropna())

    # key → (confirmed_burst_id, confirmed_rank)
    conf_burst_by_key: dict[str, tuple[int, int]] = {}
    if confirmed_obs_ids:
        conf_rows = (
            candidates[candidates["observationID"].isin(confirmed_obs_ids)][
                ["site_occasion_key", "burst_id", "rank"]
            ]
            .drop_duplicates("site_occasion_key")
        )
        for _, r in conf_rows.iterrows():
            conf_burst_by_key[r["site_occasion_key"]] = (int(r["burst_id"]), int(r["rank"]))

    # ── Period-level stats ────────────────────────────────────────────────────
    periods = (
        candidates
        .groupby(["site_occasion_key", "species_safe"])
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
    p_counts = periods["status"].value_counts().to_dict()

    by_species: list[dict] = [
        {
            "species":    grp["scientificName"].iloc[0],
            "confirmed":  int(c.get("confirmed", 0)),
            "rejected":   int(c.get("rejected", 0)),
            "unverified": int(c.get("unverified", 0)),
        }
        for _, grp in periods.groupby("species_safe", sort=True)
        for c in [grp["status"].value_counts().to_dict()]
    ]

    # ── Sequence-level stats ──────────────────────────────────────────────────
    seqs = (
        candidates
        .groupby(["site_occasion_key", "species_safe", "burst_id"])
        .agg(scientificName=("scientificName", "first"), rank=("rank", "first"))
        .reset_index()
    )

    def _seq_status(row) -> str:
        key = row["site_occasion_key"]
        bid, rank, sp = int(row["burst_id"]), int(row["rank"]), row["species_safe"]
        if key in conf_burst_by_key:
            conf_bid, conf_rank = conf_burst_by_key[key]
            if bid == conf_bid:
                return "confirmed"
            return "rejected" if rank < conf_rank else "unverified"
        return "rejected" if rank <= iter_by_sp.get(sp, 0) else "unverified"

    seqs["status"] = seqs.apply(_seq_status, axis=1)
    s_counts = seqs["status"].value_counts().to_dict()

    by_species_seqs: list[dict] = [
        {
            "species":    grp["scientificName"].iloc[0],
            "confirmed":  int(c.get("confirmed", 0)),
            "rejected":   int(c.get("rejected", 0)),
            "unverified": int(c.get("unverified", 0)),
        }
        for _, grp in seqs.groupby("species_safe", sort=True)
        for c in [grp["status"].value_counts().to_dict()]
    ]

    logger.info(
        "Results: %d periods (confirmed=%d rejected=%d unverified=%d)",
        len(periods),
        int(p_counts.get("confirmed", 0)),
        int(p_counts.get("rejected", 0)),
        int(p_counts.get("unverified", 0)),
    )
    return {
        "session_dir":     str(session_service.session_dir()),
        "output_dir":      str(p["camtrap_out"]),
        "occupancy_dir":   str(p["occupancy_out"]),
        "total":           len(periods),
        "confirmed":       int(p_counts.get("confirmed", 0)),
        "rejected":        int(p_counts.get("rejected", 0)),
        "unverified":      int(p_counts.get("unverified", 0)),
        "by_species":      by_species,
        "seq_total":       len(seqs),
        "seq_confirmed":   int(s_counts.get("confirmed", 0)),
        "seq_rejected":    int(s_counts.get("rejected", 0)),
        "seq_unverified":  int(s_counts.get("unverified", 0)),
        "by_species_seqs": by_species_seqs,
    }
