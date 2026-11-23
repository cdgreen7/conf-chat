# conf-chat

Conf-Chat is a simple two-way and many-to-many chat system built on a P2P architecture. 

## Use case

Conf-Chat implements the suggested use case, with these changes marked *(change)*:

- **Accounts.** A user registers with a username, password and full name,
  then joins by logging in with their username and password. Users can
  change their password.
- **Friends.** After logging in, a user can see which of their friends are
  online. They find new friends by searching with names: every word given
  must appear in the other user's full name. A friend request must be
  authorized by the other user, and then both become friends. A user can
  also deny a request *(change: silently, the requester is not told)*.
- **Direct messages.** A user can message any friend. An online friend gets
  the message at once. An offline friend gets it the next time they log in,
  even if the sender is no longer online, as long as at least one peer stays
  up to store it (any other user, or a `--seed` peer).
- **Conferences.** A user can create a conference chat, and messages sent to
  it go to every participant. Any participant can add other participants at
  any time *(change: only people who are their friends)*. Users cannot join
  a conference unless a participant adds them. A user who leaves the system
  automatically leaves their conferences and gets no further messages from
  them after logging in again, unless they are invited back.
- **Pure P2P.** No centralized server. Peers can be added or removed at any
  time without reconfiguring the system: peers on the same network find each
  other automatically, and `--bootstrap` can point a peer at any running
  peer on another network.

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

Each user then joins Conf-Chat with their account. The program asks:

```text
login, register or quit?
```

Registering asks for a username, full name and password, and logs you in.
Logging out returns to this prompt.

If peers are on different networks, or the network blocks multicast (some
campus Wi-Fi does), point a new peer at any running peer instead:

```bash
uv run conf-chat --port 4222                             # a peer with a known port
uv run conf-chat --bootstrap <that-peers-ip>:4222       # join through it
```

| Option | Meaning |
|---|---|
| `--port N` | UDP port for this peer (default: any free port) |
| `--bootstrap HOST:PORT` | join through a specific running peer |
| `--no-discovery` | don't look for peers on the local network |
| `--seed` | run a peer with no user, which keeps storing and serving messages while users are offline |
| `--data-dir DIR` | where each user's local state is kept (default `./.confchat`) |

Each user's local state (messages already shown, friends, pending
requests) is kept in `./.confchat/<username>.json` on their own machine, so
old messages are not shown again and friendships outlive the DHT's 7-day
expiry.

## Commands

| Command | |
|---|---|
| `search <words...>` | find users whose full name contains all the words |
| `request <username>` | send a friend request |
| `requests` | list friend requests waiting for you |
| `accept <username>` / `deny <username>` | answer a friend request |
| `friends` | list your friends, online ones first |
| `msg <friend> <text>` | direct message (delivered later if they are offline) |
| `conf <name>` | start a conference |
| `confs` | list your conferences and their members |
| `invite <conference> <friend>` | add a friend to a conference you are in |
| `say <conference> <text>` | message everyone in a conference |
| `leave <conference>` | leave a conference (you need a new invite to come back) |
| `passwd` | change your password |
| `status` | this peer's id, port and number of known peers |
| `logout` | log out (this also leaves all your conferences) |
| `quit` | log out and stop this peer |

`<conference>` is the id shown by `conf` and `confs` (e.g. `4f1a2c`), or its
name if no two of your conferences share it.
