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
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from conf_chat import auth, friends
from conf_chat.auth import User
from conf_chat.models import Envelope, make
from conf_chat.store import Store


class ChatError(Exception):
    pass


def inbox(username: str) -> str:
    return f"inbox:{username}"


def conf_key(conf_id: str) -> str:
    return f"conf:{conf_id}"


@dataclass
class Conference:
    """State rebuilt by replaying the conference log `conf:<id>` in order.

    Membership is decided by the log itself: a member can only be added by
    someone who is already a member at that point in the log, so peers can
    reject forged entries without any central authority."""
    id: str
    name: str = "?"
    creator: str | None = None
    members: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    replaying: bool = True
    added_by: str | None = None  # who (most recently) added us
    backlog: list = field(default_factory=list)  # unseen messages found while replaying


class Client:
    def __init__(self, node, user: User, out: Callable[[str], None] = print,
                 store: Store | None = None):
        self.node = node
        self.user = user
        self.out = out
        self.store = store or Store(None)
        self.login_ts = time.time()
        self.lock = threading.RLock()
        self.seen: set[str] = set()
        self.friends: set[str] = set()
        self.pending: dict[str, str] = {}  # incoming requests: username -> full name
        self.outgoing: set[str] = set()  # usernames we sent requests to
        self.presence: dict[str, Envelope] = {}  # friend -> newest presence envelope
        self.confs: dict[str, Conference] = {}  # conferences we are in
        self._stopping = threading.Event()
        self._heartbeat = threading.Thread(target=self._beat, name="conf-chat-presence", daemon=True)
        self._events: queue.Queue = queue.Queue()
        self._listens: dict[str, object] = {}
        self._handlers: dict[str, Callable[[Envelope], None]] = {
            "friend_request": self._on_friend_request,
            "friend_accept": self._on_friend_accept,
            "friend_deny": self._on_friend_deny,
            "dm": self._on_dm,
            "conf_invite": self._on_conf_invite,
        }
        self._worker = threading.Thread(target=self._run, name="conf-chat-events", daemon=True)

    @property
    def me(self) -> str:
        return self.user.username

    def start(self) -> "Client":
        friends.index_name(self.node, self.user)  # keep our search entries alive while online
        self._load()
        self._worker.start()
        self.subscribe(inbox(self.me))
        self._announce(online=True)
        self._heartbeat.start()
        return self

    def close(self) -> None:
        """Log out: leave every conference (leaving the system means leaving
        its conferences), announce we are offline, stop listening."""
        for conf_id in list(self.confs):
            self.leave_conf(conf_id)
        self._stopping.set()
        self._heartbeat.join(timeout=5)
        self._announce(online=False)
        for token in list(self._listens.values()):
            self.node.cancel_listen(token)
        self._listens.clear()
        self._events.put(None)
        self._worker.join(timeout=5)
        self._save()

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
                if self._events.qsize() == 0:
                    self._save()  # batch saves: only once the queue is drained
            except Exception as e:  # never let one bad value kill the session
                self.out(f"! error handling {env.type}: {e}")
            finally:
                self._events.task_done()

    def _handle(self, env: Envelope) -> None:
        with self.lock:
            if env.type == "presence":  # frequent and idempotent: not de-duplicated
                self._on_presence(env)
                return
            if env.type.startswith("conf_") and env.type != "conf_invite":
                self._on_conf_event(env)  # de-duplicated per conference, see _join_conf
                return
            if env.id in self.seen:  # OpenDHT may deliver a value more than once
                return
            self.seen.add(env.id)
            handler = self._handlers.get(env.type)
            if handler:
                handler(env)

    def _load(self) -> None:
        state = self.store.load()
        with self.lock:
            self.seen.update(state.get("seen", []))
            self.outgoing.update(state.get("outgoing", []))
            self.pending.update(state.get("pending", {}))
            for name in state.get("friends", []):
                self._add_friend(name)
            # Normally empty (logout leaves all conferences); non-empty only if
            # the previous session crashed, in which case we are still a member.
            for conf_id in state.get("confs", []):
                self._join_conf(conf_id, announce=False)

    def _save(self) -> None:
        with self.lock:
            state = {"seen": sorted(self.seen), "friends": sorted(self.friends),
                     "outgoing": sorted(self.outgoing), "pending": dict(self.pending),
                     "confs": sorted(self.confs)}
        self.store.save(state)

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

    def send_message(self, to: str, text: str) -> None:
        to = to.lower()
        if to not in self.friends:
            raise ChatError(f"{to} is not your friend")
        if not text.strip():
            raise ChatError("empty message")
        self._deliver(to, make("dm", self.me, to=to, text=text))

    def _on_dm(self, env: Envelope) -> None:
        if env["to"] != self.me or env.sender not in self.friends:
            return  # only friends can message us
        self.out(f"[{env.sender}]{self._when(env)} {env['text']}")

    def _when(self, env: Envelope) -> str:
        """Timestamp label for messages that arrived while we were offline."""
        if env.ts >= self.login_ts:
            return ""
        return f" ({datetime.fromtimestamp(env.ts):%b %d %H:%M}, while you were offline)"

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

    def create_conf(self, name: str) -> Conference:
        name = name.strip()
        if not name:
            raise ChatError("conference needs a name")
        conf_id = uuid.uuid4().hex[:6]
        self.node.put(conf_key(conf_id), make("conf_create", self.me, conf=conf_id, name=name))
        with self.lock:
            return self._join_conf(conf_id)

    def find_conf(self, ref: str) -> Conference:
        """Look a conference up by id or (unique) name."""
        with self.lock:
            if ref in self.confs:
                return self.confs[ref]
            matches = [c for c in self.confs.values() if c.name.lower() == ref.lower()]
        if len(matches) == 1:
            return matches[0]
        raise ChatError(f"no conference '{ref}'" if not matches else
                        f"several conferences are called '{ref}'; use the id")

    def _join_conf(self, conf_id: str, announce: bool = True) -> Conference | None:
        """Replay a conference log; keep following it only if we are a member.
        Caller holds self.lock."""
        if conf_id in self.confs:
            return self.confs[conf_id]
        conf = self.confs[conf_id] = Conference(conf_id)
        for env in self.node.get(conf_key(conf_id)):
            self._on_conf_event(env)
        conf.replaying = False
        if self.me not in conf.members:
            del self.confs[conf_id]  # e.g. an old invite from before we left
            return None
        self.subscribe(conf_key(conf_id))
        if announce and conf.added_by and conf.added_by != self.me:
            self.out(f"* {conf.added_by} added you to conference #{conf.name} [{conf.id}] "
                     f"with {', '.join(sorted(conf.members - {self.me}))}")
        for env in conf.backlog:  # messages sent while we were a member but offline
            self._show_conf_msg(conf, env)
        conf.backlog.clear()
        return conf

    def say(self, ref: str, text: str) -> None:
        conf = self.find_conf(ref)
        if not text.strip():
            raise ChatError("empty message")
        env = make("conf_msg", self.me, conf=conf.id, text=text)
        self.node.put(conf_key(conf.id), env)
        self._events.put(env)

    def leave_conf(self, ref: str) -> None:
        conf = self.find_conf(ref)
        self.node.put(conf_key(conf.id), make("conf_leave", self.me, conf=conf.id))
        with self.lock:
            self.unsubscribe(conf_key(conf.id))
            self.confs.pop(conf.id, None)

    def _show_conf_msg(self, conf: Conference, env: Envelope) -> None:
        self.seen.add(env.id)  # saved locally, so it is never shown twice
        self.out(f"[#{conf.name}] {env.sender}{self._when(env)}: {env['text']}")

    def add_member(self, ref: str, username: str) -> None:
        conf = self.find_conf(ref)
        username = username.lower()
        with self.lock:
            if username in conf.members:
                raise ChatError(f"{username} is already in #{conf.name}")
            if username not in self.friends:
                raise ChatError(f"you can only add your friends ({username} is not one)")
        env = make("conf_add", self.me, conf=conf.id, member=username)
        self.node.put(conf_key(conf.id), env)  # first the log entry that grants membership...
        self._deliver(username, make("conf_invite", self.me, to=username, conf=conf.id,
                                     name=conf.name))  # ...then the notification
        self._events.put(env)

    def _on_conf_invite(self, env: Envelope) -> None:
        if env["to"] == self.me:
            self._join_conf(env["conf"])

    def _on_conf_event(self, env: Envelope) -> None:
        conf = self.confs.get(env.get("conf"))
        if conf is None or env.id in conf.seen:
            return
        conf.seen.add(env.id)
        if env.type == "conf_create" and conf.creator is None:
            conf.creator, conf.name = env.sender, env.get("name", "?")
            conf.members = {env.sender}
            conf.added_by = env.sender
        elif env.type == "conf_add" and env.sender in conf.members:  # only members may add
            member = env["member"]
            if member in conf.members:
                return
            conf.members.add(member)
            if member == self.me:
                conf.added_by = env.sender
            elif not conf.replaying:
                self.out(f"[#{conf.name}] {env.sender} added {member}")
        elif env.type == "conf_leave" and env.sender in conf.members:  # you can only remove yourself
            conf.members.discard(env.sender)
            if env.sender == self.me:
                conf.backlog.clear()  # anything before we left is not for us any more
            elif not conf.replaying:
                self.out(f"[#{conf.name}] {env.sender} left")
        elif env.type == "conf_msg" and env.sender in conf.members and self.me in conf.members:
            # Membership is checked as of this point in the log, so messages
            # from before we were (re-)added, or after we left, are never shown.
            if env.id in self.seen:
                return
            if conf.replaying:
                conf.backlog.append(env)
            else:
                self._show_conf_msg(conf, env)
