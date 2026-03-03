from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ApiError(Exception):
    status_code: int
    detail: Any
    message: str


def build_auth_header(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    value = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    return {"Authorization": value}


class ApiClient:
    def __init__(self, base_url: str, token: str | None, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers = build_auth_header(self.token)
        try:
            response = self._client.request(
                method=method,
                url=path,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise ApiError(status_code=0, detail=None, message=str(exc)) from exc

        if response.status_code == 204:
            return {"message": "No Content"}

        if not response.is_success:
            detail: Any
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise ApiError(
                status_code=response.status_code,
                detail=detail,
                message=f"HTTP {response.status_code}",
            )

        try:
            return response.json()
        except ValueError:
            return {"message": response.text}

