# -*- coding: utf-8 -*-
"""Tushare Relay HTTP adapter."""

from __future__ import annotations

from typing import Any

import pandas as pd
import requests

from .base import DataFetchError, RateLimitError


class TushareRelayClient:
    """Client for relay endpoints using ``GET {base_url}/{api_name}``."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = 30,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def query(
        self,
        api_name: str,
        fields: str = "",
        **kwargs: Any,
    ) -> pd.DataFrame:
        params = [item for item in ({**kwargs, "fields": fields}.items()) if item[1] not in (None, "")]
        url = f"{self._base_url}/{api_name}"

        try:
            response = requests.get(
                url,
                params=params,
                headers={"X-API-Key": self._api_key},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise DataFetchError(f"Tushare Relay request failed: {exc}") from exc

        if response.status_code >= 400:
            message = self._extract_error(response)
            if response.status_code == 429:
                raise RateLimitError(f"Tushare Relay rate limited: {message}")
            raise DataFetchError(f"Tushare Relay HTTP {response.status_code}: {message}")

        try:
            result = response.json()
        except ValueError as exc:
            raise DataFetchError(
                f"Tushare Relay HTTP 200 returned non-JSON response"
            ) from exc

        if result.get("ok") is False:
            message = result.get("message") or result.get("msg") or result.get("error") or "unknown error"
            raise DataFetchError(f"Tushare Relay error: {message}")

        code = result.get("code")
        if code not in (0, None):
            raise DataFetchError(
                f"Tushare Relay API error code {code}: {result.get('msg', '')}"
            )

        data = result.get("data") or {}
        columns = data.get("fields") or []
        items = data.get("items") or []
        return pd.DataFrame(items, columns=columns)

    @staticmethod
    def _extract_error(response: requests.Response) -> str:
        try:
            result = response.json()
        except ValueError:
            return response.text.strip() or response.reason or "unknown error"

        return (
            result.get("message")
            or result.get("msg")
            or result.get("detail")
            or result.get("error")
            or "unknown error"
        )

    def __getattr__(self, api_name: str):
        if api_name.startswith("_"):
            raise AttributeError(api_name)

        def caller(**kwargs) -> pd.DataFrame:
            return self.query(api_name, **kwargs)

        return caller
