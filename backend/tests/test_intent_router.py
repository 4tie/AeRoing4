"""Tests for the deterministic Intent Router."""

import pytest
from backend.services.ai.intent_router import (
    route_intent,
    extract_strategy_name,
    extract_timerange,
    extract_baseline_pairs,
    calculate_confidence,
    list_intents,
    get_intent_spec,
)


class TestSlotExtraction:
    """Test slot extraction functions."""
    
    def test_extract_strategy_name_with_py_extension(self):
        message = "Find more profitable pairs for AIStrategy.py"
        result = extract_strategy_name(message)
        assert result == "AIStrategy"
    
    def test_extract_strategy_name_without_extension(self):
        message = "Find more profitable pairs for MyStrategy"
        result = extract_strategy_name(message)
        assert result == "MyStrategy"
    
    def test_extract_strategy_name_with_strategy_keyword(self):
        message = "Test strategy MyStrategy"
        result = extract_strategy_name(message)
        assert result == "MyStrategy"
    
    def test_extract_strategy_name_not_found(self):
        message = "Find more profitable pairs"
        result = extract_strategy_name(message)
        assert result is None
    
    def test_extract_timerange_year(self):
        message = "for 2025"
        result = extract_timerange(message)
        assert result == "2025"
    
    def test_extract_timerange_full_range(self):
        message = "for 20250101-20251231"
        result = extract_timerange(message)
        assert result == "20250101-20251231"
    
    def test_extract_timerange_not_found(self):
        message = "Find profitable pairs"
        result = extract_timerange(message)
        assert result is None
    
    def test_extract_baseline_pairs_single(self):
        message = "alongside JTO/USDT"
        result = extract_baseline_pairs(message)
        assert result == ["JTO/USDT"]
    
    def test_extract_baseline_pairs_multiple(self):
        message = "with BTC/USDT and ETH/USDT"
        result = extract_baseline_pairs(message)
        assert "BTC/USDT" in result
        assert "ETH/USDT" in result
    
    def test_extract_baseline_pairs_case_insensitive(self):
        message = "alongside jto/usdt"
        result = extract_baseline_pairs(message)
        assert result == ["JTO/USDT"]


class TestConfidenceCalculation:
    """Test confidence scoring for intent detection."""
    
    def test_confidence_no_match(self):
        message = "Hello, how are you?"
        patterns = [r'find\s+profitable\s+pairs', r'better\s+pairs']
        result = calculate_confidence(message, patterns)
        assert result == 0.0
    
    def test_confidence_exact_match(self):
        message = "find profitable pairs"
        patterns = [r'find\s+profitable\s+pairs']
        result = calculate_confidence(message, patterns)
        assert result > 0.5
    
    def test_confidence_partial_match(self):
        message = "find more profitable pairs for strategy"
        patterns = [r'find\s+(more\s+)?profitable\s+pairs']
        result = calculate_confidence(message, patterns)
        assert result > 0.5
    
    def test_confidence_multiple_patterns(self):
        message = "find profitable pairs and better pairs"
        patterns = [r'find\s+profitable\s+pairs', r'better\s+pairs']
        result = calculate_confidence(message, patterns)
        assert result > 0.5


class TestPairDiscoveryIntent:
    """Test pair_discovery intent detection and workflow generation."""
    
    def test_pair_discovery_detected_with_strategy(self):
        message = "Find more profitable pairs for AIStrategy.py alongside JTO/USDT for 2025"
        plan = route_intent(message)
        
        assert plan is not None
        assert plan["intent"] == "pair_discovery"
        assert plan["confidence"] > 0.7
        assert plan["extracted_slots"]["strategy_name"] == "AIStrategy"
        assert plan["extracted_slots"]["timerange"] == "2025"
        assert "JTO/USDT" in plan["extracted_slots"]["baseline_pairs"]
    
    def test_pair_discovery_without_timerange(self):
        message = "Find profitable pairs for MyStrategy"
        plan = route_intent(message)
        
        assert plan is not None
        assert plan["intent"] == "pair_discovery"
        assert plan["extracted_slots"]["strategy_name"] == "MyStrategy"
        assert "timerange" in plan["missing_slots"]
    
    def test_pair_discovery_without_strategy(self):
        message = "Find profitable pairs"
        plan = route_intent(message)
        
        # Should not trigger without strategy name
        assert plan is None or plan["extracted_slots"].get("strategy_name") is None
    
    def test_pair_discovery_workflow_steps_with_timerange(self):
        message = "Find more profitable pairs for AIStrategy.py for 2025"
        plan = route_intent(message)
        
        assert plan is not None
        assert len(plan["steps"]) == 3  # read_strategy, get_universe, run_explorer
        
        # Check first step is read_strategy_file
        assert plan["steps"][0]["tool"] == "read_strategy_file"
        assert plan["steps"][0]["args"]["strategy_name"] == "AIStrategy"
        
        # Check second step is get_pair_universe
        assert plan["steps"][1]["tool"] == "get_pair_universe"
        
        # Check third step is run_pair_explorer with confirmation
        assert plan["steps"][2]["tool"] == "run_pair_explorer"
        assert plan["steps"][2]["requires_confirmation"] is True
    
    def test_pair_discovery_workflow_steps_without_timerange(self):
        message = "Find profitable pairs for MyStrategy"
        plan = route_intent(message)
        
        assert plan is not None
        assert len(plan["steps"]) == 3  # read_strategy, get_universe, ask_missing
        
        # Check last step is ask_missing action
        assert plan["steps"][2]["action"] == "ask_missing"
        assert plan["steps"][2]["args"]["slot"] == "timerange"


class TestIntentRegistry:
    """Test intent registry management."""
    
    def test_list_intents(self):
        intents = list_intents()
        assert isinstance(intents, list)
        assert "pair_discovery" in intents
        assert "strategy_analysis" in intents
        assert "backtest_run" in intents
        assert "optimizer_run" in intents
    
    def test_get_intent_spec(self):
        spec = get_intent_spec("pair_discovery")
        assert spec is not None
        assert spec.name == "pair_discovery"
        assert len(spec.patterns) > 0
        assert spec.required_slots == ["strategy_name"]
    
    def test_get_intent_spec_not_found(self):
        spec = get_intent_spec("nonexistent_intent")
        assert spec is None


class TestFallbackBehavior:
    """Test fallback to model orchestration for unclear intents."""
    
    def test_unclear_message_falls_back(self):
        message = "What is the weather today?"
        plan = route_intent(message)
        
        # Should return None to trigger fallback
        assert plan is None
    
    def test_low_confidence_falls_back(self):
        message = "I like trading"
        plan = route_intent(message)
        
        # Should return None due to low confidence
        assert plan is None
    
    def test_strategy_analysis_placeholder(self):
        message = "Explain strategy MyStrategy"
        plan = route_intent(message)
        
        # Should detect intent but return empty steps (placeholder)
        if plan:
            assert plan["intent"] == "strategy_analysis"
            assert len(plan["steps"]) == 0


class TestRealScenario:
    """Test the exact scenario from the requirements."""
    
    def test_real_pair_discovery_scenario(self):
        """Test: 'Find more profitable pairs for AIStrategy.py alongside JTO/USDT for 2025.'"""
        message = "Find more profitable pairs for AIStrategy.py alongside JTO/USDT for 2025"
        plan = route_intent(message)
        
        # Verify intent detection
        assert plan is not None, "Intent should be detected"
        assert plan["intent"] == "pair_discovery"
        assert plan["confidence"] >= 0.7, "Confidence should meet threshold"
        
        # Verify slot extraction
        assert plan["extracted_slots"]["strategy_name"] == "AIStrategy"
        assert plan["extracted_slots"]["timerange"] == "2025"
        assert "JTO/USDT" in plan["extracted_slots"]["baseline_pairs"]
        
        # Verify workflow structure
        assert len(plan["steps"]) == 3, "Should have 3 workflow steps"
        
        # Step 1: Read strategy
        assert plan["steps"][0]["tool"] == "read_strategy_file"
        assert plan["steps"][0]["args"]["strategy_name"] == "AIStrategy"
        assert plan["steps"][0]["requires_confirmation"] is False
        
        # Step 2: Get pair universe
        assert plan["steps"][1]["tool"] == "get_pair_universe"
        assert plan["steps"][1]["args"]["quote_currency"] == "USDT"
        assert plan["steps"][1]["requires_confirmation"] is False
        
        # Step 3: Propose pair explorer
        assert plan["steps"][2]["tool"] == "run_pair_explorer"
        assert plan["steps"][2]["args"]["strategy_name"] == "AIStrategy"
        assert plan["steps"][2]["args"]["timerange"] == "2025"
        assert "JTO/USDT" in plan["steps"][2]["args"]["pairs"]
        assert plan["steps"][2]["requires_confirmation"] is True
        
        # Verify no missing slots (all provided)
        assert len(plan["missing_slots"]) == 0
