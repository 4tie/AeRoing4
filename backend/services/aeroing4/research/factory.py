"""Factory to assemble the Controlled Research Loop Coordinator (PROMPT 8 §9).

Assembles the existing stores + services into a ``ResearchLoopCoordinator``.
This is the ONLY place that knows the full dependency graph — the orchestrator
and API just call ``build_research_loop_coordinator``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...app_services import AppServices

from .access_guard import DataZoneGuard
from .candidate_artifacts import CandidateArtifactService
from .candidate_executor import CandidateExecutor
from .champions import ChampionStore
from .confirmation import ConfirmationService
from .experiments import ExperimentStore
from .focused_hyperopt import FocusedHyperoptService
from .hypotheses import HypothesisStore
from .loop_coordinator import ResearchLoopCoordinator
from .proposal_generator import ProposalGenerator
from .research_state import ResearchStateStore
from .sensitivity import SensitivityService


def build_research_loop_coordinator(
    services: "AppServices",
    runs_root: Path,
    *,
    develop_timerange: str = "20240101-20240630",
    pairs: list[str] | None = None,
    timeframe: str = "5m",
    min_sample_trades: int = 30,
) -> ResearchLoopCoordinator:
    """Build a fully-wired ResearchLoopCoordinator from AppServices.

    The ProposalGenerator uses the real Ollama adapter behind ``services``;
    callers may override ``proposal_callable`` for tests (the coordinator
    accepts a sync/async callable, not just a ProposalGenerator instance).
    """
    experiment_store = ExperimentStore(runs_root)
    experiment_store.budget_service = _budget_service(services, runs_root)
    hypothesis_store = HypothesisStore(runs_root)
    champion_store = ChampionStore(runs_root)
    state_store = ResearchStateStore(runs_root)
    artifact_service = CandidateArtifactService(runs_root)
    executor = CandidateExecutor(runs_root, services.backtest_runner)
    zone_guard = DataZoneGuard(state_store, runs_root)

    proposal_generator = ProposalGenerator(services)

    def diagnose_fn(champion):
        # Reuse the diagnosis for the current champion. The orchestrator feeds
        # the latest DiagnosisCode; here we default to NO_EDGE when diagnosis
        # metadata is absent (the loop still runs deterministically).
        from .diagnosis.models import DiagnosisCode

        return DiagnosisCode.NO_EDGE

    return ResearchLoopCoordinator(
        runs_root=runs_root,
        experiment_store=experiment_store,
        hypothesis_store=hypothesis_store,
        champion_store=champion_store,
        state_store=state_store,
        artifact_service=artifact_service,
        executor=executor,
        zone_guard=zone_guard,
        diagnose_fn=diagnose_fn,
        proposal_callable=proposal_generator.propose,
        develop_timerange=develop_timerange,
        pairs=pairs or ["BTC/USDT", "ETH/USDT", "BNB/USDT"],
        timeframe=timeframe,
        min_sample_trades=min_sample_trades,
    )


def build_focused_hyperopt_service(
    services: "AppServices",
    runs_root: Path,
    *,
    develop_timerange: str = "20240101-20240630",
    pairs: list[str] | None = None,
    timeframe: str = "5m",
    min_sample_trades: int = 30,
) -> FocusedHyperoptService:
    """Assemble a FocusedHyperoptService reusing the EXISTING BacktestRunner
    (no new subprocess/parser) and the same stores as the research loop."""
    champion_store = ChampionStore(runs_root)
    zone_guard = DataZoneGuard(ResearchStateStore(runs_root), runs_root)
    return FocusedHyperoptService(
        runs_root=runs_root,
        backtest_runner=services.backtest_runner,
        champion_store=champion_store,
        zone_guard=zone_guard,
        develop_timerange=develop_timerange,
        pairs=pairs or ["BTC/USDT", "ETH/USDT", "BNB/USDT"],
        timeframe=timeframe,
    )


def build_sensitivity_service(
    services: "AppServices",
    runs_root: Path,
    *,
    develop_timerange: str = "20240101-20240630",
    pairs: list[str] | None = None,
    timeframe: str = "5m",
) -> SensitivityService:
    """Assemble a SensitivityService reusing the EXISTING BacktestRunner."""
    zone_guard = DataZoneGuard(ResearchStateStore(runs_root), runs_root)
    return SensitivityService(
        runs_root=runs_root,
        backtest_runner=services.backtest_runner,
        zone_guard=zone_guard,
        develop_timerange=develop_timerange,
        pairs=pairs or ["BTC/USDT", "ETH/USDT", "BNB/USDT"],
        timeframe=timeframe,
    )


def build_confirmation_service(
    services: "AppServices",
    runs_root: Path,
    *,
    develop_timerange: str = "20240101-20240630",
    confirmation_timerange: str = "20240701-20240731",
    final_unseen_timerange: str = "20240801-20240831",
    pairs: list[str] | None = None,
    timeframe: str = "5m",
) -> ConfirmationService:
    """Assemble a ConfirmationService reusing the EXISTING BacktestRunner +
    DataZoneGuard (CONFIRMATION zone) + ChampionStore (read-only)."""
    zone_guard = DataZoneGuard(ResearchStateStore(runs_root), runs_root)
    return ConfirmationService(
        runs_root=runs_root,
        backtest_runner=services.backtest_runner,
        champion_store=ChampionStore(runs_root),
        zone_guard=zone_guard,
        develop_timerange=develop_timerange,
        confirmation_timerange=confirmation_timerange,
        final_unseen_timerange=final_unseen_timerange,
        pairs=pairs or ["BTC/USDT", "ETH/USDT", "BNB/USDT"],
        timeframe=timeframe,
    )


def build_final_unseen_service(
    services: "AppServices",
    runs_root: Path,
    *,
    develop_timerange: str = "20240101-20240630",
    confirmation_timerange: str = "20240701-20240731",
    final_unseen_timerange: str = "20240801-20240831",
    pairs: list[str] | None = None,
    timeframe: str = "5m",
) -> "FinalUnseenService":
    """Assemble a FinalUnseenService reusing the EXISTING BacktestRunner +
    DataZoneGuard (FINAL_UNSEEN zone) + ChampionStore (read-only)."""
    zone_guard = DataZoneGuard(ResearchStateStore(runs_root), runs_root)
    from .final_unseen import FinalUnseenService
    return FinalUnseenService(
        runs_root=runs_root,
        backtest_runner=services.backtest_runner,
        champion_store=ChampionStore(runs_root),
        zone_guard=zone_guard,
        develop_timerange=develop_timerange,
        confirmation_timerange=confirmation_timerange,
        final_unseen_timerange=final_unseen_timerange,
        pairs=pairs or ["BTC/USDT", "ETH/USDT", "BNB/USDT"],
        timeframe=timeframe,
    )


def build_delivery_service(
    services: "AppServices",
    runs_root: Path,
    *,
    export_profile: str = "run_local",
    force_overwrite: bool = False,
) -> "DeliveryService":
    """Assemble a DeliveryService (packaging only, safe-by-default run-local)."""
    from .delivery import DeliveryService
    return DeliveryService(
        runs_root=runs_root,
        champion_store=ChampionStore(runs_root),
        export_profile=export_profile,
        force_overwrite=force_overwrite,
    )


def build_research_loop_coordinator_legacy_note():
    # Reserved hook for future BudgetService wiring; intentionally inert.
    return None
