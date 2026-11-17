"""Small SQLite repository for registrations and monitoring state."""

import sqlite3
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS players (
                discord_user_id INTEGER PRIMARY KEY,
                roblox_user_id INTEGER NOT NULL UNIQUE,
                roblox_username TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unknown',
                suspected_status TEXT,
                suspected_count INTEGER NOT NULL DEFAULT 0,
                alert_active INTEGER NOT NULL DEFAULT 0,
                last_checked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings(key, value) VALUES ('war_active', '0');
        """)
        self.connection.commit()

    def register_player(self, discord_user_id: int, roblox_user_id: int, username: str) -> None:
        try:
            self.connection.execute(
                "INSERT INTO players(discord_user_id, roblox_user_id, roblox_username) VALUES (?, ?, ?)",
                (discord_user_id, roblox_user_id, username),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("That Discord member or Roblox account is already registered.") from exc

    def get_player(self, discord_user_id: int):
        return self.connection.execute("SELECT * FROM players WHERE discord_user_id = ?", (discord_user_id,)).fetchone()

    def list_players(self):
        return self.connection.execute("SELECT * FROM players ORDER BY roblox_username COLLATE NOCASE").fetchall()

    def update_username(self, discord_user_id: int, username: str) -> None:
        self.connection.execute("UPDATE players SET roblox_username = ? WHERE discord_user_id = ?",
                                (username, discord_user_id))
        self.connection.commit()

    def update_observation(self, discord_user_id: int, status: str, suspected_status: Optional[str],
                           suspected_count: int, alert_active: bool, checked_at: str) -> None:
        self.connection.execute("""UPDATE players SET status = ?, suspected_status = ?,
            suspected_count = ?, alert_active = ?, last_checked_at = ? WHERE discord_user_id = ?""",
            (status, suspected_status, suspected_count, int(alert_active), checked_at, discord_user_id))
        self.connection.commit()

    def is_war_active(self) -> bool:
        row = self.connection.execute("SELECT value FROM settings WHERE key = 'war_active'").fetchone()
        return bool(row and row[0] == "1")

    def set_war_active(self, active: bool) -> None:
        self.connection.execute("UPDATE settings SET value = ? WHERE key = 'war_active'", ("1" if active else "0",))
        if active:
            # Begin a new monitoring session with no inherited baseline.
            self.connection.execute("""UPDATE players SET status = 'unknown', suspected_status = NULL,
                suspected_count = 0, alert_active = 0""")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
