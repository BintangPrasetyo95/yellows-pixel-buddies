"""Slash-command routing (REVIEW M24, plan 8.3).

``_on_chat_submitted`` used to hold ~45 commands as one ~420-line if/elif chain. Commands are now an ordered table
of (matcher, handler method). Semantics are exactly the old chain's: the FIRST command whose matcher accepts the
input is the only one considered; its handler returns True if it handled the input, or False to let the message
continue to normal chat (e.g. "/fact " with nothing after it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

Matcher = Callable[[str, str], bool]   # (clean_input, lower_input) -> bool


@dataclass(frozen=True)
class Command:
    name: str
    matches: Matcher
    handler: str          # method name on the owner: handler(clean_input, lower_input) -> bool


def exact(*names: str) -> Matcher:
    wanted = frozenset(names)
    return lambda _clean, lower: lower in wanted


def prefix(*prefixes: str) -> Matcher:
    return lambda _clean, lower: lower.startswith(prefixes)


class CommandRouter:
    def __init__(self, commands: Iterable[Command]) -> None:
        self.commands: tuple[Command, ...] = tuple(commands)
        names = [c.name for c in self.commands]
        if len(names) != len(set(names)):
            raise ValueError("duplicate command names")

    def match(self, clean_input: str, lower_input: str) -> Optional[Command]:
        for cmd in self.commands:
            if cmd.matches(clean_input, lower_input):
                return cmd
        return None

    def dispatch(self, owner: Any, clean_input: str, lower_input: str) -> bool:
        """Run the first matching command on ``owner``. True = handled (stop), False = continue to chat."""
        cmd = self.match(clean_input, lower_input)
        if cmd is None:
            return False
        return bool(getattr(owner, cmd.handler)(clean_input, lower_input))
