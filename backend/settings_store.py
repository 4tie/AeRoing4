"""settings_store.py contains backend logic for settings store."""

from __future__ import annotations
import shutil
import sys
from pathlib import Path

from .core.errors import BackendError
from .models import SaveSettingsRequest, SettingsModel
from .services.interfaces import ISettingsStore
from .utils import atomic_write_json, ensure_directory, read_json


class SettingsStore(ISettingsStore):
    """SettingsStore contains class-level backend logic."""
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.settings_file = root_dir / "data" / "strategy_lab_settings.json"

    def defaults(self) -> SettingsModel:
        return SettingsModel(
            freqtrade_executable_path="py -m freqtrade",
            strategies_directory_path=str(self.root_dir / "user_data" / "strategies"),
            user_data_directory_path=str(self.root_dir / "user_data"),
            default_config_file_path=str(self.root_dir / "user_data" / "config.json"),
            ollama_api_url="http://localhost:11434",
            ollama_model="",
            ollama_provider="local",
            ollama_api_key="",
            network_mode="local",
            hyperopt_workers=2,
            ollama_self_healing_enabled=False,
            ollama_timeout=30,
            ollama_retry_delays=[2, 5, 10, 15],
            ollama_circuit_breaker_threshold=5,
            ollama_circuit_breaker_cooldown=300,
            ollama_enable_health_check=True,
            ollama_health_check_interval=60,
            ollama_timeout_chat=30,
            ollama_timeout_generate=60,
            ollama_timeout_autoquant=120,
            ollama_connection_pool_size=10,
            ollama_connection_keepalive=30,
            ollama_model_chat="",
            ollama_model_autoquant="",
            ollama_model_strategylab="hermes3:3b",
            ollama_model_optimizer="",
            ai_assistant_sandbox_enabled=False,
        )

    def load(self) -> SettingsModel:
        raw = read_json(self.settings_file)
        if raw is None:
            defaults = self.defaults()
            atomic_write_json(self.settings_file, defaults.model_dump(mode="json"))
            return defaults
        return SettingsModel.model_validate(raw)

    def save(self, request: SaveSettingsRequest | SettingsModel) -> SettingsModel:
        settings = SettingsModel.model_validate(request)
        self._validate(settings)
        atomic_write_json(self.settings_file, settings.model_dump(mode="json"))
        return settings

    def _validate(self, settings: SettingsModel) -> None:
        # For "py -m freqtrade" command, check if python is available
        if settings.freqtrade_executable_path == "py -m freqtrade":
            if shutil.which("py") is None and shutil.which("python") is None:
                raise BackendError(
                    "Invalid freqtrade_executable_path: python executable was not found.",
                    status_code=400,
                )
        elif shutil.which(settings.freqtrade_executable_path) is None and not Path(
            settings.freqtrade_executable_path
        ).is_file():
            raise BackendError(
                "Invalid freqtrade_executable_path: executable was not found.",
                status_code=400,
            )

        for field_name, raw_path in [
            ("strategies_directory_path", settings.strategies_directory_path),
            ("user_data_directory_path", settings.user_data_directory_path),
        ]:
            path = Path(raw_path)
            if not path.exists() or not path.is_dir():
                ensure_directory(path)

        config_path = Path(settings.default_config_file_path)
        if not config_path.exists():
            ensure_directory(config_path.parent)
            config_path.write_text("{}")
