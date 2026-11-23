"""Finding other users by name, and seeing who is online.

Search index: for every word in a user's full name we put an entry under
`name:<word>`, so a query only has to visit one key per word instead of
scanning every user (a DHT has no "list all keys").
"""

import re
import time

from conf_chat.auth import User
from conf_chat.models import make

WORD_RE = re.compile(r"[a-z0-9]+")

# Presence: each online client puts a heartbeat under presence:<user> every
# HEARTBEAT seconds (with OpenDHT's default short expiry). A user counts as
# online if their newest heartbeat says so and is younger than PRESENCE_TIMEOUT,
# which also covers clients that crash without saying goodbye.
HEARTBEAT = 30.0
PRESENCE_TIMEOUT = 90.0


def name_words(text: str) -> set[str]:
    return set(WORD_RE.findall(text.lower()))


def index_name(node, user: User) -> None:
    """Publish (and keep re-announcing while online) the name index entries."""
    for word in name_words(user.full_name):
        node.put(f"name:{word}", make("name_index", user.username, full_name=user.full_name),
                 permanent=True, wait=False)


def search(node, query: str) -> list[User]:
    """Users whose full name contains every word of `query`."""
    words = name_words(query)
    if not words:
        return []
    found: dict[str, str] = {}
    for word in words:
        for env in node.get(f"name:{word}"):
            if env.type == "name_index" and words <= name_words(env["full_name"]):
                found[env.sender] = env["full_name"]
    return [User(u, n) for u, n in sorted(found.items())]


def presence_key(username: str) -> str:
    return f"presence:{username}"


def is_online(env, now: float | None = None) -> bool:
    """Interpret the newest presence envelope for a user."""
    if env is None or not env.get("online"):
        return False
    return (now or time.time()) - env.ts < PRESENCE_TIMEOUT


def latest_presence(node, username: str):
    envs = [e for e in node.get(presence_key(username)) if e.type == "presence" and e.sender == username]
    return max(envs, key=lambda e: e.ts) if envs else None
