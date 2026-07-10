"""Execution tool endpoints for AI agent router."""

import asyncio

from fastapi import APIRouter, Request

from .helpers import _log_action
from .schemas import ToolExecutionRequest, ToolExecutionResponse


def register_execution_tool_endpoints(router: APIRouter) -> None:
    """Register execution tool endpoints on the given router."""
    
    @router.post(
        "/tools/run_pair_explorer",
        summary="Run Pair Explorer",
        description="Run Pair Explorer to test strategy across pair universe.",
    )
    async def run_pair_explorer(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """Run Pair Explorer to test strategy across pair universe."""
        try:
            strategy_name = body.parameters.get("strategy_name")
            timeframe = body.parameters.get("timeframe", "1h")
            timerange = body.parameters.get("timerange")
            pairs = body.parameters.get("pairs")
            
            if not all([strategy_name, timerange]):
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameters: strategy_name, timerange"
                )
            
            services = request.app.state.services
            settings = services.settings_store.load()
            
            # Import the pair explorer service
            from ...services.execution.pair_sweep_runner import PairSweepRunner
            from ...services.storage.pair_sweep_store import PairSweepStore
            
            # Use default pair universe if not provided
            if not pairs:
                # Use a default set of liquid pairs
                pairs = [
                    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
                    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOGE/USDT", "LTC/USDT",
                    "DOT/USDT", "TRX/USDT", "NEAR/USDT", "ATOM/USDT", "MATIC/USDT"
                ]
            
            # Create sweep runner
            sweep_runner = PairSweepRunner(
                freqtrade_path=settings.freqtrade_executable_path,
                user_data_dir=settings.user_data_directory_path,
                config_file=settings.default_config_file_path
            )
            
            # Create sweep store
            sweep_store = PairSweepStore(settings.user_data_directory_path)
            
            # Run the pair sweep
            sweep_id = sweep_store.create_sweep(
                strategy_name=strategy_name,
                pairs=pairs,
                timeframe=timeframe,
                timerange=timerange
            )
            
            # Run the sweep in background
            asyncio.create_task(_run_pair_sweep_background(
                sweep_runner, sweep_store, sweep_id, strategy_name, pairs, timeframe, timerange
            ))
            
            result = {
                "sweep_id": sweep_id,
                "strategy_name": strategy_name,
                "pairs_count": len(pairs),
                "timeframe": timeframe,
                "timerange": timerange,
                "status": "running"
            }
            
            _log_action(body.session_id, "run_pair_explorer", {
                "strategy_name": strategy_name,
                "sweep_id": sweep_id,
                "pairs_count": len(pairs)
            }, request)
            
            return ToolExecutionResponse(
                success=True,
                result=result,
                logs=[
                    {"message": f"Started Pair Explorer for {len(pairs)} pairs"},
                    {"message": f"Sweep ID: {sweep_id}"},
                    {"message": "Use GET /api/strategy/pair-explorer/{sweep_id} to check progress"}
                ],
                next_actions=[
                    f"Wait for Pair Explorer to complete (sweep_id: {sweep_id})",
                    "Check results using GET /api/strategy/pair-explorer/{sweep_id}",
                    "Select top 3-4 pairs based on metrics"
                ]
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to run Pair Explorer: {str(e)}"
            )

    @router.post(
        "/tools/run_backtest",
        summary="Run backtest",
        description="Run a backtest for a strategy with specified parameters.",
    )
    async def run_backtest(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """Run a backtest for a strategy with specified parameters."""
        try:
            strategy_name = body.parameters.get("strategy_name")
            timeframe = body.parameters.get("timeframe", "5m")
            timerange = body.parameters.get("timerange")
            pairs = body.parameters.get("pairs")
            max_open_trades = body.parameters.get("max_open_trades", 1)
            fee_rate = body.parameters.get("fee_rate", 0.001)
            
            if not all([strategy_name, timerange]):
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameters: strategy_name, timerange"
                )
            
            if not pairs:
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameter: pairs (list of pairs to backtest)"
                )
            
            services = request.app.state.services
            settings = services.settings_store.load()
            session_store = request.app.state.session_store
            
            # Import backtest runner
            from ...services.execution.backtest_runner import BacktestRunner
            from ...models import RunRequest
            
            # Create run request
            run_request = RunRequest(
                strategy_name=strategy_name,
                timeframe=timeframe,
                timerange=timerange,
                pairs=pairs,
                max_open_trades=max_open_trades,
                fee_rate=fee_rate
            )
            
            # Create session
            session_id = session_store.create_session(run_request)
            
            # Create backtest runner
            backtest_runner = BacktestRunner(
                freqtrade_path=settings.freqtrade_executable_path,
                user_data_dir=settings.user_data_directory_path,
                config_file=settings.default_config_file_path
            )
            
            # Run backtest in background
            asyncio.create_task(_run_backtest_background(
                backtest_runner, session_store, session_id, run_request
            ))
            
            result = {
                "session_id": session_id,
                "strategy_name": strategy_name,
                "pairs": pairs,
                "timeframe": timeframe,
                "timerange": timerange,
                "max_open_trades": max_open_trades,
                "status": "running"
            }
            
            _log_action(body.session_id, "run_backtest", {
                "strategy_name": strategy_name,
                "session_id": session_id,
                "pairs_count": len(pairs)
            }, request)
            
            return ToolExecutionResponse(
                success=True,
                result=result,
                logs=[
                    {"message": f"Started backtest for {len(pairs)} pairs"},
                    {"message": f"Session ID: {session_id}"},
                    {"message": "Use GET /api/session/status/{session_id} to check progress"}
                ],
                next_actions=[
                    f"Wait for backtest to complete (session_id: {session_id})",
                    "Check results using GET /api/session/status/{session_id}",
                    "Analyze metrics to determine if strategy passes"
                ]
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to run backtest: {str(e)}"
            )

    @router.post(
        "/tools/run_optimizer",
        summary="Run optimizer",
        description="Run the optimizer to find optimal parameters.",
    )
    async def run_optimizer(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """Run the optimizer to find optimal parameters."""
        try:
            strategy_name = body.parameters.get("strategy_name")
            timeframe = body.parameters.get("timeframe", "5m")
            timerange = body.parameters.get("timerange")
            pairs = body.parameters.get("pairs")
            spaces = body.parameters.get("spaces")
            epochs = body.parameters.get("epochs", 100)
            
            if not all([strategy_name, timerange, spaces]):
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameters: strategy_name, timerange, spaces"
                )
            
            if not pairs:
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameter: pairs (list of pairs to optimize)"
                )
            
            services = request.app.state.services
            settings = services.settings_store.load()
            session_store = request.app.state.session_store
            
            # Import optimizer runner
            from ...services.execution.optimizer_runner import OptimizerRunner
            from ...models import RunRequest
            
            # Create run request for optimizer
            run_request = RunRequest(
                strategy_name=strategy_name,
                timeframe=timeframe,
                timerange=timerange,
                pairs=pairs,
                max_open_trades=len(pairs)
            )
            
            # Create session
            session_id = session_store.create_session(run_request)
            
            # Create optimizer runner
            optimizer_runner = OptimizerRunner(
                freqtrade_path=settings.freqtrade_executable_path,
                user_data_dir=settings.user_data_directory_path,
                config_file=settings.default_config_file_path
            )
            
            # Run optimizer in background
            asyncio.create_task(_run_optimizer_background(
                optimizer_runner, session_store, session_id, run_request, spaces, epochs
            ))
            
            result = {
                "session_id": session_id,
                "strategy_name": strategy_name,
                "pairs": pairs,
                "spaces": spaces,
                "epochs": epochs,
                "timeframe": timeframe,
                "timerange": timerange,
                "status": "running"
            }
            
            _log_action(body.session_id, "run_optimizer", {
                "strategy_name": strategy_name,
                "session_id": session_id,
                "spaces": spaces,
                "epochs": epochs
            }, request)
            
            return ToolExecutionResponse(
                success=True,
                result=result,
                logs=[
                    {"message": f"Started optimizer for {len(pairs)} pairs"},
                    {"message": f"Spaces: {', '.join(spaces)}"},
                    {"message": f"Epochs: {epochs}"},
                    {"message": f"Session ID: {session_id}"},
                    {"message": "Use GET /api/session/status/{session_id} to check progress"}
                ],
                next_actions=[
                    f"Wait for optimizer to complete (session_id: {session_id})",
                    "Check results using GET /api/session/status/{session_id}",
                    "Review optimized parameters and decide whether to accept them"
                ]
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to run optimizer: {str(e)}"
            )

    @router.post(
        "/tools/run_stress_test",
        summary="Run stress test",
        description="Run Stress Test Lab including Time Split and Monte Carlo.",
    )
    async def run_stress_test(body: ToolExecutionRequest, request: Request) -> ToolExecutionResponse:
        """Run Stress Test Lab including Time Split and Monte Carlo."""
        try:
            strategy_name = body.parameters.get("strategy_name")
            timeframe = body.parameters.get("timeframe", "5m")
            timerange = body.parameters.get("timerange")
            pairs = body.parameters.get("pairs")
            tests = body.parameters.get("tests")
            
            if not all([strategy_name, timerange]):
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameters: strategy_name, timerange"
                )
            
            if not pairs:
                return ToolExecutionResponse(
                    success=False,
                    error="Missing required parameter: pairs (list of pairs to stress test)"
                )
            
            services = request.app.state.services
            settings = services.settings_store.load()
            session_store = request.app.state.session_store
            
            # Default to all available tests if not specified
            if not tests:
                tests = ["time_split", "monte_carlo", "robustness"]
            
            # Import stress test runner
            from ...services.execution.temporal_stress_runner import TemporalStressRunner
            from ...models import RunRequest
            
            # Create run request for stress test
            run_request = RunRequest(
                strategy_name=strategy_name,
                timeframe=timeframe,
                timerange=timerange,
                pairs=pairs,
                max_open_trades=len(pairs)
            )
            
            # Create session
            session_id = session_store.create_session(run_request)
            
            # Create stress test runner
            stress_runner = TemporalStressRunner(
                freqtrade_path=settings.freqtrade_executable_path,
                user_data_dir=settings.user_data_directory_path,
                config_file=settings.default_config_file_path
            )
            
            # Run stress test in background
            asyncio.create_task(_run_stress_test_background(
                stress_runner, session_store, session_id, run_request, tests
            ))
            
            result = {
                "session_id": session_id,
                "strategy_name": strategy_name,
                "pairs": pairs,
                "tests": tests,
                "timeframe": timeframe,
                "timerange": timerange,
                "status": "running"
            }
            
            _log_action(body.session_id, "run_stress_test", {
                "strategy_name": strategy_name,
                "session_id": session_id,
                "tests": tests
            }, request)
            
            return ToolExecutionResponse(
                success=True,
                result=result,
                logs=[
                    {"message": f"Started stress test for {len(pairs)} pairs"},
                    {"message": f"Tests: {', '.join(tests)}"},
                    {"message": f"Session ID: {session_id}"},
                    {"message": "Use GET /api/session/status/{session_id} to check progress"}
                ],
                next_actions=[
                    f"Wait for stress test to complete (session_id: {session_id})",
                    "Check results using GET /api/session/status/{session_id}",
                    "Review stress test results to ensure strategy passes all validation checks"
                ]
            )
            
        except Exception as e:
            return ToolExecutionResponse(
                success=False,
                error=f"Failed to run stress test: {str(e)}"
            )


async def _run_pair_sweep_background(
    sweep_runner, sweep_store, sweep_id, strategy_name, pairs, timeframe, timerange
):
    """Run pair sweep in background task."""
    try:
        await sweep_runner.run_sweep(
            sweep_id=sweep_id,
            strategy_name=strategy_name,
            pairs=pairs,
            timeframe=timeframe,
            timerange=timerange
        )
    except Exception as e:
        # Update sweep status to failed
        try:
            sweep_store.update_sweep_status(sweep_id, "failed", str(e))
        except Exception:
            pass


async def _run_backtest_background(backtest_runner, session_store, session_id, run_request):
    """Run backtest in background task."""
    try:
        await backtest_runner.run_backtest(session_id, run_request)
    except Exception as e:
        # Update session status to failed
        try:
            session_store.update_status(session_id, "failed", str(e))
        except Exception:
            pass


async def _run_optimizer_background(optimizer_runner, session_store, session_id, run_request, spaces, epochs):
    """Run optimizer in background task."""
    try:
        await optimizer_runner.run_optimizer(
            session_id=session_id,
            run_request=run_request,
            spaces=spaces,
            epochs=epochs
        )
    except Exception as e:
        # Update session status to failed
        try:
            session_store.update_status(session_id, "failed", str(e))
        except Exception:
            pass


async def _run_stress_test_background(stress_runner, session_store, session_id, run_request, tests):
    """Run stress test in background task."""
    try:
        await stress_runner.run_stress_test(
            session_id=session_id,
            run_request=run_request,
            tests=tests
        )
    except Exception as e:
        # Update session status to failed
        try:
            session_store.update_status(session_id, "failed", str(e))
        except Exception:
            pass
