"""Environment-backed bot configuration."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    discord_token: str
    notification_channel_id: int
    ps99_universe_id: int
    database_path: str = "data/ps99_bot.sqlite3"
    poll_interval_seconds: int = 45
    disconnect_confirmation_checks: int = 2
    presence_batch_size: int = 50
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_TOKEN is required")
        channel_id = _positive_int("NOTIFICATION_CHANNEL_ID")
        universe_id = _positive_int("PS99_UNIVERSE_ID")
        interval = _int_env("POLL_INTERVAL_SECONDS", 45, minimum=30, maximum=60)
        confirmations = _int_env("DISCONNECT_CONFIRMATION_CHECKS", 2, minimum=2, maximum=10)
        batch_size = _int_env("PRESENCE_BATCH_SIZE", 50, minimum=1, maximum=100)
        db_path = os.getenv("DATABASE_PATH", "data/ps99_bot.sqlite3").strip()
        if not db_path:
            raise ValueError("DATABASE_PATH cannot be empty")
        return cls(token, channel_id, universe_id, db_path, interval, confirmations,
                   batch_size, os.getenv("LOG_LEVEL", "INFO").upper())


def _positive_int(name: str) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value
