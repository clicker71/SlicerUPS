"""Thin HTTP + WebSocket transport for the UPS-RS client.

Dependency-light and injectable: the HTTP session and the WebSocket factory
are passed in (or defaulted lazily), so the core can be tested without a
network and without importing `qt`/`slicer`.

Requests are plain `requests`; the WebSocket is `websocket-client`
(`websocket.create_connection`). Both are standard, synchronous, and bundled
by 3D Slicer.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional
from urllib.parse import urlencode

log = logging.getLogger("slicer_ups_client")


class DicomwebError(Exception):
    """A non-2xx/3xx DICOMweb response."""

    def __init__(self, status: int, message: str, body: Optional[bytes] = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.body = body


class DicomwebClient:
    def __init__(
        self,
        root_url: str,
        token: Optional[str] = None,
        session: Any = None,
        websocket_factory: Optional[Callable[..., Any]] = None,
        timeout: float = 30.0,
    ) -> None:
        self.root_url = root_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        if session is None:
            import requests  # deferred: tests may inject a stub

            session = requests.Session()
        self._session = session
        self._websocket_factory = websocket_factory

    # -- transport helpers ------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.root_url}/{path.lstrip('/')}"

    def _headers(self, content_type: Optional[str] = None) -> dict:
        headers: dict[str, str] = {"Accept": "application/dicom+json"}
        if content_type is not None:
            headers["Content-Type"] = content_type
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _raise_for(self, response: Any) -> None:
        if 200 <= response.status_code < 300:
            return
        body = None
        try:
            body = response.content
        except Exception:  # noqa: BLE001 - body is best-effort for the error
            pass
        raise DicomwebError(response.status_code, response.reason, body)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Any = None,
        raw: bool = False,
    ) -> Any:
        url = self._url(path)
        kwargs: dict[str, Any] = {"headers": self._headers(None), "timeout": self.timeout}
        if params:
            kwargs["params"] = params
        if json is not None:
            kwargs["json"] = json
            kwargs["headers"] = self._headers("application/dicom+json")
        response = self._session.request(method, url, **kwargs)
        self._raise_for(response)
        if raw or method.upper() == "HEAD":
            return response
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Optional[dict] = None, raw: bool = False) -> Any:
        return self.request("POST", path, json=body, raw=raw)

    def put(self, path: str, body: dict, raw: bool = False) -> Any:
        return self.request("PUT", path, json=body, raw=raw)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # -- WebSocket ---------------------------------------------------------
    def open_websocket(self, url: str, timeout: Optional[float] = None) -> Any:
        if self._websocket_factory is not None:
            return self._websocket_factory(url)
        import websocket  # websocket-client, deferred

        return websocket.create_connection(
            url, timeout=timeout if timeout is not None else self.timeout
        )


def encode_query(params: dict) -> str:
    """Encode UPS-RS search keys into a query string (PS3.18 8.3)."""
    pairs = [(key, value) for key, value in params.items() if value is not None]
    return urlencode(pairs)
