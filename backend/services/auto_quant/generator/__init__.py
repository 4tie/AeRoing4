"""Strategy template generator package for the Auto-Quant pipeline."""

from .basic_generators import (
    generate_strategy_source_adaptive,
    generate_strategy_source,
    generate_strategy_source_momentum,
)
from .advanced_generators import (
    generate_strategy_source_omni,
    generate_strategy_source_ensemble,
)
from .market_aware_generators import (
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
