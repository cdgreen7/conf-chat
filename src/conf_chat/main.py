import argparse
import time

from conf_chat.dht import Node


def parse_args():
    p = argparse.ArgumentParser(description="Conf-Chat: P2P chat on OpenDHT")
    p.add_argument("--port", type=int, default=4222, help="UDP port for this node (default 4222)")
    p.add_argument("--bootstrap", metavar="HOST:PORT", help="any existing Conf-Chat node to join through")
    return p.parse_args()


def main():
    args = parse_args()
    node = Node(args.port)
    node.start(args.bootstrap)
    print(f"Node {node.node_id} listening on UDP {node.bound_port}")
    if args.bootstrap:
        print(f"Bootstrapped via {args.bootstrap}: {node.connected_peers()} peer(s) known")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()