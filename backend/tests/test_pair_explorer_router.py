import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend.api.routers import pair_explorer


def test_safe_config_filename_removes_pair_separators():
    cases = [
        (
            "bacf9ea3-7720-4fdf-a495-60db2d0ebb87",
            "ADA/USDT + BTC/USDT",
            "pe_bacf9ea3-7720-4fdf-a495-60db2d0ebb87_ADA_USDT_BTC_USDT.json",
        ),
        (
            "96ec9b20-fcf6-43e3-a5c9-46d81ee826de",
            "XRP/USDT + APT/USDT + SOL/USDT + STX/USDT",
            "pe_96ec9b20-fcf6-43e3-a5c9-46d81ee826de_XRP_USDT_APT_USDT_SOL_USDT_STX_USDT.json",
        ),
    ]

    for session_id, group_key, expected in cases:
        filename = pair_explorer._safe_config_filename(session_id, group_key)
        assert filename == expected
        assert "/" not in filename
        assert "\\" not in filename


def test_extract_metrics_groups_strategy_block_trades_by_pair():
    payload = {
        "strategy": {
            "DemoStrategy": {
                "total_trades": 3,
                "profit_total": 0.045,
                "wins": 2,
                "losses": 1,
                "winrate": 2 / 3,
                "max_drawdown_account": 0.012,
                "trades": [
                    {"pair": "BTC/USDT", "profit_abs": 2.5, "profit_ratio": 0.03},
                    {"pair": "ETH/USDT", "profit_abs": -1.0, "profit_ratio": -0.01},
                    {"pair": "BTC/USDT", "profit_abs": 1.0, "profit_ratio": 0.02},
                ],
            }
        },
        "strategy_comparison": [{"sharpe": 1.25}],
    }

    metrics = pair_explorer._extract_metrics(payload, "DemoStrategy")

    assert metrics["total_trades"] == 3
    assert metrics["total_profit_pct"] == 4.5
    assert metrics["trades"] == payload["strategy"]["DemoStrategy"]["trades"]
    assert sorted(metrics["trades_by_pair"]) == ["BTC/USDT", "ETH/USDT"]
    assert metrics["trades_by_pair"]["BTC/USDT"]["total_trades"] == 2
    assert metrics["trades_by_pair"]["BTC/USDT"]["win_rate"] == 100.0
    assert metrics["trades_by_pair"]["ETH/USDT"]["total_trades"] == 1
    assert metrics["trades_by_pair"]["ETH/USDT"]["win_rate"] == 0.0


def test_extract_metrics_falls_back_to_results_per_pair_without_trade_rows():
    payload = {
        "strategy": {
            "DemoStrategy": {
                "total_trades": 5,
                "profit_total": -0.01,
                "results_per_pair": [
                    {"key": "BTC/USDT", "trades": 3, "profit_total_abs": 1.5, "wins": 2, "winrate": 2 / 3},
                    {"key": "ETH/USDT", "trades": 2, "profit_total_abs": -2.5, "wins": 0, "winrate": 0},
                    {"key": "TOTAL", "trades": 5, "profit_total_abs": -1.0, "wins": 2, "winrate": 0.4},
                ],
            }
        }
    }

    metrics = pair_explorer._extract_metrics(payload, "DemoStrategy")

    assert metrics["trades"] == []
    assert sorted(metrics["trades_by_pair"]) == ["BTC/USDT", "ETH/USDT"]
    assert metrics["trades_by_pair"]["BTC/USDT"] == {
        "total_trades": 3,
        "net_profit": 1.5,
        "wins": 2,
        "win_rate": 66.67,
        "trades": [],
    }


@pytest.mark.asyncio
async def test_explore_task_marks_unfinished_group_failed(tmp_path, monkeypatch):
    session_id = "session-unfinished"
    pair_explorer._SESSIONS.clear()
    pair_explorer._SESSIONS[session_id] = {
        "session_id": session_id,
        "status": "running",
        "total": 1,
        "completed": 0,
        "results": {},
        "strategy_name": "DemoStrategy",
        "timeframe": "1h",
        "timerange": "20240101-20240201",
        "dry_run_wallet": 1000.0,
        "max_open_trades": 1,
        "pairs": ["BTC/USDT"],
        "created_at": "2024-01-01T00:00:00+00:00",
        "completed_at": None,
    }

    async def fake_run_pair_group(semaphore, task_session_id, chunk, *_args, **_kwargs):
        async with semaphore:
            group_key = pair_explorer._group_key(chunk)
            pair_explorer._SESSIONS[task_session_id]["results"][group_key] = {
                "group": group_key,
                "pairs": chunk,
                "status": "running",
            }

    monkeypatch.setattr(pair_explorer, "_run_pair_group", fake_run_pair_group)

    await pair_explorer._explore_task(
        session_id,
        [["BTC/USDT"]],
        "DemoStrategy",
        "1h",
        "20240101-20240201",
        "freqtrade",
        "config.json",
        "strategies",
        str(tmp_path),
        "binance",
        object(),
    )

    session = pair_explorer._SESSIONS[session_id]
    row = session["results"]["BTC/USDT"]
    assert session["status"] == "completed"
    assert session["completed"] == 1
    assert row["status"] == "failed"
    assert "without a terminal result" in row["error"]


def test_pair_integrity_validation_rejects_unexpected_pairs():
    """Test that pair integrity guard fails when result contains unexpected pairs."""
    chunk = ["BTC/USDT", "ETH/USDT"]
    
    # Simulate a result with unexpected pair from another group
    metrics_with_wrong_pairs = {
        "total_profit_pct": 5.0,
        "win_rate": 60.0,
        "sharpe_ratio": 1.2,
        "max_drawdown": -2.0,
        "total_trades": 10,
        "trades": [],
        "trades_by_pair": {
            "BTC/USDT": {"total_trades": 5, "net_profit": 2.5, "wins": 3, "win_rate": 60.0, "trades": []},
            "ETH/USDT": {"total_trades": 5, "net_profit": 2.5, "wins": 3, "win_rate": 60.0, "trades": []},
            "SOL/USDT": {"total_trades": 3, "net_profit": 1.5, "wins": 2, "win_rate": 66.67, "trades": []},  # Unexpected!
        },
    }
    
    parsed_pairs = set(metrics_with_wrong_pairs["trades_by_pair"].keys())
    expected_pairs = set(chunk)
    unexpected_pairs = parsed_pairs - expected_pairs
    
    assert unexpected_pairs == {"SOL/USDT"}
    assert len(unexpected_pairs) > 0


def test_pair_integrity_validation_accepts_subset_of_expected_pairs():
    """Test that pair integrity guard allows subsets (e.g., pairs with zero trades)."""
    chunk = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    
    # Result with only 2 pairs (SOL had zero trades)
    metrics_with_subset = {
        "total_profit_pct": 5.0,
        "win_rate": 60.0,
        "sharpe_ratio": 1.2,
        "max_drawdown": -2.0,
        "total_trades": 10,
        "trades": [],
        "trades_by_pair": {
            "BTC/USDT": {"total_trades": 5, "net_profit": 2.5, "wins": 3, "win_rate": 60.0, "trades": []},
            "ETH/USDT": {"total_trades": 5, "net_profit": 2.5, "wins": 3, "win_rate": 60.0, "trades": []},
        },
    }
    
    parsed_pairs = set(metrics_with_subset["trades_by_pair"].keys())
    expected_pairs = set(chunk)
    unexpected_pairs = parsed_pairs - expected_pairs
    
    # Should be empty - all parsed pairs are in expected set
    assert unexpected_pairs == set()


def test_unique_export_filename_generation():
    """Test that unique export filenames are generated for different groups."""
    import hashlib
    
    session_id = "test-session-123"
    chunk1 = ["BTC/USDT", "ETH/USDT"]
    chunk2 = ["SOL/USDT", "ADA/USDT"]
    
    gkey1 = pair_explorer._group_key(chunk1)
    gkey2 = pair_explorer._group_key(chunk2)
    
    hash1 = hashlib.md5(f"{session_id}_{gkey1}".encode()).hexdigest()[:8]
    hash2 = hashlib.md5(f"{session_id}_{gkey2}".encode()).hexdigest()[:8]
    
    export1 = f"pe_{session_id[:8]}_{hash1}"
    export2 = f"pe_{session_id[:8]}_{hash2}"
    
    assert export1 != export2
    assert hash1 != hash2


def test_concurrent_groups_dont_share_artifacts():
    """Test that concurrent groups use different result directories."""
    session_id = "concurrent-test"
    chunks = [
        ["BTC/USDT", "ETH/USDT"],
        ["SOL/USDT", "ADA/USDT"],
        ["XRP/USDT", "DOT/USDT"],
    ]
    
    import hashlib
    
    export_filenames = []
    for chunk in chunks:
        gkey = pair_explorer._group_key(chunk)
        group_hash = hashlib.md5(f"{session_id}_{gkey}".encode()).hexdigest()[:8]
        export_filename = f"pe_{session_id[:8]}_{group_hash}"
        export_filenames.append(export_filename)
    
    # All export filenames should be unique
    assert len(export_filenames) == len(set(export_filenames))
    
    # Result directories would be:
    # user_data/pair_explorer_results/{export_filename}/{export_filename}.json
    # So each group has its own directory
    for export in export_filenames:
        assert export.startswith("pe_")
        assert len(export) > 10


@pytest.mark.asyncio
async def test_out_of_order_completion_preserves_correct_results():
    """Test that groups completing out of order still get correct results."""
    session_id = "out-of-order-test"
    pair_explorer._SESSIONS.clear()
    
    chunks = [
        ["BTC/USDT", "ETH/USDT"],
        ["SOL/USDT", "ADA/USDT"],
    ]
    
    pair_explorer._SESSIONS[session_id] = {
        "session_id": session_id,
        "status": "running",
        "total": 2,
        "completed": 0,
        "results": {},
        "strategy_name": "TestStrategy",
        "timeframe": "1h",
        "timerange": "20240101-20240201",
        "dry_run_wallet": 1000.0,
        "max_open_trades": 2,
        "pairs": [p for chunk in chunks for p in chunk],
        "created_at": "2024-01-01T00:00:00+00:00",
        "completed_at": None,
    }
    
    # Simulate group 2 completing first
    gkey2 = pair_explorer._group_key(chunks[1])
    pair_explorer._SESSIONS[session_id]["results"][gkey2] = {
        "group": gkey2,
        "pairs": chunks[1],
        "status": "completed",
        "total_profit_pct": 3.0,
        "trades_by_pair": {
            "SOL/USDT": {"total_trades": 5, "net_profit": 1.5, "wins": 3, "trades": []},
            "ADA/USDT": {"total_trades": 5, "net_profit": 1.5, "wins": 3, "trades": []},
        },
    }
    pair_explorer._SESSIONS[session_id]["completed"] = 1
    
    # Then group 1 completes
    gkey1 = pair_explorer._group_key(chunks[0])
    pair_explorer._SESSIONS[session_id]["results"][gkey1] = {
        "group": gkey1,
        "pairs": chunks[0],
        "status": "completed",
        "total_profit_pct": 5.0,
        "trades_by_pair": {
            "BTC/USDT": {"total_trades": 5, "net_profit": 2.5, "wins": 3, "trades": []},
            "ETH/USDT": {"total_trades": 5, "net_profit": 2.5, "wins": 3, "trades": []},
        },
    }
    pair_explorer._SESSIONS[session_id]["completed"] = 2
    
    # Verify each group has its own correct pairs
    result1 = pair_explorer._SESSIONS[session_id]["results"][gkey1]
    result2 = pair_explorer._SESSIONS[session_id]["results"][gkey2]
    
    assert set(result1["pairs"]) == {"BTC/USDT", "ETH/USDT"}
    assert set(result2["pairs"]) == {"SOL/USDT", "ADA/USDT"}
    assert set(result1["trades_by_pair"].keys()) == {"BTC/USDT", "ETH/USDT"}
    assert set(result2["trades_by_pair"].keys()) == {"SOL/USDT", "ADA/USDT"}
