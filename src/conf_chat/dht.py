"""Thin wrapper around an OpenDHT node.

All Conf-Chat data is stored as JSON `Envelope`s. Keys are plain strings
such as "inbox:bob"; they are hashed to 160-bit DHT keys (`InfoHash.get`).
OpenDHT keeps *every* value put under a key (it does not overwrite), which
lets a key behave like an append-only mailbox or log.
"""

import datetime
import threading
import time
from typing import Callable

import opendht as dht

from conf_chat.models import Envelope

# OpenDHT drops values after 10 minutes by default. Conf-Chat registers its
# own value type so messages survive for a week, which is what makes offline
# delivery work. Every peer must register the same type id.
CHAT_TYPE_ID = 0xC0C0
CHAT_TTL = datetime.timedelta(days=7)
CHAT_TYPE = dht.ValueType(CHAT_TYPE_ID, "conf-chat", CHAT_TTL)

PUT_TIMEOUT = 10.0


def parse_peer(peer: str) -> tuple[str, str]:
    """Split 'host:port' into (host, port)."""
    host, sep, port = peer.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise ValueError(f"expected host:port, got {peer!r}")
    return host, port


def key(name: str) -> dht.InfoHash:
    return dht.InfoHash.get(name)


class Node:
    """One Conf-Chat peer in the DHT."""

    def __init__(self, port: int = 0):
        self.port = port
        self.runner = dht.DhtRunner()
        self._permanent: dict[str, list] = {}

    def start(self, bootstrap: str | None = None, discover: bool = True, wait: float = 3.0) -> bool:
        """Start the node and join the network.

        Peers on the same local network find each other automatically
        (OpenDHT peer discovery over multicast), so no address is needed.
        `bootstrap` (host:port of any running peer) is only needed to reach
        peers on another network, or where multicast is blocked.
        Returns True once at least one other peer is known.
        """
        config = dht.DhtConfig()
        config.setPeerDiscovery(discover, discover)  # find peers on the LAN, and be findable
        self.runner.run(port=self.port, config=config)
        self.runner.registerType(CHAT_TYPE)
        if bootstrap:
            host, port = parse_peer(bootstrap)
            self.runner.bootstrap(host, port)
        return self.wait_connected(wait)

    def wait_connected(self, timeout: float) -> bool:
        """Block until at least one other peer is known (or timeout)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.connected_peers() > 0:
                return True
            time.sleep(0.1)
        return False

    def connected_peers(self) -> int:
        return self.runner.getNodesStats().good_nodes

    @property
    def node_id(self) -> str:
        return str(self.runner.getNodeId())

    @property
    def bound_port(self) -> int:
        return self.runner.getBound().getPort()

    def stop(self) -> None:
        self.runner.shutdown()
        self.runner.join()

    def put(self, name: str, env: Envelope, permanent: bool = False, ephemeral: bool = False,
            wait: bool = True) -> bool:
        """Store an envelope under `name`.

        permanent: keep re-announcing the value while this peer is running
        ephemeral: use OpenDHT's default 10-minute type (e.g. presence)
             wait: block until other peers acknowledge. Peers that left
                   without saying goodbye stay in routing tables for a while
                   and cost ~1s of timeouts per operation, so background
                   writes (heartbeats, index refreshes) pass wait=False.
                   Returns True if at least one other peer stored it.
        """
        value = dht.Value(env.to_bytes())
        if not ephemeral:
            value.type = CHAT_TYPE_ID
        done = threading.Event()
        result = {"ok": False}

        def on_done(ok, _nodes):
            result["ok"] = ok
            done.set()

        self.runner.put(key(name), value, done_cb=on_done, permanent=permanent)
        if permanent:
            self._permanent.setdefault(name, []).append(value)
        if not wait:
            return False
        done.wait(PUT_TIMEOUT)
        return result["ok"]

    def cancel_permanent(self, name: str) -> None:
        """Stop re-announcing values this peer put permanently under `name`."""
        for value in self._permanent.pop(name, []):
            self.runner.cancelPut(key(name), value)

    def get(self, name: str) -> list[Envelope]:
        """All valid envelopes currently stored under `name`, oldest first."""
        return sorted(_decode_all(self.runner.get(key(name))), key=lambda e: e.ts)

    def listen(self, name: str, callback: Callable[[Envelope], None]):
        """Call `callback` for every value under `name`: first the existing
        ones, then each new one as it is published. Runs on an OpenDHT
        thread, so callbacks must not block or call back into the DHT."""

        def on_value(value, expired):
            if not expired:
                env = _decode(value)
                if env is not None:
                    callback(env)
            return True  # keep listening

        return self.runner.listen(key(name), on_value)

    def cancel_listen(self, token) -> None:
        self.runner.cancelListen(token)


def _decode(value) -> Envelope | None:
    try:
        return Envelope.from_bytes(value.data)
    except (ValueError, UnicodeDecodeError):
        return None  # not a Conf-Chat value; ignore


def _decode_all(values) -> list[Envelope]:
    return [e for e in (_decode(v) for v in values) if e is not None]
