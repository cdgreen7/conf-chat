"""Interactive command shell."""

import cmd
import sys
import threading

from conf_chat.dht import Node

_print_lock = threading.Lock()


class Shell(cmd.Cmd):
    intro = "Welcome to Conf-Chat. Type 'help' for commands."
    prompt = "> "

    def __init__(self, node: Node):
        super().__init__()
        self.node = node
        self.at_prompt = False  # True while cmd is waiting for input

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

    def do_quit(self, _):
        """quit -- leave Conf-Chat"""
        return True

    do_exit = do_quit
    do_EOF = do_quit
