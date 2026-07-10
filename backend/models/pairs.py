"""Pair selector state, request, response, and configuration models."""

from __future__ import annotations
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from .base import StrictModel

# ── Pair Selection Models ─────────────────────────────────────────────────────────

class PairSelectorState(StrictModel):
    """Current state of the pair selector."""
    available_pairs: list[str] = Field(default_factory=list)
    extended_pairs: list[str] = Field(default_factory=list)
    selected_pairs: list[str] = Field(default_factory=list)
    favorite_pairs: set[str] = Field(default_factory=set)
    locked_pairs: set[str] = Field(default_factory=set)
    max_open_trades: int = 1
    is_dropdown_open: bool = False

    @field_validator("available_pairs", "selected_pairs", mode="before")
    @classmethod
    def validate_pair_lists(cls, value: Any) -> list[str]:
        """Validate or transform `validate_pair_lists` input before the model is accepted."""
        if value is None:
            return []
        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, list):
            items = value
        else:
            raise ValueError("Value must be a list or comma-separated string.")
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        return cleaned or []

    @field_validator("favorite_pairs", "locked_pairs", mode="before")
    @classmethod
    def validate_pair_sets(cls, value: Any) -> set[str]:
        """Validate or transform `validate_pair_sets` input before the model is accepted."""
        if value is None:
            return set()
        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, list):
            items = value
        elif isinstance(value, set):
            return value
        else:
            raise ValueError("Value must be a list, set, or comma-separated string.")
        cleaned = {str(item).strip() for item in items if str(item).strip()}
        return cleaned or set()

    @field_validator("max_open_trades")
    @classmethod
    def validate_max_open_trades(cls, value: int) -> int:
        """Validate or transform `validate_max_open_trades` input before the model is accepted."""
        if value < 1:
            raise ValueError("max_open_trades must be at least 1.")
        return value


class ToggleFavoriteRequest(StrictModel):
    """Request to toggle favorite status of a pair."""
    pair: str

    @field_validator("pair", mode="before")
    @classmethod
    def validate_pair(cls, value: Any) -> str:
        """Validate or transform `validate_pair` input before the model is accepted."""
        text = str(value or "").strip()
        if not text:
            raise ValueError("pair is required.")
        if "/" not in text:
            raise ValueError("pair must contain '/' (e.g., BTC/USDT).")
        return text


class ToggleLockRequest(StrictModel):
    """Request to toggle lock status of a pair."""
    pair: str

    @field_validator("pair", mode="before")
    @classmethod
    def validate_pair(cls, value: Any) -> str:
        """Validate or transform `validate_pair` input before the model is accepted."""
        text = str(value or "").strip()
        if not text:
            raise ValueError("pair is required.")
        if "/" not in text:
            raise ValueError("pair must contain '/' (e.g., BTC/USDT).")
        return text


class SelectPairRequest(StrictModel):
    """Request to select/deselect a pair."""
    pair: str
    selected: bool = True

    @field_validator("pair", mode="before")
    @classmethod
    def validate_pair(cls, value: Any) -> str:
        """Validate or transform `validate_pair` input before the model is accepted."""
        text = str(value or "").strip()
        if not text:
            raise ValueError("pair is required.")
        if "/" not in text:
            raise ValueError("pair must contain '/' (e.g., BTC/USDT).")
        return text


class RandomizePairsRequest(StrictModel):
    """Request to randomize pair selection."""
    preserve_locked: bool = True
    max_pairs: int | None = None

    @field_validator("max_pairs")
    @classmethod
    def validate_max_pairs(cls, value: int | None) -> int | None:
        """Validate or transform `validate_max_pairs` input before the model is accepted."""
        if value is not None and value < 1:
            raise ValueError("max_pairs must be at least 1.")
        return value


class UpdateMaxTradesRequest(StrictModel):
    """Request to update maximum open trades."""
    max_open_trades: int

    @field_validator("max_open_trades")
    @classmethod
    def validate_max_open_trades(cls, value: int) -> int:
        """Validate or transform `validate_max_open_trades` input before the model is accepted."""
        if value < 1:
            raise ValueError("max_open_trades must be at least 1.")
        return value


class SearchPairsRequest(StrictModel):
    """Request to search/filter pairs."""
    search_term: str = ""
    show_favorites_only: bool = False


class PairListResponse(StrictModel):
    """Response containing filtered pair lists."""
    favorites: list[str]
    other_pairs: list[str]
    total_count: int


class PairSelectionValidation(StrictModel):
    """Validation result for pair selection."""
    is_valid: bool
    error_message: str | None = None
    current_count: int
    max_allowed: int
    can_add_more: bool


class PairSelectorConfig(StrictModel):
    """Configuration for pair selector."""
    default_pairs: list[str] = Field(
        default_factory=lambda: [
            # Large caps
            "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
            "ADA/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT", "LINK/USDT",
            "ATOM/USDT", "UNI/USDT", "LTC/USDT", "BCH/USDT", "ETC/USDT",
            # Mid caps
            "DOGE/USDT", "SHIB/USDT", "TRX/USDT", "XLM/USDT", "VET/USDT",
            "FIL/USDT", "ICP/USDT", "HBAR/USDT", "APT/USDT", "ARB/USDT",
            "OP/USDT", "INJ/USDT", "SUI/USDT", "SEI/USDT", "TIA/USDT",
            "NEAR/USDT", "FTM/USDT", "ALGO/USDT", "EGLD/USDT", "XTZ/USDT",
            "SAND/USDT", "MANA/USDT", "AXS/USDT", "GALA/USDT", "ENJ/USDT",
            # DeFi
            "AAVE/USDT", "CRV/USDT", "MKR/USDT", "SNX/USDT", "COMP/USDT",
            "1INCH/USDT", "SUSHI/USDT", "BAL/USDT", "YFI/USDT", "LDO/USDT",
            "RPL/USDT", "GMX/USDT", "DYDX/USDT", "PENDLE/USDT",
            # Layer 2 / infra
            "IMX/USDT", "BLUR/USDT", "STX/USDT", "MINA/USDT", "ZK/USDT",
            "STRK/USDT", "PYTH/USDT", "JTO/USDT", "WIF/USDT", "BONK/USDT",
        ]
    )
    extended_pairs: list[str] = Field(
        default_factory=lambda: [
            # Additional USDT — large/mid
            "PEPE/USDT", "FLOKI/USDT", "LUNC/USDT", "LUNA/USDT", "USTC/USDT",
            "KAVA/USDT", "ROSE/USDT", "ONE/USDT", "ZIL/USDT", "IOTA/USDT",
            "QTUM/USDT", "ONT/USDT", "ICX/USDT", "ZEN/USDT", "SC/USDT",
            "WAVES/USDT", "DCR/USDT", "DGB/USDT", "RVN/USDT", "NANO/USDT",
            "XEM/USDT", "LSK/USDT", "STEEM/USDT", "ARK/USDT", "PIVX/USDT",
            "XVG/USDT", "BTG/USDT", "BCD/USDT", "BTM/USDT", "KMD/USDT",
            "SYS/USDT", "XZC/USDT", "MONA/USDT", "DASH/USDT", "ZEC/USDT",
            # Gaming / metaverse
            "GODS/USDT", "ILV/USDT", "ALICE/USDT", "TLM/USDT", "HERO/USDT",
            "WAXP/USDT", "CHZ/USDT", "FLOW/USDT", "THETA/USDT", "TFUEL/USDT",
            "RNDR/USDT", "FET/USDT", "OCEAN/USDT", "GRT/USDT", "API3/USDT",
            "BAND/USDT", "RLC/USDT", "NMR/USDT", "REP/USDT", "KNC/USDT",
            "SAND/USDT", "MANA/USDT", "AXS/USDT", "GALA/USDT", "ENJ/USDT",
            "IMX/USDT", "BLUR/USDT", "STX/USDT", "MINA/USDT", "ZK/USDT",
            # DeFi extended
            "CAKE/USDT", "ALPHA/USDT", "BADGER/USDT", "RUNE/USDT", "OSMO/USDT",
            "JUNO/USDT", "SCRT/USDT", "EVMOS/USDT", "UMEE/USDT", "AXL/USDT",
            "AGIX/USDT", "CTSI/USDT", "CELR/USDT", "SKL/USDT", "BOBA/USDT",
            "METIS/USDT", "CELO/USDT", "GLMR/USDT", "MOVR/USDT", "KSM/USDT",
            "AAVE/USDT", "CRV/USDT", "MKR/USDT", "SNX/USDT", "COMP/USDT",
            "1INCH/USDT", "SUSHI/USDT", "BAL/USDT", "YFI/USDT", "LDO/USDT",
            "RPL/USDT", "GMX/USDT", "DYDX/USDT", "PENDLE/USDT", "UNI/USDT",
            # Layer 1 extended
            "EOS/USDT", "XMR/USDT", "ZEC/USDT", "DASH/USDT", "NEO/USDT",
            "GAS/USDT", "BTT/USDT", "HT/USDT", "OKB/USDT", "CRO/USDT",
            "FTT/USDT", "GT/USDT", "MX/USDT", "KCS/USDT", "BGB/USDT",
            "SOL/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT",
            "ATOM/USDT", "NEAR/USDT", "FTM/USDT", "ALGO/USDT", "EGLD/USDT",
            "XTZ/USDT", "HBAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT",
            "INJ/USDT", "SUI/USDT", "SEI/USDT", "TIA/USDT", "STRK/USDT",
            # Stablecoins / wrapped
            "WBTC/USDT", "STETH/USDT", "WETH/USDT", "CBETH/USDT", "RETH/USDT",
            "USDC/USDT", "USDP/USDT", "DAI/USDT", "TUSD/USDT", "FRAX/USDT",
            "BUSD/USDT", "USDD/USDT", "USDT/USDT", "FDUSD/USDT", "PYUSD/USDT",
            # Meme / new
            "DEGEN/USDT", "BRETT/USDT", "MOG/USDT", "TURBO/USDT", "POPCAT/USDT",
            "MEW/USDT", "BOME/USDT", "SLERF/USDT", "PONKE/USDT", "MYRO/USDT",
            "DOGE/USDT", "SHIB/USDT", "TRX/USDT", "XLM/USDT", "VET/USDT",
            "FIL/USDT", "ICP/USDT", "WIF/USDT", "BONK/USDT", "PYTH/USDT",
            "JTO/USDT", "ORCA/USDT", "RAY/USDT", "HNT/USDT", "MOBILE/USDT",
            # Cross-chain / interoperability
            "POLY/USDT", "MATIC/USDT", "QNT/USDT", "COS/USDT", "ROSE/USDT",
            "GLM/USDT", "FX/USDT", "LPT/USDT", "MASK/USDT", "RAD/USDT",
            "INDEX/USDT", "MLN/USDT", "BOND/USDT", "CVX/USDT", "ANGLE/USDT",
            # AI / data
            "FET/USDT", "RNDR/USDT", "OCEAN/USDT", "GRT/USDT", "NMR/USDT",
            "AGIX/USDT", "CQT/USDT", "ROSE/USDT", "TAO/USDT", "FIL/USDT",
            # Privacy
            "XMR/USDT", "ZEC/USDT", "DASH/USDT", "SCRT/USDT", "XVG/USDT",
            "ZEN/USDT", "XZC/USDT", "BTG/USDT", "KMD/USDT", "PIVX/USDT",
        ]
    )
    default_max_trades: int = 1
    enable_favorites: bool = True
    enable_locking: bool = True
    enable_randomization: bool = True

    @classmethod
    def load(cls) -> "PairSelectorConfig":
        """Load configuration from the pair selector config file."""
        import json
        from pathlib import Path
        
        # Try to load from user_data directory
        config_path = Path("user_data/pair_selector/pair_selector_config.json")
        
        # If not found, try absolute path from current working directory
        if not config_path.exists():
            # Try to find it relative to the backend module
            backend_dir = Path(__file__).parent.parent.parent
            config_path = backend_dir / "user_data/pair_selector/pair_selector_config.json"
        
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls.model_validate(data)
            except Exception:
                # If loading fails, return default config
                pass
        
        # Return default configuration if file doesn't exist or loading fails
        return cls()
