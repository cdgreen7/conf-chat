"""Message envelope stored as the value of every DHT entry Conf-Chat writes.

Every value is a small JSON document:

    {"id": "<uuid>", "type": "dm", "from": "alice", "ts": 1731945600.0, ...}

`id` lets receivers de-duplicate (OpenDHT can deliver the same value more
than once), `ts` orders events, and the remaining fields depend on `type`.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Envelope:
    type: str
    sender: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def to_bytes(self) -> bytes:
        doc = {"id": self.id, "type": self.type, "from": self.sender, "ts": self.ts, **self.data}
        return json.dumps(doc, separators=(",", ":")).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Envelope":
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError("envelope must be a JSON object")
        try:
            return cls(
                type=str(doc.pop("type")),
                sender=str(doc.pop("from")),
                id=str(doc.pop("id")),
                ts=float(doc.pop("ts")),
                data=doc,
            )
        except KeyError as e:
            raise ValueError(f"envelope missing field {e}") from None


def make(type: str, sender: str, **data: Any) -> Envelope:
    """Shorthand: make('dm', 'alice', to='bob', text='hi')."""
    return Envelope(type=type, sender=sender, data=data)
