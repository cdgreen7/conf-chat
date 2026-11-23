"""A logged-in user's session on this peer."""

from typing import Callable

from conf_chat.auth import User


class Client:
    def __init__(self, node, user: User, out: Callable[[str], None] = print):
        self.node = node
        self.user = user
        self.out = out

    @property
    def me(self) -> str:
        return self.user.username

    def start(self) -> "Client":
        return self

    def close(self) -> None:
        """Log out."""
