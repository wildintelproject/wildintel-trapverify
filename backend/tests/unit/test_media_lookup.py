"""Finding photos: by the end of filePath, by deployment folder, in extra folders (ported from the fork)."""
from pathlib import Path

import pandas as pd
import pytest

from camtrap_workflow import (
    _DEPLOYMENT_TREES,
    _norm_name,
    _path_parts,
    _suffix_match,
    clear_media_caches,
    gallery_frame_img_url,
    media_extra_bases,
    resolve_media_path,
)


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_media_caches()
    yield
    clear_media_caches()


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def resolve(file_path, dep, name, images, fallback=None, flat=False, extra=()):
    return resolve_media_path(file_path, dep, name, str(images) if images else "", Path(fallback or images or "."),
                              flat_search=flat, extra_bases=extra)


# ─── small helpers ────────────────────────────────────────────────────────────

def test_norm_name_folds_case_and_equivalent_extensions():
    assert _norm_name("IMG_1.JPEG") == _norm_name("img_1.jpg") == "img_1.jpg"
    assert _norm_name("a.TIFF") == "a.tif" and _norm_name("a.png") == "a.png"


def test_path_parts_reads_any_operating_system_and_drops_the_drive():
    assert _path_parts("/Volumes/Disk/2023/R0025/x.jpg") == ["Volumes", "Disk", "2023", "R0025", "x.jpg"]
    assert _path_parts("D:\\fotos\\R0025\\x.jpg") == ["fotos", "R0025", "x.jpg"]
    assert _path_parts("./a/../b//c.jpg") == ["a", "b", "c.jpg"]


# ─── end of filePath ──────────────────────────────────────────────────────────

def test_end_of_file_path_finds_photos_exported_on_another_computer(tmp_path):
    photo = touch(tmp_path / "images" / "R0025" / "dep_0011" / "x.jpg")
    mac = "/Volumes/Disk/2023/R0025/dep_0011/x.jpg"
    assert resolve(mac, "dep_0011", "x.jpg", tmp_path / "images") == photo


def test_end_of_file_path_accepts_windows_paths(tmp_path):
    photo = touch(tmp_path / "images" / "R0025" / "dep_0011" / "x.jpg")
    assert resolve("D:\\2023\\R0025\\dep_0011\\x.jpg", "dep_x", "x.jpg", tmp_path / "images") == photo


def test_end_of_file_path_never_matches_a_bare_name_at_the_root(tmp_path):
    touch(tmp_path / "images" / "x.jpg")
    # a one-part path is not looked up by suffix (the flat search is the tool for loose photos)
    assert _suffix_match("x.jpg", tmp_path / "images") is None
    assert _suffix_match("a/x.jpg", tmp_path / "images") is None                  # two parts, but no such folder
    assert _suffix_match("https://t/media/1/file/", tmp_path / "images") is None  # remote addresses are never local


def test_structured_layout_still_wins(tmp_path):
    structured = touch(tmp_path / "images" / "dep_1" / "x.jpg")
    touch(tmp_path / "images" / "R" / "dep_1" / "x.jpg")
    assert resolve("/other/R/dep_1/x.jpg", "dep_1", "x.jpg", tmp_path / "images") == structured


# ─── deployment folder ────────────────────────────────────────────────────────

def test_deployment_folder_finds_trapper_style_photos(tmp_path):
    photo = touch(tmp_path / "images" / "R0025" / "dep_0011" / "x.jpg")          # 2 levels down
    url = "https://trap.example/storage/resource/media/4897674/file/"
    assert resolve(url, "dep_0011", "x.jpg", tmp_path / "images") == photo


def test_deployment_folder_ignores_case_of_the_folder_and_the_extension(tmp_path):
    photo = touch(tmp_path / "images" / "R0025" / "DEP_0011" / "x.jpg")
    assert resolve("https://t/file/", "dep_0011", "X.JPEG", tmp_path / "images") == photo


def test_deployment_folder_gives_up_below_three_levels(tmp_path):
    touch(tmp_path / "images" / "a" / "b" / "c" / "dep_0011" / "x.jpg")           # 4 levels down
    assert not resolve("https://t/file/", "dep_0011", "x.jpg", tmp_path / "images").exists()
    touch(tmp_path / "images2" / "a" / "b" / "dep_0011" / "x.jpg")                # 3 levels down
    assert resolve("https://t/file/", "dep_0011", "x.jpg", tmp_path / "images2").exists()


def test_a_photo_in_two_deployment_folders_is_ambiguous_and_not_used(tmp_path, caplog):
    touch(tmp_path / "images" / "A" / "dep_1" / "x.jpg")
    touch(tmp_path / "images" / "B" / "dep_1" / "x.jpg")
    got = resolve("https://t/file/", "dep_1", "x.jpg", tmp_path / "images")
    assert not got.exists() and "found in 2 folders" in caplog.text


def test_deployment_folder_only_looks_as_deep_as_needed(tmp_path):
    touch(tmp_path / "images" / "dep_1" / "deep" / "deeper" / "y.jpg")
    touch(tmp_path / "images" / "G" / "dep_2" / "x.jpg")
    resolve("https://t/file/", "dep_2", "x.jpg", tmp_path / "images")
    tree = _DEPLOYMENT_TREES[str(tmp_path / "images")]
    assert tree.depth == 2                                                        # found at level 2: no third listing


# ─── flat search ──────────────────────────────────────────────────────────────

def test_flat_search_ignores_the_extension_difference(tmp_path):
    photo = touch(tmp_path / "images" / "loose" / "x.jpg")
    assert resolve("https://t/file/", "dep", "X.JPEG", tmp_path / "images", flat=True) == photo


# ─── other folders ────────────────────────────────────────────────────────────

def test_images_folder_set_one_level_too_deep_still_finds_the_photos(tmp_path):
    photo = touch(tmp_path / "pics" / "R0025" / "dep" / "x.jpg")
    too_deep = tmp_path / "pics" / "R0025"                                        # the user picked R0025 itself
    extra = media_extra_bases(str(tmp_path / "data"), str(too_deep))
    assert tmp_path / "pics" in extra                                             # the parent of the images folder
    assert resolve("R0025/dep/x.jpg", "dep_zz", "x.jpg", too_deep, extra=extra) == photo


def test_camtrapdp_folder_is_searched_when_the_images_folder_does_not_have_the_photo(tmp_path):
    data = tmp_path / "data"
    photo = touch(data / "img" / "dep" / "x.jpg")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    extra = media_extra_bases(str(data), str(elsewhere))
    assert resolve("img/dep/x.jpg", "dep", "x.jpg", elsewhere, extra=extra) == photo


def test_without_an_images_folder_the_end_of_file_path_is_tried_under_the_data_folder(tmp_path):
    data = tmp_path / "data"
    photo = touch(data / "R0025" / "dep" / "x.jpg")
    assert resolve("/Volumes/Disk/R0025/dep/x.jpg", "dep", "x.jpg", None, fallback=data) == photo


def test_a_file_that_exists_as_written_is_not_replaced_by_the_extra_folders(tmp_path):
    data = tmp_path / "data"
    touch(data / "img" / "x.jpg")
    written = touch(tmp_path / "pics" / "img" / "x.jpg")
    images = tmp_path / "pics"
    extra = media_extra_bases(str(data), str(images))
    assert resolve(str(written), "d", "x.jpg", images, extra=extra) == written


def test_media_extra_bases_without_an_images_folder_is_empty(tmp_path):
    assert media_extra_bases(str(tmp_path), "") == ()


def test_clear_media_caches_forgets_folder_listings(tmp_path):
    images = tmp_path / "images"
    (images / "G" / "dep_1").mkdir(parents=True)
    assert not resolve("https://t/file/", "dep_1", "x.jpg", images).exists()
    touch(images / "G" / "dep_1" / "x.jpg")
    assert not resolve("https://t/file/", "dep_1", "x.jpg", images).exists()      # still cached
    clear_media_caches()
    assert resolve("https://t/file/", "dep_1", "x.jpg", images).exists()


# ─── gallery URL ──────────────────────────────────────────────────────────────

def test_remote_file_path_is_served_locally_when_found_by_deployment_folder(tmp_path):
    touch(tmp_path / "images" / "R0025" / "dep_0011" / "x.jpg")
    url = gallery_frame_img_url("https://t/media/1/file/", "m1", "dep_0011", "x.jpg",
                                str(tmp_path / "images"), tmp_path / "images")
    assert url == "/api/image/m1"


def test_remote_file_path_still_uses_the_proxy_when_nothing_is_found(tmp_path):
    (tmp_path / "images").mkdir()
    url = gallery_frame_img_url("https://t/media/1/file/", "m1", "dep_0011", "x.jpg",
                                str(tmp_path / "images"), tmp_path / "images")
    assert url.startswith("/api/proxy-image?url=")
