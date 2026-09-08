# -*- coding: utf-8 -*-
"""Regression tests for TushareRelayClient and its fetcher integration."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd

from data_provider.base import DataFetchError
from data_provider.tushare_relay_client import TushareRelayClient
from data_provider.tushare_fetcher import TushareFetcher


class TestTushareRelayClient(unittest.TestCase):
    """Ensure Relay requests follow the documented gateway contract."""

    def test_query_uses_get_path_and_api_key_header(self) -> None:
        client = TushareRelayClient(
            api_key="relay-key",
            base_url="https://relay.example.com/tushare/pro",
            timeout=15,
        )
        response_payload = {
            "request_id": "request-1",
            "code": 0,
            "msg": "ok",
            "data": {
                "fields": ["ts_code", "close"],
                "items": [["600519.SH", 1688.0]],
            },
        }
        response = unittest.mock.MagicMock(
            status_code=200,
            json=lambda: response_payload,
        )

        with patch("data_provider.tushare_relay_client.requests.get", return_value=response) as get_mock:
            df = client.daily(
                ts_code="600519.SH",
                start_date="20260320",
                end_date="20260325",
            )

        get_mock.assert_called_once_with(
            "https://relay.example.com/tushare/pro/daily",
            params=[
                ("ts_code", "600519.SH"),
                ("start_date", "20260320"),
                ("end_date", "20260325"),
            ],
            headers={"X-API-Key": "relay-key"},
            timeout=15,
        )
        self.assertEqual(df.to_dict(orient="records"), [{"ts_code": "600519.SH", "close": 1688.0}])

    def test_query_omits_empty_and_none_parameters(self) -> None:
        client = TushareRelayClient(api_key="relay-key", base_url="https://relay.example.com/tushare/pro")
        response = unittest.mock.MagicMock(
            status_code=200,
            json=lambda: {"code": 0, "data": {"fields": [], "items": []}},
        )

        with patch("data_provider.tushare_relay_client.requests.get", return_value=response) as get_mock:
            client.daily(trade_date="20260827", stock_name=None, market="")

        self.assertEqual(
            get_mock.call_args.kwargs["params"],
            [("trade_date", "20260827")],
        )

    def test_query_maps_unknown_api_to_datafetch_error(self) -> None:
        client = TushareRelayClient(api_key="relay-key", base_url="https://relay.example.com/tushare/pro")
        response = unittest.mock.MagicMock(
            status_code=404,
            json=lambda: {"error": "unknown_api", "message": "path not registered"},
        )

        with patch("data_provider.tushare_relay_client.requests.get", return_value=response):
            with self.assertRaisesRegex(DataFetchError, "path not registered"):
                client.unknown_api()


class TestTushareRelayFetcherIntegration(unittest.TestCase):
    """Ensure TUSHARE_API_MODE=relay routes initialization and priority."""

    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            tushare_token="",
            tushare_api_mode="relay",
            tushare_relay_base_url="https://relay.example.com/tushare/pro",
            tushare_relay_key="relay-key",
        )

    def test_init_builds_relay_client(self) -> None:
        with patch("data_provider.tushare_fetcher.get_config", return_value=self._config()):
            fetcher = TushareFetcher()

        self.assertIsInstance(fetcher._api, TushareRelayClient)
        self.assertEqual(fetcher._api._base_url, "https://relay.example.com/tushare/pro")
        self.assertEqual(fetcher.priority, -1)

    def test_init_fails_when_tushare_mode_has_no_token(self) -> None:
        config = self._config()
        config.tushare_api_mode = "tushare"

        with patch("data_provider.tushare_fetcher.get_config", return_value=config), \
                patch.dict("os.environ", {}, clear=True):
            fetcher = TushareFetcher()

        self.assertIsNone(fetcher._api)
        self.assertEqual(fetcher.priority, 2)


class TestScreeningSnapshotSourcePriority(unittest.TestCase):
    """Ensure Relay configuration promotes Tushare in snapshot ordering."""

    def test_relay_mode_uses_tushare_first_snapshot_priority(self) -> None:
        from src.services.screening.config import Config

        env = {
            "TUSHARE_API_MODE": "relay",
            "TUSHARE_RELAY_BASE_URL": "https://relay.example.com/tushare/pro",
            "TUSHARE_RELAY_KEY": "relay-key",
        }
        with patch.dict("os.environ", env, clear=False):
            snapshot_priority = Config.from_env().snapshot_source_priority

        self.assertEqual(snapshot_priority, ["tushare", "sina", "efinance", "akshare_em", "em_datacenter"])


class TestCandidateFundFlowFallback(unittest.TestCase):
    """Ensure candidate fund-flow context degrades from Relay to AkShare."""

    def test_relay_failure_falls_back_to_akshare(self) -> None:
        from src.services.screening import candidate_context
        import akshare as ak

        fallback_df = pd.DataFrame([{
            "日期": "2026-09-07",
            "主力净流入": 123.45,
            "超大单净流入": 45.67,
        }])

        with patch("data_provider.tushare_utils.has_tushare_access", return_value=True), \
                patch("data_provider.tushare_flow.get_tushare_capital_flow", side_effect=RuntimeError("relay unavailable")), \
                patch.object(ak, "stock_individual_fund_flow", return_value=fallback_df) as ak_mock:
            summary = candidate_context.fetch_stock_fund_flow_summary("600519")

        self.assertIn("主力净流入", summary)
        ak_mock.assert_called_once()


class TestTushareCapitalFlowAdapter(unittest.TestCase):
    """Ensure Relay moneyflow maps the latest row with the correct fields."""

    def test_moneyflow_requests_trade_date_and_selects_latest_row(self) -> None:
        from data_provider.tushare_flow import get_tushare_capital_flow

        client = unittest.mock.MagicMock()
        client.moneyflow.return_value = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "trade_date": "20260901",
                    "net_mf_amount": -5313.29,
                    "net_mf_vol": -426.0,
                    "buy_lg_amount": 147789.29,
                    "sell_lg_amount": 141210.43,
                    "buy_elg_amount": 89253.3,
                    "sell_elg_amount": 72546.8,
                },
                {
                    "ts_code": "600519.SH",
                    "trade_date": "20260904",
                    "net_mf_amount": 120023.0,
                    "net_mf_vol": 9064.0,
                    "buy_lg_amount": 216354.18,
                    "sell_lg_amount": 191072.62,
                    "buy_elg_amount": 151999.0,
                    "sell_elg_amount": 141868.0,
                },
            ]
        )

        with patch("data_provider.tushare_flow.build_tushare_client", return_value=client):
            payload = get_tushare_capital_flow("600519", timeout=8)

        fields = client.moneyflow.call_args.kwargs["fields"]
        self.assertIn("trade_date", fields)
        self.assertNotIn("tradedate", fields)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["stock_flow"]["query_date"], "20260904")
        self.assertEqual(payload["stock_flow"]["main_net_inflow"], 120023.0)


if __name__ == "__main__":
    unittest.main()
