import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ps99_bot.database import Database
from ps99_bot.instance_lock import InstanceAlreadyRunning, InstanceLock
from ps99_bot.monitor import WarMonitor
from ps99_bot.roblox import classify_presence


class PresenceClassificationTests(unittest.TestCase):
    def test_game_presence_matches_configured_experience(self):
        self.assertEqual(classify_presence({"userPresenceType": 2, "universeId": 99}, 99), "ps99")
        self.assertEqual(classify_presence({"userPresenceType": 2, "universeId": 100}, 99), "other")

    def test_offline_non_game_and_missing_are_distinct(self):
        self.assertEqual(classify_presence({"userPresenceType": 0}, 99), "offline")
        self.assertEqual(classify_presence({"userPresenceType": 1}, 99), "other")
        self.assertEqual(classify_presence({"userPresenceType": 2}, 99), "unknown")
        self.assertEqual(classify_presence(None, 99), "unknown")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_duplicate_discord_or_roblox_registration_is_rejected(self):
        self.db.register_player(10, 20, "Alpha")
        with self.assertRaises(ValueError):
            self.db.register_player(10, 21, "Beta")
        with self.assertRaises(ValueError):
            self.db.register_player(11, 20, "Alpha")

    def test_war_state_persists_and_start_resets_baselines(self):
        self.db.register_player(10, 20, "Alpha")
        self.db.set_war_active(True)
        self.assertTrue(self.db.is_war_active())
        self.db.set_war_active(False)
        self.assertFalse(self.db.is_war_active())

    def test_database_creates_parent_and_expands_home_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"HOME": temp_dir}):
                db = Database("~/persistent/data/players.sqlite3")
                try:
                    self.assertEqual(
                        Path(db.path),
                        (Path(temp_dir) / "persistent" / "data" / "players.sqlite3").resolve(),
                    )
                    db.register_player(10, 20, "Alpha")
                finally:
                    db.close()

                reopened = Database(str(Path(temp_dir) / "persistent" / "data" / "players.sqlite3"))
                try:
                    self.assertEqual(reopened.get_player(10)["roblox_username"], "Alpha")
                finally:
                    reopened.close()


class InstanceLockTests(unittest.TestCase):
    def test_second_process_lock_is_rejected_then_released(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "persistent" / "players.sqlite3")
            first = InstanceLock(database_path)
            second = InstanceLock(database_path)
            first.acquire()
            try:
                with self.assertRaises(InstanceAlreadyRunning):
                    second.acquire()
            finally:
                first.release()

            second.acquire()
            second.release()


class FakeRoblox:
    def __init__(self, *responses):
        self.responses = list(responses)

    async def get_presences(self, _user_ids):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return {20: response}


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_requires_two_checks_and_reconnect_notifies(self):
        db = Database(":memory:")
        db.register_player(10, 20, "Alpha")
        db.set_war_active(True)
        notifications = []

        async def notify(discord_id, reconnected, username):
            notifications.append((discord_id, reconnected, username))

        roblox = FakeRoblox(
            {"userPresenceType": 2, "universeId": 99},
            {"userPresenceType": 0},
            {"userPresenceType": 0},
            {"userPresenceType": 2, "universeId": 99},
        )
        monitor = WarMonitor(db, roblox, 99, 45, 2, notify)
        await monitor.poll_once()  # establish PS99 baseline
        await monitor.poll_once()  # first suspected check
        self.assertEqual(notifications, [])
        await monitor.poll_once()  # confirmed departure
        self.assertEqual(notifications, [(10, False, "Alpha")])
        await monitor.poll_once()  # confirmed re-entry
        self.assertEqual(notifications[-1], (10, True, "Alpha"))
        db.close()

    async def test_api_failure_never_creates_disconnect_alert(self):
        db = Database(":memory:")
        db.register_player(10, 20, "Alpha")
        db.set_war_active(True)
        notifications = []

        async def notify(*args):
            notifications.append(args)

        from ps99_bot.roblox import RobloxAPIError
        roblox = FakeRoblox({"userPresenceType": 2, "universeId": 99}, RobloxAPIError("network"))
        monitor = WarMonitor(db, roblox, 99, 45, 2, notify)
        await monitor.poll_once()
        await monitor.poll_once()
        self.assertEqual(notifications, [])
        self.assertEqual(db.get_player(10)["status"], "ps99")
        db.close()


if __name__ == "__main__":
    unittest.main()
