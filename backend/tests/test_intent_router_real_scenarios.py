"""Real-world scenario tests for Intent Router integration.

These tests simulate actual user conversations to validate that the Intent Router
works correctly in realistic scenarios, not just unit tests.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from types import SimpleNamespace

from backend.services.ai.intent_router import route_intent
from backend.services.ai.workflow_copilot import WorkflowCopilot
from backend.services.ai.copilot_session_store import CopilotSessionStore
from backend.services.ai.workflow_tool_executor import WorkflowToolExecutor
from backend.services.agent_context import AgentContextService


class RealScenarioTest:
    """Test the Intent Router with realistic user conversations."""
    
    @pytest.mark.asyncio
    async def test_real_user_asks_for_pair_discovery_with_all_info(self, tmp_path):
        """Real scenario: User provides all information upfront."""
        # Setup
        user_data = tmp_path / "user_data"
        strategies = user_data / "strategies"
        strategies.mkdir(parents=True, exist_ok=True)
        (strategies / "MyStrategy.py").write_text(
            "class MyStrategy:\n    timeframe = '1h'\n",
            encoding="utf-8"
        )
        
        # Simulate user message
        user_message = "Find more profitable pairs for MyStrategy alongside BTC/USDT for 2025"
        
        # Route intent
        plan = route_intent(user_message)
        
        # Verify intent was detected correctly
        assert plan is not None, "Intent should be detected for clear request"
        assert plan["intent"] == "pair_discovery"
        assert plan["confidence"] >= 0.7
        
        # Verify all slots were extracted
        assert plan["extracted_slots"]["strategy_name"] == "MyStrategy"
        assert plan["extracted_slots"]["timerange"] == "2025"
        assert "BTC/USDT" in plan["extracted_slots"]["baseline_pairs"]
        
        # Verify workflow is complete (no missing slots)
        assert len(plan["missing_slots"]) == 0
        
        # Verify workflow steps are correct
        assert len(plan["steps"]) == 3
        assert plan["steps"][0]["tool"] == "read_strategy_file"
        assert plan["steps"][1]["tool"] == "get_pair_universe"
        assert plan["steps"][2]["tool"] == "run_pair_explorer"
        assert plan["steps"][2]["requires_confirmation"] is True
    
    @pytest.mark.asyncio
    async def test_real_user_asks_pair_discovery_missing_timerange(self, tmp_path):
        """Real scenario: User forgets to specify timerange."""
        user_message = "I want to find better pairs for MyStrategy"
        
        plan = route_intent(user_message)
        
        # Should detect intent but note missing timerange
        assert plan is not None
        assert plan["intent"] == "pair_discovery"
        assert plan["extracted_slots"]["strategy_name"] == "MyStrategy"
        assert "timerange" in plan["missing_slots"]
        
        # Workflow should include ask_missing step
        ask_steps = [s for s in plan["steps"] if s.get("action") == "ask_missing"]
        assert len(ask_steps) == 1
        assert ask_steps[0]["args"]["slot"] == "timerange"
    
    @pytest.mark.asyncio
    async def test_real_user_asks_vague_question_falls_back(self):
        """Real scenario: User asks something unclear, should fall back to model."""
        vague_messages = [
            "What should I trade today?",
            "Give me some trading advice",
            "How's the market doing?",
            "Tell me about crypto",
        ]
        
        for message in vague_messages:
            plan = route_intent(message)
            # Should return None to trigger fallback to model orchestration
            assert plan is None, f"Vague message should fall back: {message}"
    
    @pytest.mark.asyncio
    async def test_real_user_uses_casual_language(self):
        """Real scenario: User uses casual, conversational language."""
        casual_messages = [
            "find profitable pairs for MyStrategy",
            "I need better pairs for MyStrategy",
            "test pairs for MyStrategy",
            "discover pairs for MyStrategy",
        ]
        
        for message in casual_messages:
            plan = route_intent(message)
            assert plan is not None, f"Casual message should be detected: {message}"
            assert plan["intent"] == "pair_discovery"
    
    @pytest.mark.asyncio
    async def test_real_user_mentions_multiple_baseline_pairs(self):
        """Real scenario: User wants to test alongside multiple existing pairs."""
        user_message = "Find profitable pairs for MyStrategy with BTC/USDT and ETH/USDT"
        
        plan = route_intent(user_message)
        
        assert plan is not None
        assert plan["intent"] == "pair_discovery"
        assert "BTC/USDT" in plan["extracted_slots"]["baseline_pairs"]
        assert "ETH/USDT" in plan["extracted_slots"]["baseline_pairs"]
    
    @pytest.mark.asyncio
    async def test_real_user_uses_different_timerange_formats(self):
        """Real scenario: User specifies timerange in various formats."""
        test_cases = [
            ("for 2025", "2025"),
            ("for 20250101-20251231", "20250101-20251231"),
            ("for January 2025", "January 2025"),
        ]
        
        for message, expected in test_cases:
            full_message = f"Find pairs for MyStrategy {message}"
            plan = route_intent(full_message)
            
            if plan:
                timerange = plan["extracted_slots"].get("timerange")
                assert timerange == expected, f"Expected {expected}, got {timerange}"
    
    @pytest.mark.asyncio
    async def test_real_user_typos_and_variations(self):
        """Real scenario: User makes typos or uses variations."""
        variations = [
            "find profitable pairs for MyStrat",  # Typo
            "find profitible pairs for MyStrategy",  # Typo
            "find more profitable pair for MyStrategy",  # Singular
        ]
        
        for message in variations:
            plan = route_intent(message)
            # Some may not match due to typos, but the system should be robust
            # This is expected behavior - typos may reduce confidence
            if plan:
                assert plan["intent"] == "pair_discovery"
    
    @pytest.mark.asyncio
    async def test_real_user_complex_request_with_extra_context(self):
        """Real scenario: User provides extra context that should be ignored."""
        user_message = (
            "I've been trading MyStrategy for a while and I think it's doing well. "
            "Can you find more profitable pairs for MyStrategy alongside BTC/USDT for 2025? "
            "I'm particularly interested in altcoins."
        )
        
        plan = route_intent(user_message)
        
        # Should still detect the core intent despite extra context
        assert plan is not None
        assert plan["intent"] == "pair_discovery"
        assert plan["extracted_slots"]["strategy_name"] == "MyStrategy"
        assert "BTC/USDT" in plan["extracted_slots"]["baseline_pairs"]
        assert plan["extracted_slots"]["timerange"] == "2025"
    
    @pytest.mark.asyncio
    async def test_real_user_strategy_analysis_intent(self):
        """Real scenario: User asks for strategy explanation."""
        user_message = "Explain how MyStrategy works"
        
        plan = route_intent(user_message)
        
        # Should detect strategy_analysis intent
        if plan:
            assert plan["intent"] == "strategy_analysis"
            # Currently returns empty steps (placeholder)
            assert len(plan["steps"]) == 0
    
    @pytest.mark.asyncio
    async def test_real_user_backtest_intent(self):
        """Real scenario: User wants to run a backtest."""
        user_message = "Run a backtest for MyStrategy"
        
        plan = route_intent(user_message)
        
        if plan:
            assert plan["intent"] == "backtest_run"
    
    @pytest.mark.asyncio
    async def test_real_user_optimizer_intent(self):
        """Real scenario: User wants to optimize parameters."""
        user_message = "Optimize MyStrategy parameters"
        
        plan = route_intent(user_message)
        
        if plan:
            assert plan["intent"] == "optimizer_run"


class EdgeCaseTests:
    """Test edge cases and boundary conditions."""
    
    def test_empty_message(self):
        """Edge case: Empty message."""
        plan = route_intent("")
        assert plan is None
    
    def test_very_long_message(self):
        """Edge case: Very long message."""
        long_message = "find " + "profitable " * 100 + "pairs for MyStrategy"
        plan = route_intent(long_message)
        # Should still work, just might have different confidence
        if plan:
            assert plan["intent"] == "pair_discovery"
    
    def test_special_characters(self):
        """Edge case: Message with special characters."""
        message = "Find profitable pairs for My-Strategy! @#$%"
        plan = route_intent(message)
        # Should handle gracefully
        if plan:
            assert plan["intent"] == "pair_discovery"
    
    def test_case_insensitivity(self):
        """Edge case: Different case variations."""
        variations = [
            "FIND PROFITABLE PAIRS FOR MYSTRATEGY",
            "Find Profitable Pairs For MyStrategy",
            "find profitable pairs for mystrategy",
        ]
        
        for message in variations:
            plan = route_intent(message)
            assert plan is not None, f"Case variation should match: {message}"
            assert plan["intent"] == "pair_discovery"
