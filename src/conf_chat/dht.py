import time

import opendht as dht


def parse_peer(peer: str) -> tuple[str, str]:
    """Split 'host:port' into (host, port)."""
    host, sep, port = peer.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise ValueError(f"expected host:port, got {peer!r}")
    return host, port


class Node:
    """One Conf-Chat peer in the DHT."""

    def __init__(self, port: int = 0):
        self.port = port
        self.runner = dht.DhtRunner()

    def start(self, bootstrap: str | None = None, wait: float = 5.0) -> None:
        """Start the node and optionally join the network through an existing peer."""
        self.runner.run(port=self.port)
        if bootstrap:
            host, port = parse_peer(bootstrap)
            self.runner.bootstrap(host, port)
            self.wait_connected(wait)

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