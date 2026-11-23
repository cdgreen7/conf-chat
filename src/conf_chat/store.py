"""Small per-user state file kept on the user's own machine.

The DHT is the source of truth, but values expire after 7 days and the
inbox is replayed on every login. Keeping which envelopes we have already
handled means old messages are not shown again, and keeping the friend list
locally means friendships outlive the 7-day expiry.
"""

import json
import os
from pathlib import Path


class Store:
    def __init__(self, path: Path | None):
        self.path = path

    @classmethod
    def for_user(cls, data_dir: str | Path, username: str) -> "Store":
        return cls(Path(data_dir) / f"{username}.json")

    def load(self) -> dict:
        if self.path is None or not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}  # corrupt or unreadable: start fresh, the DHT replay rebuilds most of it

    def save(self, state: dict) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
        os.replace(tmp, self.path)  # atomic: never leaves a half-written file
