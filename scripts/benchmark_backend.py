#!/usr/bin/env python3
"""Time the backend on a synthetic large CamtrapDP (no server, no photos needed).

    uv run python scripts/benchmark_backend.py            # about 10 000 photos
    uv run python scripts/benchmark_backend.py --scale 10 # about 100 000 photos
    uv run python scripts/benchmark_backend.py --src /other/checkout/backend/src   # compare versions

Generates 60 sites x 24 occasions of 3 days with one target species, then times, through the real
API: creating the session, listing the events of round 1, saving that round's decisions, opening
the results, and (when the version defers it) the rebuild of the verified CamtrapDP that the
results page triggers. The session lives in a temporary folder and nothing of yours is touched.
"""
import argparse
import logging
import os
import random
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


def generate(out: Path, scale: int, seed: int = 11) -> int:
    random.seed(seed)
    start = datetime(2025, 1, 1)
    sites = [f"S{i:02d}" for i in range(1, 61)]
    dep = [dict(deploymentID="D" + s, locationID=s, locationName=s, deploymentStart="2025-01-01", deploymentEnd="2025-03-14") for s in sites]
    med, obs, n = [], [], 0
    for s in sites:
        for occ in range(24):
            if random.random() > 0.80:
                continue
            base = start + timedelta(days=3 * occ)
            for _ in range(random.randint(1, 3) * scale):
                t = base + timedelta(hours=random.randint(0, 70), minutes=random.randint(0, 59), seconds=random.randint(0, 59))
                score = random.uniform(0.5, 0.99)
                for f in range(random.choice([1, 2, 3, 3, 4, 6, 12])):
                    n += 1
                    ts = t + timedelta(seconds=15 * f)
                    med.append(dict(mediaID=f"m{n:07d}", deploymentID="D" + s, timestamp=ts.strftime("%Y-%m-%d %H:%M:%S"), filePath=f"img/{n}.jpg"))
                    obs.append(dict(observationID=f"o{n:07d}", deploymentID="D" + s, mediaID=f"m{n:07d}", observationLevel="media",
                                    observationType="animal", scientificName="Vulpes vulpes", classificationProbability=f"{score:.3f}",
                                    classificationMethod="machine", classifiedBy="DeepFaune", classificationTimestamp=None))
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(dep).to_csv(out / "deployments.csv", index=False)
    pd.DataFrame(med).to_csv(out / "media.csv", index=False)
    pd.DataFrame(obs).to_csv(out / "observations.csv", index=False)
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=int, default=1, help="1 = about 10 000 photos, 10 = about 100 000")
    ap.add_argument("--src", default=str(Path(__file__).resolve().parent.parent / "backend" / "src"), help="backend/src to test")
    args = ap.parse_args()

    logging.disable(logging.INFO)                                 # only the timings
    work = Path(tempfile.mkdtemp(prefix="camtrap_bench_"))
    os.environ["HOME"] = str(work / "home")                       # keeps the app's settings out of your own
    sys.path.insert(0, args.src)
    from fastapi.testclient import TestClient
    from main import app

    n = generate(work / "data", args.scale)
    client = TestClient(app)
    rows = []

    def timed(label, fn):
        t = time.perf_counter()
        r = fn()
        rows.append((label, time.perf_counter() - t))
        return r

    body = {"camtrap_dir": str(work / "data"), "output_dir": str(work / "out"), "target_species": ["Vulpes vulpes"],
            "study_start": "2025-01-01", "study_end": "2025-03-14", "occasion_days": 3, "total_iterations": 100000,
            "gap_seconds": 60, "min_score": 0.5, "include_burst_context": True}
    timed("create the session", lambda: client.post("/api/setup", json=body).json())
    ev = timed("list the events of round 1", lambda: client.get("/api/species/Vulpes_vulpes/events", params={"iteration": 1}).json())
    timed("save round 1 (300 confirmed)", lambda: client.post("/api/decisions", json={
        "species": "Vulpes_vulpes", "iteration": 1, "confirmed": [e["repObsId"] for e in ev[:300]]}).json())
    timed("open the results", lambda: client.get("/api/results").json())
    timed("species list", lambda: client.get("/api/species").json())

    print(f"\n{n:,} photos, {len(ev):,} cards in round 1  ({args.src})\n")
    for label, secs in rows:
        print(f"  {label:<32}{secs:8.2f} s")


if __name__ == "__main__":
    main()
