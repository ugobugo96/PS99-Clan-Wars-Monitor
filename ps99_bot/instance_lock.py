"""Prevent concurrent bot processes from sharing one SQLite database."""

import fcntl
import os
from pathlib import Path
from typing import Optional


class InstanceAlreadyRunning(RuntimeError):
    """Raised when another process already holds this bot's database lock."""


class InstanceLock:
    """A POSIX advisory lock kept for the lifetime of the bot process."""

    def __init__(self, database_path: str):
        self.database_path = database_path
        self.lock_path: Optional[Path] = None
        self._descriptor: Optional[int] = None
        if database_path != ":memory:":
            normalized_database_path = Path(database_path).expanduser().resolve()
            self.lock_path = normalized_database_path.with_name(
                normalized_database_path.name + ".lock"
            )

    def acquire(self) -> None:
        if self.lock_path is None:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise InstanceAlreadyRunning(
                "Another bot process is already using this database."
            ) from exc
        self._descriptor = descriptor
        os.ftruncate(descriptor, 0)
        os.write(descriptor, (str(os.getpid()) + "\n").encode("ascii"))

    def release(self) -> None:
        if self._descriptor is None:
            return
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._descriptor = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.release()
