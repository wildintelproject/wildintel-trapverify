"""Unit tests for services.trapper_service — the wildintel-trapper-sdk wrapper.

TrapperClient itself is mocked throughout; these tests only verify that
trapper_service builds the right calls and shapes the results correctly.

No async test runner (pytest-asyncio/anyio) is configured in this project,
so every async call is driven with plain asyncio.run() from ordinary
(synchronous) test functions.
"""
from __future__ import annotations

import asyncio
import gzip
import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from trapper_client import err


@pytest.fixture(autouse=True)
def reset_state():
    """Every test starts with no active connection and no background tasks."""
    import services.trapper_service as trapper_service
    trapper_service._client = None
    trapper_service._base_url = None
    trapper_service._tasks = {}
    yield
    trapper_service._client = None
    trapper_service._base_url = None
    trapper_service._tasks = {}


def _project(pk, name, **extra):
    obj = MagicMock()
    obj.pk = pk
    obj.name = name
    for k, v in extra.items():
        setattr(obj, k, v)
    return obj


def _make_zip_bytes(filename: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, content)
    return buf.getvalue()


# ─── login ──────────────────────────────────────────────────────────────────

def test_login_success_stores_client_and_returns_count():
    import services.trapper_service as trapper_service

    page = MagicMock()
    page.pagination.count = 7
    fake_client = MagicMock()
    fake_client.research_projects.get.return_value = page

    with patch("services.trapper_service.TrapperClient", return_value=fake_client) as ctor:
        result = asyncio.run(
            trapper_service.login("https://trapper.example", "user@example.com", "pw")
        )

    ctor.assert_called_once_with(
        base_url="https://trapper.example", user_name="user@example.com", user_password="pw",
    )
    fake_client.research_projects.get.assert_called_once_with(page=1, page_size=1)
    assert result == {"ok": True, "base_url": "https://trapper.example", "research_projects_count": 7}
    assert trapper_service._client is fake_client


def test_login_strips_trailing_slash_from_base_url():
    import services.trapper_service as trapper_service

    page = MagicMock()
    page.pagination.count = 0
    fake_client = MagicMock()
    fake_client.research_projects.get.return_value = page

    with patch("services.trapper_service.TrapperClient", return_value=fake_client) as ctor:
        asyncio.run(trapper_service.login("https://trapper.example/", "user", "pw"))

    assert ctor.call_args.kwargs["base_url"] == "https://trapper.example"


def test_login_raises_value_error_on_unauthorized():
    import services.trapper_service as trapper_service

    fake_client = MagicMock()
    fake_client.research_projects.get.side_effect = err.UnauthorizedError("bad credentials")

    with patch("services.trapper_service.TrapperClient", return_value=fake_client):
        with pytest.raises(ValueError, match="Credenciales incorrectas"):
            asyncio.run(trapper_service.login("https://trapper.example", "user", "wrongpw"))

    # The failed candidate must not become the active connection.
    assert trapper_service._client is None


# ─── get_research_projects ───────────────────────────────────────────────────

def test_get_research_projects_requires_login():
    import services.trapper_service as trapper_service

    with pytest.raises(RuntimeError, match="No hay conexión activa"):
        asyncio.run(trapper_service.get_research_projects())


def test_get_research_projects_shapes_results():
    import services.trapper_service as trapper_service

    fake_client = MagicMock()
    fake_client.research_projects.where.return_value = [
        _project(1, "Project One", acronym="P1"),
        _project(2, "Project Two", acronym="P2"),
    ]
    trapper_service._client = fake_client

    result = asyncio.run(trapper_service.get_research_projects())

    fake_client.research_projects.where.assert_called_once_with(page_size=500)
    assert result == [
        {"pk": 1, "name": "Project One", "acronym": "P1"},
        {"pk": 2, "name": "Project Two", "acronym": "P2"},
    ]


# ─── get_classification_projects ─────────────────────────────────────────────

def test_get_classification_projects_filters_by_exact_name_match():
    import services.trapper_service as trapper_service

    fake_client = MagicMock()
    fake_client.research_projects.find.return_value = _project(5, "Donana")
    fake_client.classification_projects.where.return_value = [
        _project(10, "CS1", is_active=True, research_project="Donana"),
        # Fuzzy search can return a project belonging to a different, similarly
        # named research project — must be excluded from the results.
        _project(11, "CS2", is_active=False, research_project="Donana Norte"),
        _project(12, "CS3", is_active=True, research_project="Donana"),
    ]
    trapper_service._client = fake_client

    result = asyncio.run(trapper_service.get_classification_projects(5))

    fake_client.research_projects.find.assert_called_once_with(pk=5)
    fake_client.classification_projects.where.assert_called_once_with(search="Donana", page_size=500)
    assert result == [
        {"pk": 10, "name": "CS1", "is_active": True},
        {"pk": 12, "name": "CS3", "is_active": True},
    ]


# ─── generate_and_download ────────────────────────────────────────────────────

def test_generate_and_download_extracts_and_decompresses(tmp_path):
    import services.trapper_service as trapper_service

    csv_bytes = gzip.compress(b"deploymentID,locationID\nDEP1,SITE_A\n")
    zip_bytes = _make_zip_bytes("deployments.csv.gz", csv_bytes)

    package_response = MagicMock()
    package_response.data.package = "https://trapper.example/download/abc?rt=token"
    package_response.data.message = "ok"
    package_response.data.errors = None

    dl_response = MagicMock()
    dl_response.content = zip_bytes

    fake_client = MagicMock()
    fake_client.classification_package.get_project_package.return_value = package_response
    fake_client.make_request.return_value = dl_response
    trapper_service._client = fake_client

    result_dir = asyncio.run(
        trapper_service.generate_and_download(42, tmp_path, clear_cache=True)
    )

    fake_client.classification_package.get_project_package.assert_called_once_with(
        project_pk=42, export_format="camtrapdp", export_filetype="csv.gz", clear_cache="true",
    )
    fake_client.make_request.assert_called_once_with(
        endpoint="https://trapper.example/download/abc?rt=token", method="GET",
    )
    assert result_dir == tmp_path / "camtrap_dp"
    extracted_csv = result_dir / "deployments.csv"
    assert extracted_csv.exists()
    assert not (result_dir / "deployments.csv.gz").exists()
    assert extracted_csv.read_bytes() == b"deploymentID,locationID\nDEP1,SITE_A\n"


def test_generate_and_download_passes_clear_cache_false_as_string(tmp_path):
    import services.trapper_service as trapper_service

    zip_bytes = _make_zip_bytes("empty.csv", b"a,b\n")
    package_response = MagicMock()
    package_response.data.package = "https://trapper.example/download/xyz"

    fake_client = MagicMock()
    fake_client.classification_package.get_project_package.return_value = package_response
    fake_client.make_request.return_value = MagicMock(content=zip_bytes)
    trapper_service._client = fake_client

    asyncio.run(trapper_service.generate_and_download(1, tmp_path, clear_cache=False))

    assert fake_client.classification_package.get_project_package.call_args.kwargs["clear_cache"] == "false"


def test_generate_and_download_raises_when_no_package_url(tmp_path):
    import services.trapper_service as trapper_service

    package_response = MagicMock()
    package_response.data.package = None
    package_response.data.message = "Could not generate package"
    package_response.data.errors = {"deployment": ["invalid"]}

    fake_client = MagicMock()
    fake_client.classification_package.get_project_package.return_value = package_response
    trapper_service._client = fake_client

    with pytest.raises(RuntimeError, match="no devolvió URL de descarga"):
        asyncio.run(trapper_service.generate_and_download(1, tmp_path))

    fake_client.make_request.assert_not_called()


# ─── background task helpers ─────────────────────────────────────────────────

def test_start_generation_task_marks_done_on_success(tmp_path):
    import services.trapper_service as trapper_service

    zip_bytes = _make_zip_bytes("empty.csv", b"a,b\n")
    package_response = MagicMock()
    package_response.data.package = "https://trapper.example/download/1"

    fake_client = MagicMock()
    fake_client.classification_package.get_project_package.return_value = package_response
    fake_client.make_request.return_value = MagicMock(content=zip_bytes)
    trapper_service._client = fake_client

    async def _drive():
        task_id = await trapper_service.start_generation_task(1, tmp_path)
        for _ in range(50):
            if trapper_service.get_task_status(task_id)["status"] != "running":
                break
            await asyncio.sleep(0.01)
        return task_id

    task_id = asyncio.run(_drive())

    status = trapper_service.get_task_status(task_id)
    assert status["status"] == "done"
    assert status["path"] == str(tmp_path / "camtrap_dp")
    assert status["error"] is None


def test_start_generation_task_marks_error_on_failure(tmp_path):
    import services.trapper_service as trapper_service

    package_response = MagicMock()
    package_response.data.package = None
    package_response.data.message = "boom"
    package_response.data.errors = None

    fake_client = MagicMock()
    fake_client.classification_package.get_project_package.return_value = package_response
    trapper_service._client = fake_client

    async def _drive():
        task_id = await trapper_service.start_generation_task(1, tmp_path)
        for _ in range(50):
            if trapper_service.get_task_status(task_id)["status"] != "running":
                break
            await asyncio.sleep(0.01)
        return task_id

    task_id = asyncio.run(_drive())

    status = trapper_service.get_task_status(task_id)
    assert status["status"] == "error"
    assert "no devolvió URL de descarga" in status["error"]


def test_get_task_status_unknown_returns_none():
    import services.trapper_service as trapper_service
    assert trapper_service.get_task_status("nonexistent") is None
