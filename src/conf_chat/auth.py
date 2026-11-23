"""User accounts stored in the DHT.

Key `user:<username>` holds one `user` envelope per registration or password
change; the newest one (highest ts) is the current record. Passwords are
never stored, only a salted scrypt hash.
"""

import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from conf_chat.models import Envelope, make

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
MIN_PASSWORD = 4


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class User:
    username: str
    full_name: str


def user_key(username: str) -> str:
    return f"user:{username}"


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def lookup(node, username: str) -> Envelope | None:
    """Newest account record for `username`, or None if unregistered."""
    records = [e for e in node.get(user_key(username)) if e.type == "user" and e.sender == username]
    return max(records, key=lambda e: e.ts) if records else None


def _record(username: str, full_name: str, password: str) -> Envelope:
    salt = os.urandom(16)
    return make("user", username, full_name=full_name, salt=salt.hex(),
                pw_hash=hash_password(password, salt))


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"password must be at least {MIN_PASSWORD} characters")


def register(node, username: str, full_name: str, password: str) -> User:
    username = username.lower()
    full_name = " ".join(full_name.split())
    if not USERNAME_RE.match(username):
        raise AuthError("username must be 3-20 characters: a-z, 0-9, _")
    if not full_name:
        raise AuthError("full name is required")
    _check_password(password)
    if lookup(node, username) is not None:
        raise AuthError(f"username '{username}' is already taken")
    node.put(user_key(username), _record(username, full_name, password), permanent=True)
    return User(username, full_name)


def _verify(record: Envelope, password: str) -> bool:
    expected = hash_password(password, bytes.fromhex(record["salt"]))
    return hmac.compare_digest(expected, record["pw_hash"])


def login(node, username: str, password: str) -> User:
    username = username.lower()
    record = lookup(node, username)
    if record is None or not _verify(record, password):
        raise AuthError("wrong username or password")
    # Re-announce our account record from this peer while we are online so
    # it stays in the DHT even if the peer that registered it is gone.
    node.put(user_key(username), record, permanent=True, wait=False)
    return User(username, record["full_name"])


def change_password(node, user: User, old_password: str, new_password: str) -> None:
    """Publish a new account record; the newest record wins on lookup."""
    record = lookup(node, user.username)
    if record is None or not _verify(record, old_password):
        raise AuthError("current password is wrong")
    _check_password(new_password)
    node.cancel_permanent(user_key(user.username))  # stop re-announcing the old hash
    node.put(user_key(user.username), _record(user.username, user.full_name, new_password),
             permanent=True)
