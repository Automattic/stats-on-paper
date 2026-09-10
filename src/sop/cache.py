"""Power-loss-safe snapshot cache."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sop.models import SnapshotFormatError, StatsSnapshot, snapshot_from_public_json


class CacheError(RuntimeError):
    """The snapshot cache could not be read or written."""


class SnapshotCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "snapshot.json"

    def load(self) -> StatsSnapshot | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as error:
            raise CacheError(
                f"Could not read snapshot cache {self.path}: {error}"
            ) from error
        try:
            return snapshot_from_public_json(payload)
        except SnapshotFormatError as error:
            raise CacheError(
                f"Snapshot cache {self.path} is not a valid snapshot: {error}"
            ) from error

    def save(self, snapshot: StatsSnapshot) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=".snapshot-",
                suffix=".json",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(snapshot.to_public_json(), temporary, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.path)
        except OSError as error:
            raise CacheError(
                f"Could not write snapshot cache {self.path}: {error}"
            ) from error
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def is_fresh(
        snapshot: StatsSnapshot,
        *,
        max_age: float,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        age = (
            current.astimezone(UTC) - snapshot.fetched_at.astimezone(UTC)
        ).total_seconds()
        return 0 <= age <= max_age
