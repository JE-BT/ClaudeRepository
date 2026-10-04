"""Colour for the terminal. Game text marks story hooks with [[main]]...[[/]] (gold) and
[[side]]...[[/]] (teal); goal changes use [[goal]] (gold, bold). The CLI renders the marks as ANSI
colours, or strips them with --no-color or when the terminal cannot show colour."""
from __future__ import annotations

import os
import re
import sys

CODES = {"main": "\x1b[38;5;178m", "side": "\x1b[38;5;37m", "goal": "\x1b[1;38;5;178m", "dim": "\x1b[2m", "/": "\x1b[0m"}
MARK = re.compile(r"\[\[(main|side|goal|dim|/)\]\]")


def mark(text: str, kind: str) -> str:
    return f"[[{kind}]]{text}[[/]]" if text else text


def strip(text: str) -> str:
    return MARK.sub("", text)


def enable() -> bool:
    """True if the terminal can show colour (turns on ANSI handling on Windows 10+)."""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            return False
    return True


def render(text: str, colour: bool) -> str:
    return MARK.sub(lambda m: CODES[m.group(1)], text) if colour else strip(text)
