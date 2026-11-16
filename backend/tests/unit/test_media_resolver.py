"""MediaResolver: photos located from cached folder listings (tests ported from the community fork)."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


def test_media_resolver_matches_exists_semantics(tmp_path, monkeypatch):
    import os
    from camtrap_workflow import MediaResolver

    (tmp_path / "DEP1").mkdir()
    (tmp_path / "DEP1" / "a.jpg").write_bytes(b"x")
    (tmp_path / "LOCKED").mkdir()
    real_listdir = os.listdir

    def fake_listdir(path="."):
        if Path(path).name == "LOCKED":
            raise PermissionError("denied")
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", fake_listdir)
    r = MediaResolver(str(tmp_path), tmp_path)
    assert r.status(tmp_path / "DEP1" / "a.jpg") == "ok"
    assert r.status(tmp_path / "DEP1" / "b.jpg") == "missing"
    assert r.status(tmp_path / "NOPE" / "a.jpg") == "missing"
    assert r.status(tmp_path / "LOCKED" / "a.jpg") == "denied"
    assert r.exists(tmp_path / "LOCKED" / "a.jpg") is True   # like _exists_or_denied
    assert r.resolve("ignored/a.jpg", "DEP1", "a.jpg") == tmp_path / "DEP1" / "a.jpg"


def test_filepath_from_another_computer_is_found_by_its_suffix(tmp_path):
    """A media.csv exported on a Mac (absolute /Volumes/... paths) still finds
    the photos on Windows when the images folder holds the same sub-tree, with
    no flat search (which would walk the whole archive)."""
    from camtrap_workflow import MediaResolver, resolve_media_path

    photo = tmp_path / "R0025" / "r0025-dona_0011" / "R0025-DONA_0011__20230509_8232.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"x")
    mac = "/Volumes/T7 Shield/pictures/2023_optimized/R0025/r0025-dona_0011/R0025-DONA_0011__20230509_8232.jpg"
    win = "D:\\2023_optimized\\R0025\\r0025-dona_0011\\R0025-DONA_0011__20230509_8232.jpg"
    for fp in (mac, win):
        assert resolve_media_path(fp, "r0025-dona_0011", photo.name, str(tmp_path), tmp_path) == photo
        assert MediaResolver(str(tmp_path), tmp_path).resolve(fp, "r0025-dona_0011", photo.name) == photo


def test_suffix_match_never_matches_a_bare_file_name_at_the_root(tmp_path):
    from camtrap_workflow import resolve_media_path

    (tmp_path / "a.jpg").write_bytes(b"x")
    got = resolve_media_path("/elsewhere/dep/a.jpg", "dep", "a.jpg", str(tmp_path), tmp_path)
    assert got != tmp_path / "a.jpg"


def test_ambiguity_check_does_not_walk_when_everything_resolves(tmp_path, monkeypatch):
    import os
    from camtrap_workflow import clear_media_caches, find_flat_search_ambiguities

    clear_media_caches()
    photo = tmp_path / "R0025" / "dep1" / "a.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"x")
    med = pd.DataFrame({
        "mediaID": ["m1"], "deploymentID": ["dep1"], "fileName": ["a.jpg"],
        "filePath": ["/Volumes/X/R0025/dep1/a.jpg"],
    })

    def no_walk(*_a, **_k):
        raise AssertionError("the image tree should not be walked")

    monkeypatch.setattr(os, "walk", no_walk)
    assert find_flat_search_ambiguities(med, str(tmp_path)) == []


def test_photos_below_the_data_folder_are_found_without_images_folder(tmp_path):
    """No images folder configured, absolute filePaths from another computer,
    photos stored below the CamtrapDP folder: found via the filePath suffix."""
    from camtrap_workflow import MediaResolver, resolve_media_path

    data = tmp_path / "2023_optimized"
    photo = data / "R0025" / "dep1" / "a.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"x")
    mac = "/Volumes/T7 Shield/x/2023_optimized/R0025/dep1/a.jpg"
    assert resolve_media_path(mac, "dep1", "a.jpg", "", data) == photo
    assert MediaResolver("", data).resolve(mac, "dep1", "a.jpg") == photo


def test_cached_suffix_lookup_matches_uncached(tmp_path):
    from camtrap_workflow import MediaResolver, _is_file, _suffix_match

    for rel in ("A/R1/d1/x.jpg", "R1/d1/y.jpg", "R1/d2/x.jpg", "d3/z.jpg"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    r = MediaResolver(str(tmp_path), tmp_path)
    for fp in ("/m/A/R1/d1/x.jpg", "/m/A/R1/d1/y.jpg", "/m/q/R1/d1/y.jpg", "/m/R1/d2/x.jpg",
               "C:\\m\\R1\\d1\\x.jpg", "/m/d3/z.jpg", "/m/d3/none.jpg", "z.jpg", "/m/A/R1/d1/x.jpg"):
        assert r.suffix_lookup(fp, tmp_path) == _suffix_match(fp, tmp_path, _is_file), fp


def test_images_folder_set_one_level_too_deep_still_finds_photos(tmp_path):
    """The CamtrapDP folder picked as images folder by mistake: the photos,
    next to it, are found through the data folder / the folder's parent."""
    from camtrap_workflow import MediaResolver
    from services.session_service import media_extra_bases

    root = tmp_path / "2023_optimized"
    photo = root / "R0025" / "dep1" / "a.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"x")
    (root / "camtrapDP").mkdir()
    mac = "/Volumes/T7 Shield/x/2023_optimized/R0025/dep1/a.jpg"
    wrong = str(root / "camtrapDP")
    r = MediaResolver(wrong, Path(wrong), extra_bases=media_extra_bases(str(root / "camtrapDP"), wrong))
    assert r.resolve(mac, "dep1", "a.jpg") == photo


def test_existing_filepath_wins_over_extra_folders(tmp_path):
    from camtrap_workflow import MediaResolver

    real = tmp_path / "real" / "dep1" / "a.jpg"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"x")
    copy = tmp_path / "other" / "dep1" / "a.jpg"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b"x")
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    r = MediaResolver(str(imgs), imgs, extra_bases=(str(tmp_path / "other"),))
    assert r.resolve(str(real), "nope", "a.jpg") == real
