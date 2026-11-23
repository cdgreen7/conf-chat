# conf-chat

Conf-Chat is a simple two-way and many-to-many chat system built on a P2P architecture. 

## Use case

Conf-Chat follows the following use case:

- **Accounts.** A user registers with a username, password and full name,
  then joins by logging in with their username and password. Users can
  change their password.
- **Friends.** After logging in, a user can see which of their friends are
  online. They find new friends by searching with names: every word given
  must appear in the other user's full name. A friend request must be
  authorized by the other user, and then both become friends.
- **Direct messages.** A user can message any friend. An online friend gets
  the message at once. An offline friend gets it the next time they log in,
  even if the sender is no longer online.
- **Conferences.** A user can create a conference chat, and messages sent to
  it go to every participant. Any participant can add other participants at
  any time. Users cannot join a conference unless a participant adds them.
  A user who leaves the system automatically leaves their conferences and
  gets no further messages from them after logging in again, unless they are
  invited back.
- **Pure P2P.** No centralized server. Peers can be added or removed at any
  time without reconfiguring the system: a new peer only needs the address
  of any peer that is already running.

## P2P framework

Conf-Chat uses [OpenDHT](https://github.com/savoirfairelinux/opendht), a
Kademlia distributed hash table, through its official Python bindings.

## Installation

Official guides:
- uv (Python package manager): https://docs.astral.sh/uv/getting-started/installation/
- OpenDHT: https://github.com/savoirfairelinux/opendht/wiki/Build-the-library

The installation differs from the OpenDHT guide, which builds the library
from source. Instead, uv installs the prebuilt `opendht` package (Python
bindings included) from PyPI:

```bash
# 1. Install uv (macOS/Linux; see the uv guide for Windows)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone this fork
git clone https://github.com/cdgreen7/conf-chat.git
cd conf-chat

# 3. Install Python 3.13+ (if missing) and the dependencies from uv.lock
uv sync
```

Prebuilt `opendht` packages exist for Linux (x86_64, aarch64), Windows
(x86_64) and macOS 15+ (Apple Silicon). On other platforms, follow the
OpenDHT build guide first.

## Running

Start a peer in each terminal (or on each machine):

```bash
uv run conf-chat
```

Peers on the same local network find each other automatically, so no
addresses or configuration are needed. The first peer simply waits for
others, and peers can join or leave at any time.

If peers are on different networks, or the network blocks multicast (some
campus Wi-Fi does), point a new peer at any running peer instead:

```bash
uv run conf-chat --port 4222                             # a peer with a known port
uv run conf-chat --bootstrap <that-peer's-ip>:4222       # join through it
```

| Option | Meaning |
|---|---|
| `--port N` | UDP port for this peer (default: any free port) |
| `--bootstrap HOST:PORT` | join through a specific running peer |
| `--no-discovery` | don't look for peers on the local network |
