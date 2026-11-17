"""Async clients for Roblox's public user and Presence endpoints."""

import asyncio
import logging
from typing import Dict, Iterable, List, Optional

try:
    import aiohttp
except ImportError:  # Keep classification logic testable without optional runtime packages installed.
    aiohttp = None

log = logging.getLogger(__name__)
PRESENCE_URL = "https://presence.roblox.com/v1/presence/users"
USERNAME_URL = "https://users.roblox.com/v1/usernames/users"


class RobloxAPIError(RuntimeError):
    pass


class RobloxClient:
    def __init__(self, session, batch_size: int = 50):
        self.session = session
        self.batch_size = batch_size

    async def resolve_username(self, username: str) -> dict:
        payload = {"usernames": [username], "excludeBannedUsers": False}
        data = await self._post_json(USERNAME_URL, payload)
        users = data.get("data", [])
        if not users:
            raise ValueError("Roblox username not found. Check the spelling and try again.")
        return users[0]

    async def get_presences(self, user_ids: Iterable[int]) -> Dict[int, dict]:
        ids = list(user_ids)
        result: Dict[int, dict] = {}
        for start in range(0, len(ids), self.batch_size):
            data = await self._post_json(PRESENCE_URL, {"userIds": ids[start:start + self.batch_size]})
            presences = data.get("userPresences")
            if not isinstance(presences, list):
                raise RobloxAPIError("Roblox Presence API response did not contain userPresences")
            for presence in presences:
                try:
                    result[int(presence["userId"])] = presence
                except (KeyError, TypeError, ValueError):
                    log.warning("Ignoring malformed Roblox presence entry")
        return result

    async def _post_json(self, url: str, payload: dict) -> dict:
        if aiohttp is None:
            raise RobloxAPIError("aiohttp is required; install dependencies with pip install -r requirements.txt")
        for attempt in range(4):
            try:
                async with self.session.post(url, json=payload) as response:
                    if response.status == 429:
                        retry_after = response.headers.get("Retry-After")
                        delay = min(float(retry_after), 60.0) if retry_after else min(2 ** attempt, 30)
                        if attempt == 3:
                            raise RobloxAPIError("Roblox API rate limited the request after retries")
                        log.warning("Roblox API rate limited request; retrying in %.1fs", delay)
                        await asyncio.sleep(delay)
                        continue
                    if response.status >= 500 and attempt < 3:
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    if response.status >= 400:
                        body = (await response.text())[:300]
                        raise RobloxAPIError("Roblox API returned HTTP %s: %s" % (response.status, body))
                    data = await response.json(content_type=None)
                    if not isinstance(data, dict):
                        raise RobloxAPIError("Roblox API returned an unexpected response")
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt == 3:
                    raise RobloxAPIError("Could not reach Roblox API") from exc
                await asyncio.sleep(min(2 ** attempt, 8))
        raise RobloxAPIError("Roblox API request failed")


def classify_presence(presence: Optional[dict], target_universe_id: int) -> str:
    """Return ps99, other, offline, or unknown from a single response."""
    if presence is None:
        return "unknown"
    presence_type = presence.get("userPresenceType")
    if not isinstance(presence_type, int):
        return "unknown"
    if presence_type == 0:
        return "offline"
    if presence_type == 2:
        universe_id = presence.get("universeId")
        if universe_id is None:
            return "unknown"
        try:
            return "ps99" if int(universe_id) == target_universe_id else "other"
        except (TypeError, ValueError):
            return "unknown"
    # Online on website, Studio, or another non-game presence is not in PS99.
    return "other"
