import argparse
import time

from conf_chat.cli import Shell
from conf_chat.dht import Node


def parse_args():
    p = argparse.ArgumentParser(description="Conf-Chat: P2P chat on OpenDHT")
    p.add_argument("--port", type=int, default=0,
                   help="UDP port for this peer (default: any free port)")
    p.add_argument("--bootstrap", metavar="HOST:PORT",
                   help="address of a running peer; only needed if peers are on another "
                        "network (peers on the same network are found automatically)")
    p.add_argument("--no-discovery", action="store_true",
                   help="don't look for peers on the local network")
    p.add_argument("--data-dir", default=".confchat",
                   help="where each user's local state is kept (default ./.confchat)")
    p.add_argument("--seed", action="store_true",
                   help="run a headless peer with no user, which keeps storing and serving "
                        "messages while users are offline")
    return p.parse_args()


def run_seed() -> None:
    print("Running as a headless seed peer. Ctrl-C to stop.")
    while True:
        time.sleep(1)


def main():
    args = parse_args()
    node = Node(args.port)
    print("Joining the Conf-Chat network...")
    if node.start(args.bootstrap, discover=not args.no_discovery):
        print(f"Connected: {node.connected_peers()} peer(s) found")
    else:
        print("No other peers found yet; you are the first peer (others will find you).")
    shell = Shell(node, args.data_dir)
    try:
        if args.seed:
            run_seed()
        else:
            shell.run()
    except KeyboardInterrupt:
        print()
    finally:
        shell.close()
        node.stop()


if __name__ == "__main__":
    main()
