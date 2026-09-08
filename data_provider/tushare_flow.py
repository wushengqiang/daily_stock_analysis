# -*- coding: utf-8 -*-
"""Lightweight adapter for Tushare / Relay moneyflow data."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from .tushare_utils import build_tushare_client, to_tushare_stock_code


_STANDARD_FIELDS = "ts_code,trade_date,buy_md_vol,sell_md_vol,net_mf_vol,buy_lg_vol,sell_lg_vol,buy_elg_vol,sell_elg_vol,net_mf_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount"
_DEFAULT_START_DAYS = 45


def _to_fundamental_flow_context(df: pd.DataFrame, api_name: str) -> dict[str, Any]:
    """Map one Tushare / Relay fund-flow DataFrame into DSA context payload."""

    if df is None or df.empty:
        return {}

    trade_col = next((col for col in ("trade_date", "date") if col in df.columns), None)
    if trade_col is None:
        return {}
    sorted_df = df.sort_values(trade_col)
    row = sorted_df.iloc[-1]
    trade_date = str(row.get("trade_date") or row.get("date") or "")
    ts_code = str(row.get("ts_code") or row.get("code") or "")

    def _numeric(name: str) -> Any:
        try:
            return float(row.get(name, 0.0) or 0.0)
        except (TypeError, ValueError):
            return None

    stock_flow = {
        "query_date": trade_date,
        "ts_code": ts_code,
        "source": f"tushare_{api_name}",
        "main_net_inflow": _numeric("net_mf_amount"),
        "main_net_inflow_vol": _numeric("net_mf_vol"),
        "buy_lg_amount": _numeric("buy_lg_amount"),
        "sell_lg_amount": _numeric("sell_lg_amount"),
        "buy_elg_amount": _numeric("buy_elg_amount"),
        "sell_elg_amount": _numeric("sell_elg_amount"),
        "net_lg_inflow": _numeric("buy_lg_amount"),
        "net_lg_outflow": _numeric("sell_lg_amount"),
        "net_elg_inflow": _numeric("buy_elg_amount"),
        "net_elg_outflow": _numeric("sell_elg_amount"),
    }
    if stock_flow.get("main_net_inflow_vol") is not None:
        stock_flow["main_net_inflow_vol"] = round(stock_flow["main_net_inflow_vol"], 4)

    return {
        "status": "ok" if score(stock_flow) else "partial",
        "stock_flow": stock_flow,
        "sector_rankings": {},
        "source_chain": [
            {
                "provider": "tushare_relay",
                "result": "ok" if score(stock_flow) else "partial",
            }
        ],
        "errors": [],
    }


def score(payload: dict[str, Any]) -> bool:
    """Return whether stock-flow payload has a usable main flow metric."""

    for name in ("main_net_inflow", "main_net_inflow_vol", "buy_lg_amount", "sell_lg_amount"):
        if payload.get(name) is not None:
            return True
    return False


def get_tushare_capital_flow(stock_code: str, *, timeout: int = 4) -> dict[str, Any] | None:
    """Fetch the latest stock-level moneyflow from configured Tushare / Relay."""

    ts_code = to_tushare_stock_code(stock_code)
    if not ts_code:
        return None

    client = build_tushare_client(timeout=timeout)
    end = date.today()
    start = end - timedelta(days=_DEFAULT_START_DAYS)
    df = client.moneyflow(
        ts_code=ts_code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        fields=_STANDARD_FIELDS,
    )
    if df is None or df.empty:
        return None
    return _to_fundamental_flow_context(df, "moneyflow")
