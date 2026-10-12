"""Running user commands portably."""

from __future__ import annotations

import os
import shlex


def split_cmd(cmd: str) -> list[str] | str:
    """POSIX: shell-style split. Windows: pass the string to CreateProcess, which parses its own
    quoting (shlex would eat the backslashes in C:\\ paths)."""
    if os.name == "nt":
        return cmd
    return shlex.split(cmd)
