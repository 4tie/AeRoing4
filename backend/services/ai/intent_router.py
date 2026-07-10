"""Deterministic Intent Router for AI workflow orchestration.

This module provides rule-based intent detection and controlled workflow execution
for known user intents, sitting in front of WorkflowCopilot as a preprocessing step.

Architecture Overview:
----------------------
The Intent Router is a lightweight, deterministic layer that:
1. Detects user intents using regex pattern matching
2. Extracts required parameters (slots) from natural language
3. Generates structured workflow plans for known intents
4. Falls back to model-based orchestration for unclear requests

Key Design Principles:
---------------------
- **Deterministic**: Rule-based pattern matching, no model inference for routing
- **Minimal**: Small footprint, easy to understand and extend
- **Non-blocking**: Falls back gracefully when intent is unclear
- **Separation of concerns**: Router handles orchestration, model handles explanation

Integration Point:
------------------
The router is integrated into WorkflowCopilot.process_turn() as a preprocessing step:
1. User message arrives
2. route_intent() attempts to detect intent
3. If confident: execute deterministic workflow plan
4. If unclear: fall back to existing model-based orchestration

Extensibility:
--------------
To add a new intent:
1. Define patterns in _INTENT_REGISTRY
2. Create a handler function that returns a WorkflowPlan
3. Add slot extraction helpers if needed
4. Register in _INTENT_REGISTRY with confidence threshold

Example:
    "my_new_intent": IntentSpec(
        name="my_new_intent",
        patterns=[r'pattern1', r'pattern2'],
        required_slots=["param1", "param2"],
        confidence_threshold=0.7,
        handler=handle_my_new_intent,
    )

The router handles orchestration (which tools to call in which order) while
the model remains responsible for explanations, analysis, and conversation.
"""

from __future__ import annotations

import re
import logging
from typing import Any, Callable, Dict, List, Optional, TypedDict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── Intent Specification ────────────────────────────────────────────────────────


@dataclass
class IntentSpec:
    """Specification for a single intent."""
    name: str
    patterns: List[str]  # Regex patterns for detection
    required_slots: List[str]  # Required parameters (e.g., strategy_name, timerange)
    confidence_threshold: float = 0.7  # Minimum confidence to trigger
    handler: Callable[[str, Dict[str, Any]], Dict[str, Any]] | None = None


class WorkflowStep(TypedDict):
    """Single step in a workflow plan."""
    tool: Optional[str]  # Tool name if this is a tool call
    action: Optional[str]  # Action type if this is a meta-action
    args: Dict[str, Any]  # Arguments for tool or action
    requires_confirmation: Optional[bool]  # Whether this step needs user confirmation


class WorkflowPlan(TypedDict):
    """Structured workflow plan for an intent."""
    intent: str
    steps: List[WorkflowStep]
    missing_slots: List[str]
    extracted_slots: Dict[str, Any]
    confidence: float


# ── Slot Extraction Helpers ─────────────────────────────────────────────────────


def extract_strategy_name(message: str) -> Optional[str]:
    """Extract strategy name from user message.
    
    Matches patterns like:
    - "for AIStrategy.py"
    - "for AIStrategy"
    - "strategy MyStrategy"
    - "test MyStrategy"
    
    Prioritizes more specific patterns (with .py or "for" keyword).
    """
    patterns = [
        r'for\s+(\w+\.py)',  # "for AIStrategy.py" - highest priority
        r'for\s+([A-Z]\w+)',  # "for AIStrategy" - capital letter indicates proper noun
        r'strategy\s+(\w+)',  # "strategy MyStrategy"
        r'test\s+(\w+)',  # "test MyStrategy"
        r'(\w+\.py)',  # "AIStrategy.py"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1)
            # Remove .py extension if present
            if name.endswith('.py'):
                name = name[:-3]
            # Filter out common words that aren't strategy names
            common_words = {'a', 'the', 'for', 'with', 'and', 'or', 'but', 'in', 'on', 'at', 'to'}
            if name.lower() in common_words:
                continue
            return name
    
    return None


def extract_timerange(message: str) -> Optional[str]:
    """Extract timerange from user message.
    
    Matches patterns like:
    - "for 2025"
    - "for 20250101-20251231"
    - "last 6 months"
    - "from January to March"
    """
    patterns = [
        r'for\s+(\d{4})\b',  # "for 2025" - word boundary to avoid partial matches
        r'for\s+(\d{8}-\d{8})',  # "for 20250101-20251231"
        r'for\s+(\w+\s+\d{4})',  # "for January 2025"
        r'last\s+(\d+)\s+(month|months|year|years)',  # "last 6 months"
        r'\bfor\s+(\d{4})\b',  # "for 2025" at end of sentence
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None


def extract_baseline_pairs(message: str) -> List[str]:
    """Extract baseline pairs from user message.
    
    Matches patterns like:
    - "alongside JTO/USDT"
    - "with BTC/USDT and ETH/USDT"
    """
    patterns = [
        r'alongside\s+([A-Z0-9]+/[A-Z0-9]+)',  # "alongside JTO/USDT"
        r'with\s+([A-Z0-9]+/[A-Z0-9]+)',  # "with BTC/USDT"
        r'([A-Z0-9]+/[A-Z0-9]+)',  # "BTC/USDT"
    ]
    
    pairs = []
    for pattern in patterns:
        matches = re.findall(pattern, message, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            pair = match.upper()
            if pair not in pairs:
                pairs.append(pair)
    
    return pairs


def calculate_confidence(message: str, patterns: List[str]) -> float:
    """Calculate confidence score based on pattern matches.
    
    Returns a float between 0.0 and 1.0 based on:
    - Number of matching patterns
    - Pattern specificity (longer patterns = higher confidence)
    """
    message_lower = message.lower()
    matches = 0
    total_weight = 0.0
    
    for pattern in patterns:
        try:
            if re.search(pattern, message_lower, re.IGNORECASE):
                matches += 1
                # Longer patterns are more specific = higher weight
                total_weight += len(pattern)
                logger.debug(f"Pattern matched: {pattern} in message: {message_lower}")
        except re.error:
            logger.warning(f"Invalid regex pattern: {pattern}")
    
    if matches == 0:
        return 0.0
    
    # Improved confidence calculation:
    # - Any match gives at least 0.5 base confidence
    # - Additional matches increase confidence
    # - Pattern specificity adds bonus
    base_confidence = 0.5 + (matches - 1) * 0.15  # 0.5 for 1 match, up to 0.8 for 3+ matches
    specificity_bonus = min(total_weight / (len(patterns) * 15), 0.2)  # Max 0.2 bonus
    
    confidence = min(base_confidence + specificity_bonus, 1.0)
    logger.debug(f"Confidence: {confidence:.2f} (matches: {matches}/{len(patterns)})")
    return confidence


# ── Intent Handlers ─────────────────────────────────────────────────────────────


def handle_pair_discovery(message: str, extracted_slots: Dict[str, Any]) -> WorkflowPlan:
    """Generate workflow plan for pair_discovery intent.
    
    Workflow:
    1. Read strategy file to get timeframe
    2. Get pair universe from backend
    3. Ask for timerange if missing
    4. Propose run_pair_explorer with baseline pairs preserved
    5. After confirmation, execute and analyze results
    """
    strategy_name = extracted_slots.get("strategy_name")
    timerange = extracted_slots.get("timerange")
    baseline_pairs = extracted_slots.get("baseline_pairs", [])
    
    steps: List[WorkflowStep] = []
    missing_slots: List[str] = []
    
    if not strategy_name:
        missing_slots.append("strategy_name")
        return WorkflowPlan(
            intent="pair_discovery",
            steps=[],
            missing_slots=missing_slots,
            extracted_slots=extracted_slots,
            confidence=0.0,
        )
    
    # Step 1: Read strategy to get timeframe
    steps.append(WorkflowStep(
        tool="read_strategy_file",
        action=None,
        args={"strategy_name": strategy_name},
        requires_confirmation=False,
    ))
    
    # Step 2: Get pair universe
    quote_currency = "USDT"  # Default, could be extracted from baseline pairs
    if baseline_pairs:
        # Extract quote currency from first baseline pair
        if "/" in baseline_pairs[0]:
            quote_currency = baseline_pairs[0].split("/")[1]
    
    steps.append(WorkflowStep(
        tool="get_pair_universe",
        action=None,
        args={"quote_currency": quote_currency},
        requires_confirmation=False,
    ))
    
    # Step 3: Ask for timerange if missing
    if not timerange:
        steps.append(WorkflowStep(
            tool=None,
            action="ask_missing",
            args={"slot": "timerange", "prompt": "What timerange do you want to backtest?"},
            requires_confirmation=False,
        ))
        missing_slots.append("timerange")
    else:
        # Step 4: Propose pair explorer if we have all required info
        steps.append(WorkflowStep(
            tool="run_pair_explorer",
            action=None,
            args={
                "strategy_name": strategy_name,
                "timerange": timerange,
                # Pairs will be filled after get_pair_universe returns
                "pairs": baseline_pairs,  # Will be merged with universe
            },
            requires_confirmation=True,
        ))
    
    return WorkflowPlan(
        intent="pair_discovery",
        steps=steps,
        missing_slots=missing_slots,
        extracted_slots=extracted_slots,
        confidence=extracted_slots.get("confidence", 0.0),
    )


def handle_strategy_analysis(message: str, extracted_slots: Dict[str, Any]) -> WorkflowPlan:
    """Generate workflow plan for strategy_analysis intent.
    
    This is a placeholder - for now, we fall back to model orchestration
    since strategy explanation is primarily conversational.
    """
    return WorkflowPlan(
        intent="strategy_analysis",
        steps=[],
        missing_slots=[],
        extracted_slots=extracted_slots,
        confidence=extracted_slots.get("confidence", 0.0),
    )


def handle_backtest_run(message: str, extracted_slots: Dict[str, Any]) -> WorkflowPlan:
    """Generate workflow plan for backtest_run intent.
    
    Placeholder - fall back to model orchestration for now.
    """
    return WorkflowPlan(
        intent="backtest_run",
        steps=[],
        missing_slots=[],
        extracted_slots=extracted_slots,
        confidence=extracted_slots.get("confidence", 0.0),
    )


def handle_optimizer_run(message: str, extracted_slots: Dict[str, Any]) -> WorkflowPlan:
    """Generate workflow plan for optimizer_run intent.
    
    Placeholder - fall back to model orchestration for now.
    """
    return WorkflowPlan(
        intent="optimizer_run",
        steps=[],
        missing_slots=[],
        extracted_slots=extracted_slots,
        confidence=extracted_slots.get("confidence", 0.0),
    )


# ── Intent Registry ────────────────────────────────────────────────────────────


_INTENT_REGISTRY: Dict[str, IntentSpec] = {
    "pair_discovery": IntentSpec(
        name="pair_discovery",
        patterns=[
            r'find\s+(more\s+)?profitable\s+pairs',
            r'better\s+pairs',
            r'test\s+pairs\s+for\s+\w+',
            r'pair\s+discovery',
            r'explore\s+pairs',
            r'find\s+pairs',
            r'search\s+pairs',
            r'need\s+better\s+pairs',
            r'want\s+better\s+pairs',
        ],
        required_slots=["strategy_name", "timerange"],  # timerange is optional but we extract it
        confidence_threshold=0.55,  # Lowered to catch "find pairs" variations
        handler=handle_pair_discovery,
    ),
    "strategy_analysis": IntentSpec(
        name="strategy_analysis",
        patterns=[
            r'explain\s+strategy',
            r'how\s+does\s+\w+\s+work',
            r'analyze\s+strategy',
            r'what\s+does\s+\w+\s+do',
            r'explain\s+how\s+\w+\s+works',
        ],
        required_slots=["strategy_name"],
        confidence_threshold=0.55,  # Lowered for conversational variations
        handler=handle_strategy_analysis,
    ),
    "backtest_run": IntentSpec(
        name="backtest_run",
        patterns=[
            r'run\s+backtest',
            r'backtest\s+\w+',
            r'test\s+\w+\s+with\s+backtest',
        ],
        required_slots=["strategy_name"],
        confidence_threshold=0.65,  # Lowered slightly
        handler=handle_backtest_run,
    ),
    "optimizer_run": IntentSpec(
        name="optimizer_run",
        patterns=[
            r'optimize',
            r'find\s+best\s+parameters',
            r'hyperopt',
            r'tune\s+parameters',
            r'optimize\s+parameters',
        ],
        required_slots=["strategy_name"],
        confidence_threshold=0.60,  # Lowered to catch "optimize X"
        handler=handle_optimizer_run,
    ),
}


# ── Public API ─────────────────────────────────────────────────────────────────


def route_intent(message: str) -> Optional[WorkflowPlan]:
    """Detect intent and generate workflow plan if confidence is high enough.
    
    Args:
        message: User's natural language message
        
    Returns:
        WorkflowPlan if intent is confidently detected, None otherwise
    """
    best_intent = None
    best_confidence = 0.0
    best_spec = None
    
    for intent_name, spec in _INTENT_REGISTRY.items():
        confidence = calculate_confidence(message, spec.patterns)
        if confidence > best_confidence:
            best_confidence = confidence
            best_intent = intent_name
            best_spec = spec
    
    if best_intent and best_spec and best_confidence >= best_spec.confidence_threshold:
        # Extract slots for this intent
        extracted_slots = {"confidence": best_confidence}
        
        if "strategy_name" in best_spec.required_slots:
            strategy_name = extract_strategy_name(message)
            if strategy_name:
                extracted_slots["strategy_name"] = strategy_name
        
        if "timerange" in best_spec.required_slots:
            timerange = extract_timerange(message)
            if timerange:
                extracted_slots["timerange"] = timerange
        
        if best_intent == "pair_discovery":
            baseline_pairs = extract_baseline_pairs(message)
            if baseline_pairs:
                extracted_slots["baseline_pairs"] = baseline_pairs
        
        # Generate workflow plan
        if best_spec.handler:
            return best_spec.handler(message, extracted_slots)
    
    return None


def list_intents() -> List[str]:
    """List all registered intent names."""
    return list(_INTENT_REGISTRY.keys())


def get_intent_spec(intent_name: str) -> Optional[IntentSpec]:
    """Get intent specification by name."""
    return _INTENT_REGISTRY.get(intent_name)
