"""User accounts stored in the DHT.

Key `user:<username>` holds one `user` envelope per registration or password
change; the newest one (highest ts) is the current record. Passwords are
never stored, only a salted scrypt hash.
"""

import hashlib
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
