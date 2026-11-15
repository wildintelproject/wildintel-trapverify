"""Progress of an unfinished review round, kept in the session folder.

The gallery saves the decisions of the round being reviewed a couple of seconds after each
click, so closing the tab (or the computer) loses nothing and the work can be continued from
another browser or, through the session export, another computer. Progress changes no result:
it is only read back by the gallery, and it is removed when the round is finished.

One file per species and round: ``decisions/progress_<species>_iter<N>.csv`` with one row per
decided event (``observationID`` of the event's representative detection).
"""
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

COLS = ["observationID", "decision", "actual_species", "decided_at"]
DECISIONS = ("confirmed", "rejected", "unsure")


def _file(decisions_dir: Path, species_safe: str, iteration: int) -> Path:
    return decisions_dir / f"progress_{species_safe}_iter{int(iteration)}.csv"


def save_progress(
    decisions_dir: Path,
    species_safe: str,
    iteration: int,
    decisions: dict[str, str],
    corrections: dict[str, str],
    times_ms: dict[str, int],
) -> int:
    """Write (replace) the progress of a round; returns the number of decisions kept.

    Unknown decision values are dropped. An empty progress removes the file.
    """
    decisions_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "observationID": oid,
            "decision": d,
            "actual_species": str(corrections.get(oid, "")).strip() if d == "rejected" else "",
            "decided_at": int(times_ms[oid]) if oid in times_ms else "",
        }
        for oid, d in decisions.items() if d in DECISIONS
    ]
    path = _file(decisions_dir, species_safe, iteration)
    if not rows:
        path.unlink(missing_ok=True)
        return 0
    tmp = path.with_suffix(".csv.tmp")
    pd.DataFrame(rows, columns=COLS).to_csv(tmp, index=False)
    tmp.replace(path)                                       # written whole or not at all
    return len(rows)


def load_progress(decisions_dir: Path, species_safe: str, iteration: int) -> Optional[dict]:
    """Saved progress of a round, or None when there is none."""
    path = _file(decisions_dir, species_safe, iteration)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        logger.warning("Unreadable progress file %s", path)
        return None
    df = df[df["decision"].isin(DECISIONS)]
    times = {r.observationID: int(float(r.decided_at)) for r in df.itertuples() if r.decided_at}
    return {
        "iteration": int(iteration),
        "decisions": dict(zip(df["observationID"], df["decision"])),
        "corrections": {r.observationID: r.actual_species for r in df.itertuples() if r.actual_species},
        "decision_times": times,
        "saved_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
    }


def clear_progress(decisions_dir: Path, species_safe: str, iteration: Optional[int] = None) -> None:
    """Remove the progress of one round, or of every round of the species."""
    if iteration is not None:
        _file(decisions_dir, species_safe, iteration).unlink(missing_ok=True)
        return
    if decisions_dir.exists():
        for f in decisions_dir.glob(f"progress_{species_safe}_iter*.csv"):
            if re.fullmatch(rf"progress_{re.escape(species_safe)}_iter\d+\.csv", f.name):
                f.unlink()
