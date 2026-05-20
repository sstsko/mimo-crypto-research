"""Configuration from environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    etherscan_key: Optional[str] = None
    telegram_token: Optional[str] = None
    telegram_chat: Optional[str] = None
    db_path: Path = Path("data/chainscout.sqlite")
    alert_thresholds: tuple[float, ...] = (-5.0, -10.0, 5.0, 10.0)
    dashboard_port: int = 8080

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat)


def load_settings(env_path: Optional[Path] = None) -> Settings:
    if env_path:
        load_dotenv(env_path, override=False)
    else:
        load_dotenv(override=False)

    base_url = os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()

    if not base_url or not api_key or not model:
        raise RuntimeError(
            "Missing LLM config. Set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL in .env"
        )

    raw = os.getenv("ALERT_THRESHOLDS", "-5,-10,5,10").strip()
    try:
        thresholds = tuple(float(x.strip()) for x in raw.split(",") if x.strip())
    except ValueError:
        thresholds = (-5.0, -10.0, 5.0, 10.0)

    try:
        port = int(os.getenv("DASHBOARD_PORT", "8080"))
    except ValueError:
        port = 8080

    return Settings(
        llm_base_url=base_url.rstrip("/"),
        llm_api_key=api_key,
        llm_model=model,
        etherscan_key=os.getenv("ETHERSCAN_API_KEY") or None,
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat=os.getenv("TELEGRAM_CHAT_ID") or None,
        db_path=Path(os.getenv("DB_PATH", "data/chainscout.sqlite")),
        alert_thresholds=thresholds,
        dashboard_port=port,
    )
