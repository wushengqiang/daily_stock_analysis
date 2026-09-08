# -*- coding: utf-8 -*-
"""Shared Tushare / Relay access helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from src.config import get_config

if TYPE_CHECKING:
    from .tushare_fetcher import _TushareHttpClient
    from .tushare_relay_client import TushareRelayClient


@dataclass(frozen=True)
class TushareAccess:
    """Normalized access mode and credentials for Tushare / Relay calls."""

    mode: str
    base_url: str
    api_key: str
    token: str

    @property
    def is_relay(self) -> bool:
        return self.mode == "relay"

    @property
    def is_ready(self) -> bool:
        if self.is_relay:
            return bool(self.base_url and self.api_key)
        return bool(self.token)


def _resolve_tushare_access(config: Any = None) -> TushareAccess:
    """Resolve access mode from config, with env fallbacks."""

    raw_mode = getattr(config, "tushare_api_mode", None)
    if raw_mode in (None, ""):
        raw_mode = os.getenv("TUSHARE_API_MODE")
    mode = str(raw_mode or "tushare").strip().lower()
    if mode not in ("tushare", "relay"):
        raise ValueError(
            "TUSHARE_API_MODE 仅支持 tushare 或 relay，当前值为 "
            f"{raw_mode!r}"
        )

    relay_base = getattr(config, "tushare_relay_base_url", None)
    if relay_base in (None, ""):
        relay_base = os.getenv("TUSHARE_RELAY_BASE_URL")
    relay_key = getattr(config, "tushare_relay_key", None)
    if relay_key in (None, ""):
        relay_key = os.getenv("TUSHARE_RELAY_KEY")
    token = getattr(config, "tushare_token", None)
    if token in (None, ""):
        token = os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_API_TOKEN")

    return TushareAccess(
        mode=mode,
        base_url=str(relay_base or "").strip(),
        api_key=str(relay_key or "").strip(),
        token=str(token or "").strip(),
    )


def has_tushare_access(config: Any = None) -> bool:
    """Whether a Tushare or Relay call can be attempted before fallback."""

    access = _resolve_tushare_access(config)
    return access.is_ready


def build_tushare_client(config: Any = None, *, timeout: int = 30) -> _TushareHttpClient | TushareRelayClient:
    """Build a Tushare client according to the access mode."""

    access = _resolve_tushare_access(config)
    if not access.is_ready:
        raise ValueError("TUSHARE/Relay 配置不可用，无法创建 Tushare 客户端")
    if access.is_relay:
        from .tushare_relay_client import TushareRelayClient

        return TushareRelayClient(api_key=access.api_key, base_url=access.base_url, timeout=timeout)

    api_url = os.getenv("TUSHARE_HTTP_URL")
    from .tushare_fetcher import _TushareHttpClient

    return _TushareHttpClient(
        token=access.token,
        api_url=api_url or "http://api.tushare.pro",
        timeout=timeout,
    )


def to_tushare_stock_code(stock_code: str, *exchange_hint: str) -> str:
    """Map a 6-digit A-share/BSE code to Tushare's ``ts_code`` form."""

    from .base import normalize_stock_code

    normalized = normalize_stock_code(stock_code)
    if not normalized:
        return ""

    if exchange_hint and exchange_hint[0].upper() in {"SH", "SZ", "BJ"}:
        return f"{normalized}.{exchange_hint[0].upper()}"

    if normalized.startswith(("4", "8", "920")):
        return f"{normalized}.BJ"
    if normalized.startswith(("6", "9", "5")):
        return f"{normalized}.SH"
    return f"{normalized}.SZ"
