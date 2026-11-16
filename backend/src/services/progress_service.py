"""Progress of an unfinished round (or of the pending-expert-review view), kept in the session folder.

The gallery saves the decisions of the work in progress a couple of seconds after each click, so
closing the tab (or the computer) loses nothing and the work can be continued from another browser
or, through the session export, another computer. Progress changes no result: it is only read back
by the gallery, and it is removed when the round is finished (or the pending verdicts are saved).

One small CSV per species, ``decisions/progress_<species>.csv``, as in the community fork. It holds
the progress of several pieces of work at once, told apart by ``mode`` (``rounds`` or ``pending``)
and ``iteration`` (the round; 0 for the pending view), so going back to a previous round keeps what
was already done in the later one. One row per decided cell (``key``); ``rep_obs_id`` is the event
confirmed in the pending view (the photo being looked at), ``actual_species`` the species typed for
a rejection and ``decided_at`` when the reviewer clicked (epoch ms). The name does not start with
``decisions_`` or ``unsure_`` on purpose, so nothing that reads the saved rounds ever picks it up.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import HTTPException

logger = logging.getLogger(__name__)

PROGRESS_COLUMNS = ["mode", "iteration", "key", "decision", "rep_obs_id", "actual_species", "decided_at", "saved_at"]
VALID_MODES = {"rounds", "pending"}
VALID_DECISIONS = {"confirmed", "rejected", "unsure"}
_SAFE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _path(decisions_dir: Path, species_safe: str) -> Path:
    if not _SAFE.match(species_safe) or species_safe.startswith("."):
        raise HTTPException(400, f"Especie no válida: {species_safe}")
    return decisions_dir / f"progress_{species_safe}.csv"


def _read(decisions_dir: Path, species_safe: str) -> pd.DataFrame:
    f = _path(decisions_dir, species_safe)
    if not f.is_file():
        return pd.DataFrame(columns=PROGRESS_COLUMNS)
    try:
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
    except Exception:
        logger.warning("Unreadable progress file ignored: %s", f)
        return pd.DataFrame(columns=PROGRESS_COLUMNS)
    if not set(PROGRESS_COLUMNS) <= set(df.columns):
        return pd.DataFrame(columns=PROGRESS_COLUMNS)
    return df[PROGRESS_COLUMNS]


def _write(decisions_dir: Path, species_safe: str, df: pd.DataFrame) -> None:
    f = _path(decisions_dir, species_safe)
    if df.empty:
        f.unlink(missing_ok=True)
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".csv.tmp")
    df[PROGRESS_COLUMNS].to_csv(tmp, index=False)
    tmp.replace(f)                                          # written whole or not at all


def _same(df: pd.DataFrame, mode: str, iteration: int) -> pd.Series:
    return (df["mode"] == mode) & (df["iteration"] == str(int(iteration)))


def load_progress(
    decisions_dir: Path, species_safe: str, mode: Optional[str] = None, iteration: Optional[int] = None,
) -> Optional[dict]:
    """Saved progress of a species for one piece of work (or the latest saved one), or None."""
    df = _read(decisions_dir, species_safe)
    if df.empty:
        return None
    if mode is not None and iteration is not None:
        df = df[_same(df, mode, iteration)]
    else:
        latest = df.sort_values("saved_at").iloc[-1]
        df = df[(df["mode"] == latest["mode"]) & (df["iteration"] == latest["iteration"])]
    if df.empty:
        return None
    first = df.iloc[0]
    try:
        it = int(first["iteration"])
    except ValueError:
        return None
    decisions: dict[str, str] = {}
    chosen_rep: dict[str, str] = {}
    corrections: dict[str, str] = {}
    times: dict[str, int] = {}
    for key, dec, rep, actual, at in zip(df["key"], df["decision"], df["rep_obs_id"], df["actual_species"], df["decided_at"]):
        if dec not in VALID_DECISIONS:
            continue
        decisions[key] = dec
        if rep:
            chosen_rep[key] = rep
        if actual:
            corrections[key] = actual
        if at:
            try:
                times[key] = int(float(at))
            except ValueError:
                pass
    return {
        "mode": first["mode"], "iteration": it, "saved_at": df["saved_at"].max(),
        "decisions": decisions, "chosen_rep": chosen_rep, "corrections": corrections, "decision_times": times,
    }


def save_progress(
    decisions_dir: Path,
    species_safe: str,
    mode: str,
    iteration: int,
    decisions: dict[str, str],
    chosen_rep: Optional[dict[str, str]] = None,
    corrections: Optional[dict[str, str]] = None,
    times_ms: Optional[dict[str, int]] = None,
) -> str:
    """Overwrite the progress of one piece of work of a species; returns the timestamp.

    Unknown decision values are dropped; an empty progress removes that piece of work.
    """
    if mode not in VALID_MODES:
        raise HTTPException(400, f"Modo no válido: {mode}")
    chosen_rep, corrections, times_ms = chosen_rep or {}, corrections or {}, times_ms or {}
    saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = pd.DataFrame([
        {
            "mode": mode, "iteration": str(int(iteration)), "key": key, "decision": dec,
            "rep_obs_id": chosen_rep.get(key, ""),
            "actual_species": str(corrections.get(key, "")).strip() if dec == "rejected" else "",
            "decided_at": str(int(times_ms[key])) if key in times_ms else "",
            "saved_at": saved_at,
        }
        for key, dec in decisions.items() if dec in VALID_DECISIONS
    ], columns=PROGRESS_COLUMNS)
    df = _read(decisions_dir, species_safe)
    df = df[~_same(df, mode, iteration)]
    _write(decisions_dir, species_safe, pd.concat([df, rows], ignore_index=True))
    logger.info("Progress saved: species=%s mode=%s iteration=%d decisions=%d", species_safe, mode, iteration, len(rows))
    return saved_at


def clear_progress(
    decisions_dir: Path, species_safe: str, mode: Optional[str] = None, iteration: Optional[int] = None,
) -> None:
    """Forget the progress of a species: one piece of work, or all of it."""
    try:
        if mode is None or iteration is None:
            _path(decisions_dir, species_safe).unlink(missing_ok=True)
            return
        df = _read(decisions_dir, species_safe)
        _write(decisions_dir, species_safe, df[~_same(df, mode, iteration)])
    except HTTPException:
        pass
