"""Bounding boxes: reading them, carrying them to the candidates, drawing them, serving them."""
import io
import json
from datetime import date

import pandas as pd
import pytest
from PIL import Image

from camtrap_workflow import (
    BOX_COLS, build_candidates, collect_boxes, count_boxes, generic_csv_to_camtrapdp,
)
from image_boxes import _PRIMARY, draw_boxes, render_with_boxes


def _obs(rows):
    cols = ["observationID", "mediaID", "scientificName", "classificationProbability", *BOX_COLS]
    return pd.DataFrame(rows, columns=cols).astype(object)


# ─── collect_boxes ────────────────────────────────────────────────────────────

def test_collect_boxes_lists_best_first_per_photo_and_species():
    obs = _obs([("a", "m1", "Cervus elaphus", "0.6", 0.1, 0.1, 0.2, 0.2),
                ("b", "m1", "Cervus elaphus", "0.9", 0.5, 0.5, 0.3, 0.3),
                ("c", "m1", "Sus scrofa",     "0.8", 0.0, 0.0, 0.5, 0.5)])
    boxes = collect_boxes(obs)
    assert json.loads(boxes[("m1", "Cervus elaphus")]) == [[0.5, 0.5, 0.3, 0.3], [0.1, 0.1, 0.2, 0.2]]
    assert json.loads(boxes[("m1", "Sus scrofa")]) == [[0.0, 0.0, 0.5, 0.5]]


def test_collect_boxes_ignores_missing_or_invalid_boxes():
    obs = _obs([("a", "m1", "X x", "0.9", None, None, None, None),        # no box
                ("b", "m2", "X x", "0.9", "abc", 0.1, 0.2, 0.2),            # not numeric
                ("c", "m3", "X x", "0.9", 0.1, 0.1, 0.0, 0.2),              # empty
                ("d", "m4", "X x", "0.9", 0.9, 0.1, 0.3, 0.2),              # sticks out of the image
                ("e", "m5", "X x", "0.9", 0.1, 0.1, 0.2, 0.2)])             # valid
    assert list(collect_boxes(obs)) == [("m5", "X x")]


def test_collect_boxes_without_box_columns_is_empty():
    assert collect_boxes(pd.DataFrame({"mediaID": ["m"], "scientificName": ["X x"],
                                       "classificationProbability": ["0.9"]})) == {}


def test_count_boxes_handles_empty_and_bad_values():
    assert count_boxes("") == 0 and count_boxes(None) == 0 and count_boxes(float("nan")) == 0
    assert count_boxes("not json") == 0 and count_boxes("[[0,0,1,1],[0,0,0.5,0.5]]") == 2


# ─── candidates ───────────────────────────────────────────────────────────────

def _tables(extra_obs):
    dep = pd.DataFrame({"deploymentID": ["D"], "locationID": ["S"],
                        "deploymentStart": ["2025-11-01"], "deploymentEnd": ["2025-11-05"]})
    med = pd.DataFrame({"mediaID": ["m1", "m2"], "deploymentID": "D",
                        "timestamp": ["2025-11-02 10:00:00", "2025-11-03 10:00:00"], "filePath": ["a.jpg", "b.jpg"]})
    base = dict(deploymentID="D", observationLevel="media", observationType="animal",
                classificationMethod="machine", classifiedBy="x", classificationTimestamp=None)
    obs = pd.DataFrame([{**base, **o} for o in extra_obs])
    return dep, med, obs


def _cands(extra_obs):
    dep, med, obs = _tables(extra_obs)
    return build_candidates(dep, med, obs, target_species=["Cervus elaphus", "Sus scrofa"],
                            study_start=date(2025, 11, 1), study_end=date(2025, 11, 5),
                            occasion_days=5, total_iterations=100, gap_seconds=60)


def test_candidates_carry_the_boxes_of_their_own_species():
    c = _cands([
        dict(observationID="a", mediaID="m1", scientificName="Cervus elaphus", classificationProbability="0.9",
             bboxX="0.1", bboxY="0.1", bboxWidth="0.2", bboxHeight="0.2"),
        dict(observationID="b", mediaID="m1", scientificName="Cervus elaphus", classificationProbability="0.7",
             bboxX="0.6", bboxY="0.5", bboxWidth="0.2", bboxHeight="0.3"),
        dict(observationID="c", mediaID="m1", scientificName="Sus scrofa", classificationProbability="0.8",
             bboxX="0.3", bboxY="0.3", bboxWidth="0.4", bboxHeight="0.4"),
        dict(observationID="d", mediaID="m2", scientificName="Cervus elaphus", classificationProbability="0.9"),
    ]).set_index("observationID")
    assert json.loads(c.loc["a", "bboxes"]) == [[0.1, 0.1, 0.2, 0.2], [0.6, 0.5, 0.2, 0.3]]   # both deer, best first
    assert json.loads(c.loc["c", "bboxes"]) == [[0.3, 0.3, 0.4, 0.4]]                         # only the boar's box
    assert count_boxes(c.loc["d", "bboxes"]) == 0                                              # no box available
    assert "b" not in c.index                       # the two deer rows are one candidate (collapsed)


def test_candidates_without_box_columns_still_have_the_column():
    c = _cands([dict(observationID="a", mediaID="m1", scientificName="Cervus elaphus", classificationProbability="0.9")])
    assert "bboxes" in c.columns and count_boxes(c["bboxes"].iloc[0]) == 0


# ─── drawing ──────────────────────────────────────────────────────────────────

def test_draw_boxes_colours_the_edge_and_leaves_the_rest_alone():
    base = Image.new("RGB", (100, 80), (90, 90, 90))
    out = draw_boxes(base, [[0.2, 0.25, 0.5, 0.5]])                  # x 20..70, y 20..60
    assert out.getpixel((20, 40)) == _PRIMARY                        # left edge
    assert out.getpixel((45, 20)) == _PRIMARY                        # top edge
    assert out.getpixel((45, 40)) == (90, 90, 90)                    # inside the box: untouched
    assert out.getpixel((5, 5)) == (90, 90, 90)                      # outside: untouched
    assert out.size == (100, 80) and base.getpixel((20, 40)) == (90, 90, 90)   # input not modified


def test_secondary_box_is_drawn_lighter():
    out = draw_boxes(Image.new("RGB", (200, 100), (90, 90, 90)), [[0.1, 0.1, 0.3, 0.3], [0.6, 0.5, 0.3, 0.3]])
    assert out.getpixel((20, 30)) == _PRIMARY
    assert out.getpixel((120, 50)) != _PRIMARY and out.getpixel((120, 50)) != (90, 90, 90)


def test_render_follows_exif_orientation_and_keeps_png(tmp_path):
    jpg = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6                                                  # stored sideways: shown rotated 90 degrees
    Image.new("RGB", (40, 20), (50, 60, 70)).save(jpg, exif=exif)
    data, kind = render_with_boxes(jpg, [[0.1, 0.1, 0.5, 0.5]])
    assert kind == "image/jpeg" and Image.open(io.BytesIO(data)).size == (20, 40)
    png = tmp_path / "a.png"
    Image.new("RGB", (30, 30)).save(png)
    data, kind = render_with_boxes(png, [[0.1, 0.1, 0.5, 0.5]])
    assert kind == "image/png"


# ─── importer ─────────────────────────────────────────────────────────────────

def test_custom_csv_keeps_bounding_box_columns(tmp_path):
    df = pd.DataFrame({"image_path": ["a/x.jpg", "a/y.jpg"], "datetime": ["2025-11-02 10:00:00", "2025-11-02 11:00:00"],
                       "label": ["red deer", "red deer"], "prob": [0.9, 0.8], "bboxX": [0.1, None],
                       "bboxY": [0.2, None], "bboxWidth": [0.3, None], "bboxHeight": [0.4, None]})
    generic_csv_to_camtrapdp(df, tmp_path, "image_path", "datetime", "label", col_score="prob")
    obs = pd.read_csv(tmp_path / "observations.csv")
    assert list(obs["bboxX"].dropna()) == [0.1] and list(obs["bboxHeight"].dropna()) == [0.4]
    assert set(BOX_COLS) <= set(obs.columns)


def test_custom_csv_without_boxes_adds_no_box_columns(tmp_path):
    df = pd.DataFrame({"image_path": ["a/x.jpg"], "datetime": ["2025-11-02 10:00:00"], "label": ["fox"]})
    generic_csv_to_camtrapdp(df, tmp_path, "image_path", "datetime", "label")
    assert not (set(BOX_COLS) & set(pd.read_csv(tmp_path / "observations.csv").columns))
