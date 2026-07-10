"""Strategy template generator for the Auto-Quant pipeline.

This module acts as a coordinator, importing and re-exporting strategy template
generation functions from the generator subpackage to maintain backward compatibility.
"""

from .generator import (
    generate_strategy_source_adaptive,
    generate_strategy_source,
    generate_strategy_source_momentum,
    generate_strategy_source_omni,
    generate_strategy_source_ensemble,
    generate_strategy_source_market_aware,
    generate_strategy_source_indicator_library,
)

__all__ = [
    "generate_strategy_source_adaptive",
    "generate_strategy_source",
    "generate_strategy_source_momentum",
    "generate_strategy_source_omni",
    "generate_strategy_source_ensemble",
    "generate_strategy_source_market_aware",
    "generate_strategy_source_indicator_library",
]
