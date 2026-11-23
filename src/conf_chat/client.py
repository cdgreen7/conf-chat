"""A logged-in user's session on this peer.

Everything addressed to a user goes into their DHT mailbox `inbox:<user>`.
On login the client replays the mailbox in timestamp order, then listens
for new values. OpenDHT invokes listen callbacks on its own thread, which
must not block or call back into the DHT, so callbacks only enqueue
envelopes; a worker thread handles them (and may use the DHT freely).
"""

import queue
import threading
import time
from typing import Callable

from conf_chat import auth, friends
from conf_chat.auth import User
from conf_chat.models import Envelope, make


class ChatError(Exception):
    pass


def inbox(username: str) -> str:
    return f"inbox:{username}"


class Client:
    def __init__(self, node, user: User, out: Callable[[str], None] = print):
        self.node = node
        self.user = user
        self.out = out
        self.login_ts = time.time()
        self.lock = threading.RLock()
        self.seen: set[str] = set()
        self.friends: set[str] = set()
        self.pending: dict[str, str] = {}  # incoming requests: username -> full name
        self.outgoing: set[str] = set()  # usernames we sent requests to
        self.presence: dict[str, Envelope] = {}  # friend -> newest presence envelope
        self._stopping = threading.Event()
        self._heartbeat = threading.Thread(target=self._beat, name="conf-chat-presence", daemon=True)
        self._events: queue.Queue = queue.Queue()
        self._listens: dict[str, object] = {}
        self._handlers: dict[str, Callable[[Envelope], None]] = {
            "friend_request": self._on_friend_request,
            "friend_accept": self._on_friend_accept,
            "friend_deny": self._on_friend_deny,
        }
        self._worker = threading.Thread(target=self._run, name="conf-chat-events", daemon=True)

    @property
    def me(self) -> str:
        return self.user.username

    def start(self) -> "Client":
        friends.index_name(self.node, self.user)  # keep our search entries alive while online
        self._worker.start()
        self.subscribe(inbox(self.me))
        self._announce(online=True)
        self._heartbeat.start()
        return self

    def close(self) -> None:
        """Log out: announce we are offline, stop listening, stop the worker."""
        self._stopping.set()
        self._heartbeat.join(timeout=5)
        self._announce(online=False)
        for token in list(self._listens.values()):
            self.node.cancel_listen(token)
        self._listens.clear()
        self._events.put(None)
        self._worker.join(timeout=5)

    def sync(self) -> None:
        """Wait until every queued event has been handled."""
        self._events.join()

    def subscribe(self, name: str) -> None:
        """Replay `name` in timestamp order, then follow new values."""
        if name in self._listens:
            return
        for env in self.node.get(name):
            self._events.put(env)
        self._listens[name] = self.node.listen(name, self._events.put)

    def unsubscribe(self, name: str) -> None:
        token = self._listens.pop(name, None)
        if token is not None:
            self.node.cancel_listen(token)

    def _run(self) -> None:
        while True:
            env = self._events.get()
            try:
                if env is None:
                    return
                self._handle(env)
            except Exception as e:  # never let one bad value kill the session
                self.out(f"! error handling {env.type}: {e}")
            finally:
                self._events.task_done()

    def _handle(self, env: Envelope) -> None:
        with self.lock:
            if env.type == "presence":  # frequent and idempotent: not de-duplicated
                self._on_presence(env)
                return
            if env.id in self.seen:  # OpenDHT may deliver a value more than once
                return
            self.seen.add(env.id)
            handler = self._handlers.get(env.type)
            if handler:
                handler(env)

    def _deliver(self, to: str, env: Envelope) -> None:
        self.node.put(inbox(to), env)

    def _record(self, env: Envelope) -> None:
        """Put an event in our own inbox (so it is replayed on next login) and
        apply it now rather than waiting for it to come back over the DHT."""
        self._deliver(self.me, env)
        self._events.put(env)

    def request_friend(self, username: str) -> None:
        username = username.lower()
        if username == self.me:
            raise ChatError("you can't befriend yourself")
        if username in self.friends:
            raise ChatError(f"{username} is already your friend")
        if auth.lookup(self.node, username) is None:
            raise ChatError(f"no such user: {username}")
        env = make("friend_request", self.me, to=username, full_name=self.user.full_name)
        self._deliver(username, env)
        self._record(env)  # our own copy, so we remember we asked

    def _add_friend(self, username: str) -> None:
        self.friends.add(username)
        self.subscribe(friends.presence_key(username))  # get told when they come and go

    def _on_friend_request(self, env: Envelope) -> None:
        if env.sender == self.me:
            self.outgoing.add(env["to"])
        elif env["to"] == self.me and env.sender not in self.friends:
            self.pending[env.sender] = env.get("full_name", "")
            self.out(f"* friend request from {env.sender} ({env.get('full_name', '')}): "
                     f"'accept {env.sender}' or 'deny {env.sender}'")

    def accept_friend(self, username: str) -> None:
        username = username.lower()
        with self.lock:
            if username not in self.pending:
                raise ChatError(f"no friend request from {username}")
        env = make("friend_accept", self.me, to=username)
        self._deliver(username, env)
        self._record(env)

    def deny_friend(self, username: str) -> None:
        username = username.lower()
        with self.lock:
            if username not in self.pending:
                raise ChatError(f"no friend request from {username}")
        # Only recorded in our own inbox: the requester is not told.
        self._record(make("friend_deny", self.me, to=username))

    def _on_friend_accept(self, env: Envelope) -> None:
        if env.sender == self.me:  # we accepted someone
            other = env["to"]
            self.pending.pop(other, None)
            self._add_friend(other)
            self.out(f"* you are now friends with {other}")
        elif env["to"] == self.me and env.sender in self.outgoing:  # they accepted us
            self.outgoing.discard(env.sender)
            self._add_friend(env.sender)
            self.out(f"* {env.sender} accepted your friend request")

    def _on_friend_deny(self, env: Envelope) -> None:
        if env.sender == self.me:
            self.pending.pop(env["to"], None)

    def _announce(self, online: bool) -> None:
        # Heartbeats don't wait for acknowledgement; the goodbye does, so it
        # is sent before this peer shuts down.
        self.node.put(friends.presence_key(self.me), make("presence", self.me, online=online),
                      ephemeral=True, wait=not online)

    def _beat(self) -> None:
        while not self._stopping.wait(friends.HEARTBEAT):
            self._announce(online=True)

    def _on_presence(self, env: Envelope) -> None:
        who = env.sender
        if who not in self.friends:
            return
        old = self.presence.get(who)
        if old is not None and old.ts >= env.ts:
            return  # stale or duplicate heartbeat
        was, now = friends.is_online(old), friends.is_online(env)
        self.presence[who] = env
        if was != now and env.ts > self.login_ts:
            self.out(f"* {who} is now {'online' if now else 'offline'}")

    def friend_status(self) -> dict[str, bool]:
        """Friend -> online? Asks the DHT, so it is accurate even if a friend
        crashed without saying goodbye."""
        with self.lock:
            names = sorted(self.friends)
        return {f: friends.is_online(friends.latest_presence(self.node, f)) for f in names}
