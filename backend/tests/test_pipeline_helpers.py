"""Unit tests for AutoQuant pipeline helper extraction logic."""

from __future__ import annotations

import backend.services.auto_quant.pipeline as pl
from backend.services.auto_quant.pipeline_modules.helpers import _extract_per_pair_results


def test_extract_per_pair_results_includes_profit_factor():
    data = {
        "strategy": {
            "SmokeTestStrategy": {
                "results_per_pair": [
                    {
                        "key": "BTC/USDT",
                        "profit_total": 0.05,
                        "profit_total_abs": 50.0,
                        "profit_mean": 0.0025,
                        "trades": 20,
                        "wins": 12,
                        "losses": 8,
                        "profit_factor": 1.4,
                    },
                ],
            }
        }
    }

    extracted = _extract_per_pair_results(data, "SmokeTestStrategy")

    assert len(extracted) == 1
    assert extracted[0]["key"] == "BTC/USDT"
    assert extracted[0]["profit_factor"] == 1.4
    assert extracted[0]["trades"] == 20


def test_extract_per_pair_results_defaults_missing_profit_factor_to_zero():
    data = {
        "strategy": {
            "SmokeTestStrategy": {
                "results_per_pair": [
                    {
                        "key": "ETH/USDT",
                        "profit_total": 0.02,
                        "profit_total_abs": 20.0,
                        "profit_mean": 0.001,
                        "trades": 18,
                        "wins": 10,
                        "losses": 8,
                    },
                ],
            }
        }
    }

    extracted = _extract_per_pair_results(data, "SmokeTestStrategy")

    assert len(extracted) == 1
    assert extracted[0]["key"] == "ETH/USDT"
    assert extracted[0]["profit_factor"] == 0.0
    assert extracted[0]["trades"] == 18
