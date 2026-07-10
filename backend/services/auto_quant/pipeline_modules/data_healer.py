"""Data Healer module for validating and auto-downloading historical market data.

This module implements Phase 1 of the OmniFactory pipeline: intelligent data validation
that checks local historical data against target timeranges and indicator warm-up periods,
automatically downloads missing candles, and evicts pairs only when necessary (API errors
or insufficient historical depth).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .helpers import _emit, _run_subprocess
from .logging import _rlog, logger
from .state import PipelineState, _Cancelled, _cancelled


def _parse_timerange(timerange: str) -> tuple[datetime, datetime]:
    """Parse freqtrade timerange string (YYYYMMDD-YYYYMMDD) to datetime objects.
    
    Returns:
        tuple of (start_date, end_date) in UTC
    """
    try:
        parts = timerange.split("-", 1)
        if len(parts) != 2 or len(parts[0]) != 8 or len(parts[1]) != 8:
            raise ValueError(f"Invalid timerange format: {timerange}")
        
        start = datetime.strptime(parts[0], "%Y%m%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(parts[1], "%Y%m%d").replace(tzinfo=timezone.utc)
        return start, end
    except Exception as exc:
        logger.error("Data_Healer | failed to parse timerange %s: %s", timerange, exc)
        raise


def _timeframe_to_minutes(timeframe: str) -> int:
    """Convert freqtrade timeframe string to minutes.
    
    Examples: 1m -> 1, 5m -> 5, 1h -> 60, 4h -> 240, 1d -> 1440
    """
    timeframe = timeframe.lower()
    if timeframe.endswith("m"):
        return int(timeframe[:-1])
    elif timeframe.endswith("h"):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith("d"):
        return int(timeframe[:-1]) * 1440
    else:
        raise ValueError(f"Unknown timeframe format: {timeframe}")


def _get_data_file_path(pair: str, timeframe: str, user_data_dir: str) -> Path:
    """Get the path to freqtrade's local data file for a pair/timeframe.

    Freqtrade stores data as flat feather files:
        user_data_dir/data/binance/<PAIR_QUOTE>-<timeframe>.feather
    e.g. user_data/data/binance/BTC_USDT-5m.feather
    """
    from ....utils import get_data_file_path
    return get_data_file_path(user_data_dir, pair, timeframe, "binance", "feather")


def _check_pair_data_gaps(
    pair: str,
    timerange: str,
    timeframe: str,
    user_data_dir: str,
    warmup_candles: int = 200,
) -> dict[str, Any]:
    """Check local historical data for gaps against target timerange + warm-up.
    
    Args:
        pair: Trading pair (e.g., "BTC/USDT")
        timerange: Target timerange string (YYYYMMDD-YYYYMMDD)
        timeframe: Timeframe string (e.g., "5m", "1h")
        user_data_dir: Freqtrade user data directory
        warmup_candles: Number of candles to add as warm-up buffer
    
    Returns:
        dict with keys:
            - has_gaps: bool
            - missing_ranges: list of (start, end) tuples
            - available_candles: int
            - required_candles: int
            - earliest_available: datetime or None
            - latest_available: datetime or None
    """
    try:
        import json
        
        start_date, end_date = _parse_timerange(timerange)
        tf_minutes = _timeframe_to_minutes(timeframe)
        
        # Calculate required range with warm-up
        warmup_delta = timedelta(minutes=tf_minutes * warmup_candles)
        required_start = start_date - warmup_delta
        required_end = end_date
        
        # Get data file path
        data_file = _get_data_file_path(pair, timeframe, user_data_dir)
        
        if not data_file.exists():
            return {
                "has_gaps": True,
                "missing_ranges": [(required_start, required_end)],
                "available_candles": 0,
                "required_candles": int((required_end - required_start).total_seconds() / 60 / tf_minutes),
                "earliest_available": None,
                "latest_available": None,
                "reason": "no_data_file",
            }
        
        # Load feather file using pandas (freqtrade's native storage format).
        # Schema: date (datetime64[ms, UTC]), open, high, low, close, volume
        try:
            import pandas as pd
            df = pd.read_feather(data_file)
        except Exception as read_exc:
            return {
                "has_gaps": True,
                "missing_ranges": [(required_start, required_end)],
                "available_candles": 0,
                "required_candles": int((required_end - required_start).total_seconds() / 60 / tf_minutes),
                "earliest_available": None,
                "latest_available": None,
                "reason": f"read_error: {read_exc}",
            }

        if df is None or df.empty:
            return {
                "has_gaps": True,
                "missing_ranges": [(required_start, required_end)],
                "available_candles": 0,
                "required_candles": int((required_end - required_start).total_seconds() / 60 / tf_minutes),
                "earliest_available": None,
                "latest_available": None,
                "reason": "empty_data_file",
            }

        # Normalise the date column to timezone-aware datetime64.
        # Freqtrade may write the column as:
        #   • datetime64[ms, UTC]  — current feather format (df["date"].dt works)
        #   • int64 ms since epoch — older list-of-lists derived feather files
        # We convert int64 to UTC datetime64 before calling .dt.to_pydatetime().
        if pd.api.types.is_integer_dtype(df["date"]):
            df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
        elif not hasattr(df["date"].dtype, "tz") or df["date"].dtype.tz is None:
            # Naive datetime64 — assume UTC
            df["date"] = df["date"].dt.tz_localize("UTC")

        # date column is now timezone-aware datetime; convert to Python datetimes
        dates = df["date"].dt.to_pydatetime()
        timestamps = sorted(dates)
        earliest = timestamps[0]
        latest = timestamps[-1]
        available_candles = len(timestamps)
        required_candles = int((required_end - required_start).total_seconds() / 60 / tf_minutes)
        
        # Check if required range is covered
        has_gaps = False
        missing_ranges = []

        # Check start coverage.
        # If the data starts after the warmup-adjusted required_start but at or before
        # the IS window start (start_date), the pair was simply not listed on the exchange
        # earlier — this is an exchange-bounded boundary, not a real data gap.
        if earliest > required_start:
            if earliest <= start_date:
                # Exchange-bounded: data begins at/before IS start; warmup is limited
                # but the pair is usable.
                pass
            else:
                has_gaps = True
                missing_ranges.append((required_start, earliest))

        # Check end coverage (allow 1-day slack for exchange trading-day boundaries)
        end_tolerance = timedelta(days=1)
        if latest < required_end - end_tolerance:
            has_gaps = True
            missing_ranges.append((latest, required_end))
        
        # Check for internal gaps (more than 2x timeframe interval)
        for i in range(len(timestamps) - 1):
            gap = timestamps[i + 1] - timestamps[i]
            expected_interval = timedelta(minutes=tf_minutes)
            if gap > expected_interval * 2:
                has_gaps = True
                missing_ranges.append((timestamps[i], timestamps[i + 1]))
                logger.debug(
                    "Data_Healer | %s: internal gap detected at %s: %s gap (expected %s)",
                    pair, timestamps[i], gap, expected_interval
                )
        
        return {
            "has_gaps": has_gaps,
            "missing_ranges": missing_ranges,
            "available_candles": available_candles,
            "required_candles": required_candles,
            "earliest_available": earliest,
            "latest_available": latest,
            "reason": "gaps_detected" if has_gaps else "complete",
        }
        
    except Exception as exc:
        logger.error("Data_Healer | failed to check data gaps for %s: %s", pair, exc)
        return {
            "has_gaps": True,
            "missing_ranges": [],
            "available_candles": 0,
            "required_candles": 0,
            "earliest_available": None,
            "latest_available": None,
            "reason": f"check_error: {exc}",
        }


def _is_only_start_boundary_gap(
    verify_check: dict[str, Any],
    start_date: datetime,
    end_date: datetime,
) -> bool:
    """Return True when the only gaps are at the start boundary (warmup region).

    A "start boundary gap" means the exchange simply doesn't have data going
    back as far as the warmup buffer requires.  The backtest period itself is
    intact, so the pair should be accepted with a warning rather than evicted.

    Conditions that must both hold:
      1. Every missing range ends at or before ``start_date`` — no gaps touch
         the actual backtest window.
      2. ``latest_available`` is at or after ``end_date`` — data covers the
         full backtest end.
    """
    if not verify_check.get("missing_ranges"):
        return False

    latest = verify_check.get("latest_available")
    if latest is None or latest < end_date:
        return False

    for gap_start, gap_end in verify_check["missing_ranges"]:
        if gap_end > start_date:
            return False

    return True


async def _download_pair_data(
    pair: str,
    timerange: str,
    timeframe: str,
    config_file: str,
    freqtrade_path: str,
    user_data_dir: str,
    run_id: str = "data_healer",
    timeout_seconds: int = 300,
    prepend: bool = False,
    erase: bool = False,
) -> dict[str, Any]:
    """Download historical data for a single pair using freqtrade download-data.
    
    Args:
        pair: Trading pair to download
        timerange: Timerange string (YYYYMMDD-YYYYMMDD)
        timeframe: Timeframe string
        config_file: Freqtrade config file path
        freqtrade_path: Path to freqtrade executable
        user_data_dir: Freqtrade user data directory
        timeout_seconds: Subprocess timeout
    
    Returns:
        dict with keys:
            - success: bool
            - exit_code: int
            - candles_downloaded: int
            - error: str or None
    """
    try:
        # Build download command
        cmd = [
            freqtrade_path, "download-data",
            "--config", config_file,
            "--timerange", timerange,
            "--timeframes", timeframe,
            "--pairs", pair,
            "--user-data-dir", user_data_dir,
            "--no-color",
        ]
        
        if prepend:
            cmd.append("--prepend")
        if erase:
            cmd.append("--erase")
        
        logger.info("Data_Healer | downloading data for %s: %s", pair, " ".join(cmd))
        
        # Run with timeout
        try:
            rc, stdout, stderr = await asyncio.wait_for(
                _run_subprocess(run_id, cmd, stage=0),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.error("Data_Healer | download timeout for %s after %s seconds", pair, timeout_seconds)
            return {
                "success": False,
                "exit_code": -1,
                "candles_downloaded": 0,
                "error": f"timeout after {timeout_seconds}s",
            }
        
        # Check result
        if rc != 0:
            error_msg = stderr or stdout or "unknown error"
            logger.error("Data_Healer | download failed for %s (rc=%d): %s", pair, rc, error_msg[-200:])
            return {
                "success": False,
                "exit_code": rc,
                "candles_downloaded": 0,
                "error": error_msg,
            }
        
        # Count downloaded candles by re-checking
        gap_check = _check_pair_data_gaps(pair, timerange, timeframe, user_data_dir, warmup_candles=0)
        candles_downloaded = gap_check["available_candles"]
        
        logger.info("Data_Healer | download successful for %s: %d candles", pair, candles_downloaded)
        
        return {
            "success": True,
            "exit_code": 0,
            "candles_downloaded": candles_downloaded,
            "error": None,
        }
        
    except Exception as exc:
        logger.error("Data_Healer | download exception for %s: %s", pair, exc)
        return {
            "success": False,
            "exit_code": -1,
            "candles_downloaded": 0,
            "error": str(exc),
        }


def _calculate_wfo_min_candles(
    wfo_is_months: int,
    wfo_oos_months: int,
    timeframe_minutes: int,
) -> int:
    """Calculate minimum candles required for Walk-Forward Analysis.
    
    Args:
        wfo_is_months: In-sample months per window
        wfo_oos_months: Out-of-sample months per window
        timeframe_minutes: Timeframe in minutes
    
    Returns:
        Minimum number of candles required
    """
    # Total months needed for one complete WFO window
    total_months = wfo_is_months + wfo_oos_months
    # Convert to candles (approximate: 30 days/month, 24 hours/day)
    min_candles = total_months * 30 * 24 * 60 // timeframe_minutes
    return min_candles


async def _stage_data_healing(
    run_id: str,
    state: PipelineState,
    out_dir: Path,
) -> dict[str, Any]:
    """Stage 0: Data Healing - validate and auto-download historical data.
    
    This stage checks all pairs in the pair_universe for data gaps,
    automatically downloads missing candles, and evicts pairs only when
    necessary (API errors or insufficient historical depth for WFO).
    
    Args:
        run_id: Pipeline run ID
        state: Pipeline state
        out_dir: Output directory for this run
    
    Returns:
        Summary dict with healing results
    """
    _rlog(run_id, 0, logging.INFO, "── STAGE 0: Data Healing ──")
    
    pairs_to_heal = state.pair_universe or []
    timerange = state.in_sample_range  # Use IS range for data validation
    timeframe = state.timeframe
    warmup_candles = getattr(state, "data_healing_warmup_candles", 200)
    timeout_seconds = getattr(state, "data_healing_timeout", 300)
    
    # Emit data_healing_start event
    _emit(
        run_id, 0, "running",
        f"Starting data validation for {len(pairs_to_heal)} pairs...",
        0,
        {
            "type": "data_healing_start",
            "pairs": pairs_to_heal,
            "timerange": timerange,
            "timeframe": timeframe,
            "warmup_candles": warmup_candles,
        }
    )
    
    _rlog(run_id, 0, logging.INFO,
          f"Data_Healer | validating {len(pairs_to_heal)} pairs for {timerange} @ {timeframe} "
          f"(warmup={warmup_candles} candles)")
    
    surviving_pairs = []
    evicted_pairs = []
    
    # Parse timerange once for use in gap boundary checks
    start_date, end_date = _parse_timerange(timerange)
    tf_minutes = _timeframe_to_minutes(timeframe)

    for pair in pairs_to_heal:
        if _cancelled(run_id):
            raise _Cancelled()
        
        # Check data gaps
        gap_check = _check_pair_data_gaps(
            pair, timerange, timeframe, state.user_data_dir, warmup_candles
        )
        
        candles_before = gap_check["available_candles"]
        
        if not gap_check["has_gaps"]:
            # Data is complete
            surviving_pairs.append(pair)
            _emit(
                run_id, 0, "running",
                f"✓ {pair}: data complete ({candles_before} candles)",
                0,
                {
                    "type": "data_pair_status",
                    "pair": pair,
                    "status": "healed",
                    "reason": "data_complete",
                    "candles_before": candles_before,
                    "candles_after": candles_before,
                }
            )
            _rlog(run_id, 0, logging.DEBUG,
                  f"Data_Healer | {pair}: data complete ({candles_before} candles)")
            continue
        
        # Check if gap is only at start boundary (warmup region) before attempting download
        if _is_only_start_boundary_gap(gap_check, start_date, end_date):
            # Gaps are only in the warmup region — exchange has no earlier data.
            # Skip download and accept with partial warmup.
            earliest = gap_check["earliest_available"]
            if earliest is not None and earliest < start_date:
                warmup_candles_available = int(
                    (start_date - earliest).total_seconds() / 60 / tf_minutes
                )
            else:
                warmup_candles_available = 0
            warmup_coverage = f"{warmup_candles_available}/{warmup_candles} candles"
            exchange_start_str = (
                earliest.strftime("%Y-%m-%d") if earliest is not None else "unknown"
            )
            surviving_pairs.append(pair)
            _emit(
                run_id, 0, "running",
                f"⚠ {pair}: accepted with partial warmup ({warmup_coverage} — exchange data begins {exchange_start_str})",
                0,
                {
                    "type": "data_pair_status",
                    "pair": pair,
                    "status": "healed_partial_warmup",
                    "reason": "start_boundary_gap_only",
                    "candles_before": candles_before,
                    "candles_after": gap_check["available_candles"],
                    "warmup_coverage": warmup_coverage,
                }
            )
            _rlog(run_id, 0, logging.WARNING,
                  f"Data_Healer | {pair}: accepted with partial warmup "
                  f"({warmup_coverage} — exchange data begins {exchange_start_str})")
            continue

        # Data has gaps - attempt download
        _emit(
            run_id, 0, "running",
            f"⬇ {pair}: downloading missing data...",
            0,
            {
                "type": "data_pair_status",
                "pair": pair,
                "status": "downloading",
                "reason": gap_check["reason"],
                "candles_before": candles_before,
                "candles_after": candles_before,
            }
        )
        _rlog(run_id, 0, logging.INFO,
              f"Data_Healer | {pair}: gaps detected ({gap_check['reason']}), downloading...")
        
        # Calculate extended timerange for download (include warm-up)
        warmup_delta = timedelta(minutes=tf_minutes * warmup_candles)
        download_start_dt = start_date - warmup_delta
        download_start = download_start_dt.strftime("%Y%m%d")
        download_end = end_date.strftime("%Y%m%d")
        download_timerange = f"{download_start}-{download_end}"
        
        # Determine if we need prepend, erase, or normal append
        needs_prepend = False
        needs_erase = False
        earliest = gap_check.get("earliest_available")
        latest = gap_check.get("latest_available")
        
        if earliest is not None and latest is not None:
            needs_prepend = earliest > download_start_dt
            needs_append = latest < end_date
            
            # Check for middle gaps
            middle_gaps = False
            for gap_start, gap_end in gap_check.get("missing_ranges", []):
                if gap_start > earliest and gap_end < latest:
                    middle_gaps = True
                    break
                    
            if middle_gaps or (needs_prepend and needs_append):
                needs_erase = True
        
        # Download data
        download_result = await _download_pair_data(
            pair,
            download_timerange,
            timeframe,
            state.config_file,
            state.freqtrade_path,
            state.user_data_dir,
            run_id,
            timeout_seconds,
            prepend=(needs_prepend and not needs_erase),
            erase=needs_erase,
        )
        
        candles_after = download_result["candles_downloaded"]
        
        if download_result["success"]:
            # Download successful - verify again
            verify_check = _check_pair_data_gaps(
                pair, timerange, timeframe, state.user_data_dir, warmup_candles
            )
            
            # Check WFO historical depth if enabled
            if state.wfo_enabled:
                tf_minutes = _timeframe_to_minutes(timeframe)
                min_candles = _calculate_wfo_min_candles(
                    state.wfo_is_months,
                    state.wfo_oos_months,
                    tf_minutes
                )
                
                if verify_check["available_candles"] < min_candles:
                    evicted_pairs.append((pair, "insufficient_history_for_wfo"))
                    _emit(
                        run_id, 0, "running",
                        f"✗ {pair}: evicted (insufficient history for WFO: {verify_check['available_candles']} < {min_candles})",
                        0,
                        {
                            "type": "data_pair_status",
                            "pair": pair,
                            "status": "evicted",
                            "reason": "insufficient_history_for_wfo",
                            "candles_before": candles_before,
                            "candles_after": verify_check["available_candles"],
                        }
                    )
                    _rlog(run_id, 0, logging.WARNING,
                          f"Data_Healer | {pair}: evicted (insufficient history for WFO)")
                    continue
            
            if not verify_check["has_gaps"]:
                surviving_pairs.append(pair)
                _emit(
                    run_id, 0, "running",
                    f"✓ {pair}: healed ({candles_before} → {verify_check['available_candles']} candles)",
                    0,
                    {
                        "type": "data_pair_status",
                        "pair": pair,
                        "status": "healed",
                        "reason": "download_successful",
                        "candles_before": candles_before,
                        "candles_after": verify_check["available_candles"],
                    }
                )
                _rlog(run_id, 0, logging.INFO,
                      f"Data_Healer | {pair}: healed ({candles_before} → {verify_check['available_candles']} candles)")
            elif _is_only_start_boundary_gap(verify_check, start_date, end_date):
                # Gaps are only in the warmup region — exchange has no earlier
                # data.  The backtest window itself is complete, so accept with
                # a warning instead of evicting.
                earliest = verify_check["earliest_available"]
                if earliest is not None and earliest < start_date:
                    warmup_candles_available = int(
                        (start_date - earliest).total_seconds() / 60 / tf_minutes
                    )
                else:
                    warmup_candles_available = 0
                warmup_coverage = f"{warmup_candles_available}/{warmup_candles} candles"
                exchange_start_str = (
                    earliest.strftime("%Y-%m-%d") if earliest is not None else "unknown"
                )
                surviving_pairs.append(pair)
                _emit(
                    run_id, 0, "running",
                    f"⚠ {pair}: accepted with partial warmup ({warmup_coverage} — exchange data begins {exchange_start_str})",
                    0,
                    {
                        "type": "data_pair_status",
                        "pair": pair,
                        "status": "healed_partial_warmup",
                        "reason": "start_boundary_gap_only",
                        "candles_before": candles_before,
                        "candles_after": verify_check["available_candles"],
                        "warmup_coverage": warmup_coverage,
                    }
                )
                _rlog(run_id, 0, logging.WARNING,
                      f"Data_Healer | {pair}: accepted with partial warmup "
                      f"({warmup_coverage} — exchange data begins {exchange_start_str})")
            else:
                # Still has genuine gaps after download - check data coverage
                coverage_ratio = verify_check["available_candles"] / verify_check["required_candles"] if verify_check["required_candles"] > 0 else 0
                if coverage_ratio >= 0.9:
                    # Accept pair with >90% coverage despite gaps
                    surviving_pairs.append(pair)
                    _emit(
                        run_id, 0, "running",
                        f"⚠ {pair}: accepted with gaps ({coverage_ratio:.1%} coverage - {verify_check['available_candles']}/{verify_check['required_candles']} candles)",
                        0,
                        {
                            "type": "data_pair_status",
                            "pair": pair,
                            "status": "healed_with_gaps",
                            "reason": "high_coverage_with_gaps",
                            "candles_before": candles_before,
                            "candles_after": verify_check["available_candles"],
                            "coverage_ratio": coverage_ratio,
                        }
                    )
                    _rlog(run_id, 0, logging.WARNING,
                          f"Data_Healer | {pair}: accepted with gaps ({coverage_ratio:.1%} coverage)")
                else:
                    # Evict pair with insufficient coverage
                    evicted_pairs.append((pair, "gaps_after_download"))
                    _emit(
                        run_id, 0, "running",
                        f"✗ {pair}: evicted (gaps persist after download, {coverage_ratio:.1%} coverage)",
                        0,
                        {
                            "type": "data_pair_status",
                            "pair": pair,
                            "status": "evicted",
                            "reason": "gaps_after_download",
                            "candles_before": candles_before,
                            "candles_after": verify_check["available_candles"],
                            "coverage_ratio": coverage_ratio,
                        }
                    )
                    _rlog(run_id, 0, logging.WARNING,
                          f"Data_Healer | {pair}: evicted (gaps persist after download, {coverage_ratio:.1%} coverage)")
        else:
            # Download failed - evict
            error_reason = download_result["error"] or "download_failed"
            evicted_pairs.append((pair, error_reason))
            _emit(
                run_id, 0, "running",
                f"✗ {pair}: evicted ({error_reason})",
                0,
                {
                    "type": "data_pair_status",
                    "pair": pair,
                    "status": "evicted",
                    "reason": error_reason,
                    "candles_before": candles_before,
                    "candles_after": candles_after,
                }
            )
            _rlog(run_id, 0, logging.WARNING,
                  f"Data_Healer | {pair}: evicted ({error_reason})")
    
    # Check if all pairs were evicted
    if not surviving_pairs:
        msg = f"Data_Healing FAILED: All {len(pairs_to_heal)} pairs were evicted. Check exchange connectivity or choose different pairs."
        _rlog(run_id, 0, logging.ERROR, msg)
        _emit(
            run_id, 0, "failed",
            msg,
            0,
            {
                "type": "data_healing_summary",
                "total_pairs": len(pairs_to_heal),
                "surviving_pairs": 0,
                "evicted_pairs": len(evicted_pairs),
                "surviving_pair_list": [],
            }
        )
        raise Exception(msg)
    
    # Update state with surviving pairs
    state.pair_universe = surviving_pairs
    
    # Emit summary
    summary = {
        "type": "data_healing_summary",
        "total_pairs": len(pairs_to_heal),
        "surviving_pairs": len(surviving_pairs),
        "evicted_pairs": len(evicted_pairs),
        "surviving_pair_list": surviving_pairs,
        "evicted_pair_details": [{"pair": p, "reason": r} for p, r in evicted_pairs],
    }
    
    _emit(
        run_id, 0, "running",
        f"Data healing complete: {len(surviving_pairs)}/{len(pairs_to_heal)} pairs passed",
        0,
        summary
    )
    
    _rlog(run_id, 0, logging.INFO,
          f"Data_Healer | COMPLETE: {len(surviving_pairs)}/{len(pairs_to_heal)} pairs survived, "
          f"{len(evicted_pairs)} evicted")
    
    return summary
