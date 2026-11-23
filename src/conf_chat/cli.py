"""Interactive command shell.

Joining Conf-Chat is done with an account: the shell starts by asking the
user to log in or register, and only then accepts chat commands. Logging
out returns to that prompt.
"""

import cmd
import functools
import getpass
import sys
import threading

from conf_chat import auth
from conf_chat.client import Client
from conf_chat.dht import Node

_print_lock = threading.Lock()


def needs_login(method):
    @functools.wraps(method)
    def wrapper(self, line):
        if self.client is None:
            print("log in first")
            return None
        return method(self, line)
    return wrapper


class Shell(cmd.Cmd):
    prompt = "> "

    def __init__(self, node: Node):
        super().__init__()
        self.node = node
        self.client: Client | None = None
        self.quitting = False
        self.at_prompt = False  # True while cmd is waiting for input

    def run(self) -> None:
        """Ask for an account, run commands until logout, repeat until quit."""
        print("Welcome to Conf-Chat.")
        while not self.quitting:
            if not self.welcome():
                break
            print("Type 'help' for commands.")
            self.cmdloop()

    def welcome(self) -> bool:
        """Log in or register. Returns False if the user wants to quit."""
        while True:
            try:
                choice = input("login, register or quit? ").strip().lower()
            except EOFError:
                print()
                return False
            if choice in ("l", "login") and self.login():
                return True
            if choice in ("r", "register") and self.register():
                return True
            if choice in ("q", "quit", "exit"):
                return False

    def login(self) -> bool:
        username = input("Username: ").strip()
        try:
            user = auth.login(self.node, username, getpass.getpass("Password: "))
        except auth.AuthError as e:
            print(e)
            return False
        self.start_session(user)
        return True

    def register(self) -> bool:
        username = input("Username: ").strip()
        full_name = input("Full name: ")
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            print("passwords do not match")
            return False
        try:
            auth.register(self.node, username, full_name, password)
            user = auth.login(self.node, username, password)
        except auth.AuthError as e:
            print(e)
            return False
        self.start_session(user)
        return True

    def start_session(self, user: auth.User) -> None:
        self.prompt = f"{user.username}> "
        print(f"Welcome, {user.full_name}!")
        self.client = Client(self.node, user, out=self.notify).start()

    def close(self) -> None:
        """Log out if needed (called when the program exits)."""
        if self.client:
            self.client.close()
            self.client = None
            self.prompt = "> "

    def notify(self, text: str) -> None:
        """Print a line from a background thread without wrecking the prompt."""
        with _print_lock:
            if sys.stdout.isatty():
                clear = "\r\x1b[K"  # wipe the half-drawn prompt
            else:
                clear = "\n" if self.at_prompt else ""
            sys.stdout.write(f"{clear}{text}\n" + (self.prompt if self.at_prompt else ""))
            sys.stdout.flush()

    @staticmethod
    def args(line: str, n: int, usage: str) -> list[str] | None:
        """Split `line` into exactly n args; the last one keeps its spaces."""
        parts = line.split(maxsplit=n - 1)
        if len(parts) != n:
            print(f"usage: {usage}")
            return None
        return parts

    def preloop(self):
        self.at_prompt = True

    def precmd(self, line):
        self.at_prompt = False
        return line

    def postcmd(self, stop, line):
        self.at_prompt = True
        return stop

    def get_names(self):
        return [n for n in super().get_names() if n != "do_EOF"]  # hide EOF from help

    def emptyline(self):
        pass  # don't repeat the last command on Enter

    def default(self, line):
        print(f"unknown command: {line.split()[0]} (try 'help')")

    def do_status(self, _):
        """status -- show this peer's id, port and number of known peers"""
        print(f"peer {self.node.node_id}  port {self.node.bound_port}  "
              f"peers {self.node.connected_peers()}")

    @needs_login
    def do_passwd(self, _):
        """passwd -- change your password"""
        old = getpass.getpass("Current password: ")
        new = getpass.getpass("New password: ")
        if getpass.getpass("Repeat new password: ") != new:
            print("passwords do not match")
            return
        try:
            auth.change_password(self.node, self.client.user, old, new)
        except auth.AuthError as e:
            print(e)
            return
        print("Password changed.")

    @needs_login
    def do_logout(self, _):
        """logout -- log out of Conf-Chat"""
        self.close()
        print("Logged out.")
        return True  # back to the login/register prompt

    def do_quit(self, _):
        """quit -- log out and leave Conf-Chat"""
        self.close()
        self.quitting = True
        return True

    do_exit = do_quit
    do_EOF = do_quit
