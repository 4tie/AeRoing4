"""Configuration constants and helpers for the Auto-Quant pipeline."""

from __future__ import annotations

import calendar
from datetime import date

# ── WFO date helpers ──────────────────────────────────────────────────────────

def _parse_yyyymmdd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _fmt_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _add_months(d: date, months: int) -> date:
    """Add N calendar months, clamping to the last valid day of the target month."""
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _generate_wfo_windows(
    in_sample_range: str,
    is_months: int,
    oos_months: int,
    min_is_days: int = 30,
    min_oos_days: int = 7,
) -> list[tuple[str, str]]:
    """Generate rolling (IS_range, OOS_range) pairs from the in-sample period.

    Step size equals oos_months so OOS windows are non-overlapping.
    Windows that are too short are silently skipped.
    Returns list of ("YYYYMMDD-YYYYMMDD", "YYYYMMDD-YYYYMMDD") pairs.
    """
    parts = in_sample_range.split("-", 1)
    if len(parts) != 2 or len(parts[0]) != 8 or len(parts[1]) != 8:
        return []
    try:
        full_start = _parse_yyyymmdd(parts[0])
        full_end   = _parse_yyyymmdd(parts[1])
    except (ValueError, IndexError):
        return []

    windows: list[tuple[str, str]] = []
    window_start = full_start

    while True:
        is_start  = window_start
        is_end    = _add_months(is_start, is_months)
        oos_start = is_end
        oos_end   = _add_months(oos_start, oos_months)

        if oos_end > full_end:
            break

        if (is_end - is_start).days >= min_is_days and (oos_end - oos_start).days >= min_oos_days:
            windows.append((
                f"{_fmt_yyyymmdd(is_start)}-{_fmt_yyyymmdd(is_end)}",
                f"{_fmt_yyyymmdd(oos_start)}-{_fmt_yyyymmdd(oos_end)}",
            ))

        window_start = _add_months(window_start, oos_months)

    return windows


# ── Constants ─────────────────────────────────────────────────────────────────

STAGE_NAMES = [
    "Pre-Flight Filtering",
    "Portfolio Baseline Backtest",
    "Standard Hyperopt",
    "Robustness Testing",
    "Portfolio Competition",
    "Delivery",
]

DEFAULT_STRESS_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "DOGE/USDT", "DOT/USDT", "MATIC/USDT", "LINK/USDT",
]

# Pre-Selection: Number of top pairs to select in Stage 1
TOP_PAIRS_SELECTION_COUNT = 4  # Select top 3-4 pairs in Stage 1

# Broad universe for Omni-Strategy multi-pair backtesting (Top 50 by volume)
BROAD_UNIVERSE_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT",
    "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT",
    "FIL/USDT", "NEAR/USDT", "ALGO/USDT", "VET/USDT", "ICP/USDT",
    "OP/USDT", "ARB/USDT", "PEPE/USDT", "SHIB/USDT", "RNDR/USDT",
    "INJ/USDT", "APT/USDT", "QNT/USDT", "AAVE/USDT", "MKR/USDT",
    "CRV/USDT", "COMP/USDT", "YFI/USDT", "SNX/USDT", "KAVA/USDT",
    "ROSE/USDT", "FTM/USDT", "GLM/USDT", "GRT/USDT", "LDO/USDT",
    "FXS/USDT", "PENDLE/USDT", "GMX/USDT", "GALA/USDT", "SAND/USDT",
    "MANA/USDT", "AXS/USDT", "ENJ/USDT", "IMX/USDT", "SUI/USDT",
]

# Thresholds for Stage 6 (all in decimal format)
MAX_DRAWDOWN_THRESHOLD = 0.30   # 30% maximum drawdown
MIN_WIN_RATE = 0.40             # 40% minimum win rate
MIN_PROFIT_FACTOR = 1.0
MIN_SHARPE = 0.5
MIN_OOS_PROFIT = 0.0            # total profit must be >= 0
MONTE_CARLO_THRESHOLD = 0.20    # 20% maximum 95th-percentile drawdown

# ── AutoQuant Feature Flags ───────────────────────────────────────────────────
# These master switches control which advanced features are enabled in the active workflow.
# Backend implementations remain intact for future reactivation.

# Self-Healing: Auto-fix, AI recovery, retry loops, automatic feature injection
AUTOQUANT_SELF_HEALING_ENABLED = False

# Regime Detection: Market regime detection and adaptive hyperopt configuration
AUTOQUANT_REGIME_DETECTION_ENABLED = False

# Genetic Algorithm Evolution: Stage 2.5 genetic optimization
AUTOQUANT_GENETIC_ALGORITHM_ENABLED = False

# Reinforcement Learning: Stage 3.5 RL training and Stage 4.5 RL deployment
AUTOQUANT_REINFORCEMENT_LEARNING_ENABLED = False

# Walk-Forward Optimization: Rolling WFO windows vs Standard Hyperopt
AUTOQUANT_WFO_ENABLED = False

# ── Ollama Integration Settings ───────────────────────────────────────────────

OLLAMA_ENABLED = True  # Master switch for AI features
OLLAMA_TIMEOUT = 30  # Seconds for generate requests
OLLAMA_HEALTH_CHECK_TIMEOUT = 5  # Seconds for health checks
OLLAMA_MAX_RETRIES = 1  # Retry failed requests once
OLLAMA_STRICT_JSON = True  # Use format="json" parameter
# Note: OLLAMA_BASE_URL and OLLAMA_MODEL are read from settings (data/strategy_lab_settings.json)

# ── Dynamic timeframe → profitability threshold profiles ──────────────────────

_TIMEFRAME_PROFILES: dict[str, dict] = {
    "1m":  {
        "profile": "Scalping",
        "min_oos_profit": 0.05,
        "max_drawdown_threshold": 0.20,  # 20%
        "min_win_rate": 0.40,  # 40%
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "description": "High trade count, tight stops, small per-trade profit target",
    },
    "3m":  {
        "profile": "Scalping",
        "min_oos_profit": 0.05,
        "max_drawdown_threshold": 0.20,  # 20%
        "min_win_rate": 0.40,  # 40%
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "description": "High trade count, tight stops, small per-trade profit target",
    },
    "5m":  {
        "profile": "Scalping",
        "min_oos_profit": 0.04,
        "max_drawdown_threshold": 0.25,  # 25%
        "min_win_rate": 0.40,  # 40%
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "description": "High trade count, tight stops, small per-trade profit target",
    },
    "15m": {
        "profile": "Scalping",
        "min_oos_profit": 0.03,
        "max_drawdown_threshold": 0.30,  # 30%
        "min_win_rate": 0.40,  # 40%
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "description": "High trade count, tight stops, small per-trade profit target",
    },
    "30m": {
        "profile": "Intraday",
        "min_oos_profit": 0.025,
        "max_drawdown_threshold": 0.325,  # 32.5%
        "min_win_rate": 0.40,  # 40%
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "description": "Balanced between scalping cadence and swing-style profit targets",
    },
    "1h":  {
        "profile": "Swing",
        "min_oos_profit": 0.02,
        "max_drawdown_threshold": 0.35,  # 35%
        "min_win_rate": 0.40,  # 40%
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "description": "Fewer trades, higher per-trade profit requirement, wider stops",
    },
    "4h":  {
        "profile": "Swing",
        "min_oos_profit": 0.015,
        "max_drawdown_threshold": 0.40,  # 40%
        "min_win_rate": 0.40,  # 40%
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "description": "Fewer trades, higher per-trade profit requirement, wider stops",
    },
    "1d":  {
        "profile": "Position",
        "min_oos_profit": 0.01,
        "max_drawdown_threshold": 0.45,  # 45%
        "min_win_rate": 0.40,  # 40%
        "min_profit_factor": 1.0,
        "min_sharpe": 0.5,
        "description": "Long-term holds, highest profit target, widest stop tolerance",
    },
}

_DEFAULT_PROFILE = {
    "profile": "Standard",
    "min_oos_profit": MIN_OOS_PROFIT,
    "max_drawdown_threshold": MAX_DRAWDOWN_THRESHOLD,
    "min_win_rate": MIN_WIN_RATE,
    "min_profit_factor": MIN_PROFIT_FACTOR,
    "min_sharpe": MIN_SHARPE,
    "description": "Default thresholds",
}


def get_timeframe_thresholds(timeframe: str) -> dict:
    """Return profitability thresholds calibrated to *timeframe*.

    Returns a dict with keys: profile, min_oos_profit, max_drawdown_threshold,
    min_win_rate, min_profit_factor, min_sharpe, description.
    Falls back to module-level defaults for unknown timeframes.
    """
    try:
        from ..policy import get_public_timeframe_thresholds

        return get_public_timeframe_thresholds(timeframe)
    except Exception:
        profile = dict(_TIMEFRAME_PROFILES.get(timeframe, _DEFAULT_PROFILE))
        if profile.get("max_drawdown_threshold", 0) <= 1:
            profile["max_drawdown_threshold"] = profile["max_drawdown_threshold"] * 100
        if profile.get("min_win_rate", 0) <= 1:
            profile["min_win_rate"] = profile["min_win_rate"] * 100
        return profile
