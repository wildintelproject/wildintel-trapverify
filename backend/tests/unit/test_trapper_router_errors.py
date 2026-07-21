"""Unit tests for api.routers.trapper._http_exc's mapping of
wildintel-trapper-sdk's typed err.APIError subclasses to HTTP status codes."""
from __future__ import annotations

import httpx
import pytest
from trapper_client import err


@pytest.mark.parametrize("exc_cls, expected_status", [
    (err.BadRequestError, 400),
    (err.UnauthorizedError, 401),
    (err.ForbiddenError, 403),
    (err.NotFoundError, 404),
    (err.ConflictError, 409),
    (err.UnprocessableEntityError, 422),
    (err.ServerError, 500),
])
def test_maps_each_api_error_subclass_to_its_status_code(exc_cls, expected_status):
    from api.routers.trapper import _http_exc

    result = _http_exc(exc_cls("something went wrong"))

    assert result.status_code == expected_status
    assert "something went wrong" in result.detail


def test_unknown_api_error_subclass_defaults_to_400():
    from api.routers.trapper import _http_exc

    class SomeNewApiError(err.APIError):
        pass

    result = _http_exc(SomeNewApiError("new kind of error"))

    assert result.status_code == 400


def test_httpx_status_error_still_mapped_by_response_status(monkeypatch):
    from api.routers.trapper import _http_exc

    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("service unavailable", request=request, response=response)

    result = _http_exc(exc)

    assert result.status_code == 503


def test_runtime_error_maps_to_401():
    from api.routers.trapper import _http_exc

    result = _http_exc(RuntimeError("No hay conexión activa."))

    assert result.status_code == 401


def test_unrecognized_exception_defaults_to_400():
    from api.routers.trapper import _http_exc

    result = _http_exc(ValueError("weird input"))

    assert result.status_code == 400
