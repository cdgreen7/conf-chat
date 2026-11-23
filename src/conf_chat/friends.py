"""Finding other users by name.

Search index: for every word in a user's full name we put an entry under
`name:<word>`, so a query only has to visit one key per word instead of
scanning every user (a DHT has no "list all keys").
"""

import re

from conf_chat.auth import User
from conf_chat.models import make

WORD_RE = re.compile(r"[a-z0-9]+")


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
