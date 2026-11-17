"""Polling and confirmation logic for war presence monitoring."""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Awaitable, Callable, Optional

from .roblox import RobloxAPIError, classify_presence

log = logging.getLogger(__name__)
Notify = Callable[[int, bool, str], Awaitable[None]]


class WarMonitor:
    def __init__(self, database, roblox, universe_id: int, interval: int,
                 confirmation_checks: int, notify: Notify):
        self.database = database
        self.roblox = roblox
        self.universe_id = universe_id
        self.interval = interval
        self.confirmation_checks = confirmation_checks
        self.notify = notify
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="ps99-war-monitor")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _run(self) -> None:
        while self.database.is_war_active():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Unexpected error during monitoring poll")
            await asyncio.sleep(self.interval)

    async def poll_once(self) -> None:
        players = self.database.list_players()
        if not players:
            return
        try:
            presences = await self.roblox.get_presences([p["roblox_user_id"] for p in players])
        except RobloxAPIError:
            # A failed API response is unknown, never a disconnect signal.
            log.exception("Presence check failed; leaving player states unchanged")
            return

        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for player in players:
            presence = presences.get(player["roblox_user_id"])
            observed = classify_presence(presence, self.universe_id)
            # Missing entries are unknown rather than offline to avoid false alerts.
            if observed == "unknown":
                continue
            current = player["status"]
            suspect = player["suspected_status"]
            count = player["suspected_count"]
            alerted = bool(player["alert_active"])

            if observed == "ps99":
                if alerted:
                    await self.notify(player["discord_user_id"], True, player["roblox_username"])
                    alerted = False
                current, suspect, count = "ps99", None, 0
            elif current == "unknown":
                # First successful observation is a baseline, not a disconnect.
                current, suspect, count = observed, None, 0
            elif current == "ps99":
                if suspect == observed:
                    count += 1
                else:
                    suspect, count = observed, 1
                if count >= self.confirmation_checks:
                    current, suspect, count = observed, None, 0
                    if not alerted:
                        await self.notify(player["discord_user_id"], False, player["roblox_username"])
                        alerted = True
            else:
                # Keep an away player eligible to get a disconnect alert only after
                # first observing them in PS99 during this war.
                current, suspect, count = observed, None, 0

            self.database.update_observation(player["discord_user_id"], current, suspect, count, alerted, checked_at)
