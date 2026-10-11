"""Configuration models for the forecasting prototype."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.core import constants

class ValidatorConfig(BaseModel):
    validator_id: UUID = Field(default_factory=uuid4)
    available_providers: list[str] = Field(
        default_factory=lambda: list(constants.VALIDATOR.available_providers)
    )
    orchestrator_api_url: str = constants.ORCHESTRATOR_API_URL

    # Wall-clock budget for one agent `predict` call. Agents run in the
    # validator process, so this is the only execution limit applied.
    sandbox_timeout_seconds: int = constants.VALIDATOR.sandbox_timeout_seconds


class BittensorConfig(BaseModel):
    """Validator-side Bittensor wallet configuration.

    Read by the validator process to sign gateway requests. Agents execute in
    the same process, so they are not isolated from the loaded hotkey.
    """

    wallet_path: Path = constants.BITTENSOR.wallet_path
    wallet_name: str = constants.BITTENSOR.wallet_name
    wallet_hotkey: str = constants.BITTENSOR.wallet_hotkey
    netuid: int = constants.BITTENSOR.netuid
    subtensor_network: str = constants.BITTENSOR.subtensor_network
    signing_required: bool = constants.BITTENSOR.signing_required
    weights_version_key: int = constants.BITTENSOR.weights_version_key


class StorageConfig(BaseModel):
    backend: str = constants.STORAGE.backend
    data_dir: Path = constants.STORAGE.data_dir
    persist_traces: bool = constants.STORAGE.persist_traces


class GatewayConfig(BaseModel):
    call_timeout_seconds: int = constants.GATEWAY.call_timeout_seconds
    debug_log_raw_response: bool = constants.GATEWAY.debug_log_raw_response
    debug_raw_response_max_chars: int = constants.GATEWAY.debug_raw_response_max_chars


class ValidatorLoopConfig(BaseModel):
    """Long-running Bittensor validator configuration.

    Controls the per-mechanism enable toggles and weight shares that the
    main ``Validator`` reads at each epoch. When ``loop_enabled`` is false,
    the entrypoint runs only the local signing proxy + agent orchestrator
    daemon for dev use.
    """

    loop_enabled: bool = constants.VALIDATOR_LOOP.loop_enabled
    market_enabled: bool = constants.VALIDATOR_LOOP.market_enabled
    forecasting_enabled: bool = constants.VALIDATOR_LOOP.forecasting_enabled
    metadata_manager_enabled: bool = constants.VALIDATOR_LOOP.metadata_manager_enabled
    market_weight_share: float = constants.VALIDATOR_LOOP.market_weight_share
    forecasting_weight_share: float = constants.VALIDATOR_LOOP.forecasting_weight_share
    market_api_url: Optional[str] = constants.VALIDATOR_LOOP.market_api_url
    use_synthetic_trading_data: bool = constants.VALIDATOR_LOOP.use_synthetic_trading_data
    write_trading_history: bool = constants.VALIDATOR_LOOP.write_trading_history
    db_score_logging: bool = constants.VALIDATOR_LOOP.db_score_logging
    wandb_enabled: bool = constants.VALIDATOR_LOOP.wandb_enabled
    rolling_window_days: int = constants.VALIDATOR_LOOP.rolling_window_days
    metadata_update_interval_seconds: int = constants.VALIDATOR_LOOP.metadata_update_interval_seconds
    metadata_batch_size: int = constants.VALIDATOR_LOOP.metadata_batch_size
    metadata_batch_delay_seconds: float = constants.VALIDATOR_LOOP.metadata_batch_delay_seconds
    metadata_per_uid_delay_seconds: float = constants.VALIDATOR_LOOP.metadata_per_uid_delay_seconds
    metadata_use_bulk_commitments: bool = constants.VALIDATOR_LOOP.metadata_use_bulk_commitments
    set_weights_enabled: bool = constants.VALIDATOR_LOOP.set_weights_enabled
    assignment_execution_cooldown_seconds: int = constants.VALIDATOR_LOOP.assignment_execution_cooldown_seconds


class AppConfig(BaseModel):
    validator: ValidatorConfig = Field(default_factory=ValidatorConfig)
    bittensor: BittensorConfig = Field(default_factory=BittensorConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    loop: ValidatorLoopConfig = Field(default_factory=ValidatorLoopConfig)
    log_level: str = constants.LOG_LEVEL

    @classmethod
    def load_default(cls) -> "AppConfig":
        """Build config from code defaults in :mod:`src.core.constants`.

        ``ORCHESTRATOR_API_URL`` from the environment (including repo-root ``.env``)
        overrides the orchestrator URL when set. Other loop/sandbox settings stay
        code-driven; provider credentials are still read by gateway clients.
        """
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)

        cfg = cls()
        orch = os.environ.get("ORCHESTRATOR_API_URL", "").strip()
        if orch:
            cfg.validator.orchestrator_api_url = orch.rstrip("/")
        return cfg
