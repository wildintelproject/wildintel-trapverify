#!/usr/bin/env python3
"""
generate_datapackage_example.py — Deriva examples/camtrap_dp_with_datapackage/ a partir de
examples/camtrap_dp/, añadiendo lo que le falta a este último para ser un paquete Camtrap DP
1.0.2 válido: coordenadas de despliegue, timestamps con huso horario, los campos obligatorios
que faltan en media.csv/observations.csv, y un datapackage.json completo.

Sirve como el ejemplo "con datapackage.json", en contraste con examples/camtrap_dp/ (sin él),
para probar ambos caminos del flujo de importación/exportación de la app.

Reutiliza las mismas imágenes de examples/images/ (las rutas relativas en media.csv son
idénticas); no crea una copia de las fotos.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE     = Path(__file__).parent
SRC      = BASE / "camtrap_dp"
OUT      = BASE / "camtrap_dp_with_datapackage"
OUT.mkdir(exist_ok=True)

# Coordenadas de ejemplo dentro del Parque Nacional de Doñana (los deploymentID
# "r0039-dona_*" ya sugerían esa zona, pero el CamtrapDP original no traía coordenadas).
COORDS = {
    "r0039-dona_0033": (37.021, -6.437),
    "r0039-dona_0067": (36.988, -6.395),
    "r0039-dona_0071": (37.045, -6.361),
}

dep = pd.read_csv(SRC / "deployments.csv")
med = pd.read_csv(SRC / "media.csv")
obs = pd.read_csv(SRC / "observations.csv")

# Orden canónico de columnas de cada Table Schema oficial (1.0.2): un recurso Camtrap DP
# real trae siempre el conjunto completo de columnas, en este orden, aunque muchas queden
# vacías -- no solo las que tengan dato.
DEPLOYMENTS_COLS = [
    "deploymentID", "locationID", "locationName", "latitude", "longitude",
    "coordinateUncertainty", "deploymentStart", "deploymentEnd", "setupBy", "cameraID",
    "cameraModel", "cameraDelay", "cameraHeight", "cameraDepth", "cameraTilt",
    "cameraHeading", "detectionDistance", "timestampIssues", "baitUse", "featureType",
    "habitat", "deploymentGroups", "deploymentTags", "deploymentComments",
]
MEDIA_COLS = [
    "mediaID", "deploymentID", "captureMethod", "timestamp", "filePath", "filePublic",
    "fileName", "fileMediatype", "exifData", "favorite", "mediaComments",
]
OBSERVATIONS_COLS = [
    "observationID", "deploymentID", "mediaID", "eventID", "eventStart", "eventEnd",
    "observationLevel", "observationType", "cameraSetupType", "scientificName", "count",
    "lifeStage", "sex", "behavior", "individualID", "individualPositionRadius",
    "individualPositionAngle", "individualSpeed", "bboxX", "bboxY", "bboxWidth",
    "bboxHeight", "classificationMethod", "classifiedBy", "classificationTimestamp",
    "classificationProbability", "observationTags", "observationComments",
]

# ── deployments.csv: rellenar latitude/longitude (obligatorias, venían vacías) ──
dep["latitude"]  = dep["deploymentID"].map(lambda d: COORDS[d][0])
dep["longitude"] = dep["deploymentID"].map(lambda d: COORDS[d][1])
dep = dep.reindex(columns=DEPLOYMENTS_COLS)
dep.to_csv(OUT / "deployments.csv", index=False)

# ── media.csv: añadir huso horario a timestamp y los campos obligatorios que faltaban ──
med["timestamp"]     = med["timestamp"] + "+00:00"
med["captureMethod"] = "activityDetection"
med["filePublic"]    = "false"  # minúsculas: así es como Table Schema espera un booleano
med["fileName"]      = med["filePath"].apply(lambda p: Path(p).name)
med["fileMediatype"] = "image/jpeg"
med = med.reindex(columns=MEDIA_COLS)
med.to_csv(OUT / "media.csv", index=False)

# ── observations.csv: añadir eventStart/eventEnd (obligatorias) ──
# Las observaciones son a nivel de "media" (una por foto), así que el evento
# coincide con el timestamp de esa misma foto.
obs = obs.merge(med[["mediaID", "timestamp"]], on="mediaID", how="left")
obs["eventStart"] = obs["timestamp"]
obs["eventEnd"]   = obs["timestamp"]
obs = obs.reindex(columns=OBSERVATIONS_COLS)
obs.to_csv(OUT / "observations.csv", index=False)

# ── datapackage.json ──
species = sorted(obs["scientificName"].dropna().unique().tolist())
lat, lon = dep["latitude"], dep["longitude"]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resource(name: str) -> dict:
    return {
        "name": name,
        "path": f"{name}.csv",
        "profile": "tabular-data-resource",
        "schema": f"https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/{name}-table-schema.json",
    }


datapackage = {
    "name": "camtrap-dp-example",
    "title": "Doñana camera trap pilot survey (example)",
    "profile": "https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/camtrap-dp-profile.json",
    "created": now,
    "resources": [resource("deployments"), resource("media"), resource("observations")],
    "contributors": [
        {"title": "WildINTEL project", "role": "principalInvestigator"},
    ],
    "project": {
        "title": "Doñana camera trap pilot survey",
        "samplingDesign": "opportunistic",
        "captureMethod": ["activityDetection"],
        "individualAnimals": False,
        "observationLevel": ["media"],
    },
    "spatial": {
        "type": "Polygon",
        "coordinates": [[
            [lon.min(), lat.min()], [lon.max(), lat.min()],
            [lon.max(), lat.max()], [lon.min(), lat.max()],
            [lon.min(), lat.min()],
        ]],
    },
    "temporal": {
        "start": med["timestamp"].min()[:10],
        "end": med["timestamp"].max()[:10],
    },
    "taxonomic": [{"scientificName": s} for s in species],
}
(OUT / "datapackage.json").write_text(json.dumps(datapackage, indent=2) + "\n")

print(f"Escrito {OUT} ({len(med)} media, {len(obs)} observations, especies: {species})")
