from __future__ import annotations

import sys
from typing import Any, TextIO

from .callbacks import ResultCallback
from .models import AccountRegionResult, AccountResult, ExecutionPhase


def show_progress(
    *,
    file: TextIO | None = None,
    disable: bool | None = None,
) -> ResultCallback[object]:
    """Return an ``on_result`` callback that rewrites one status line.

    The line is written to stderr when that stream is a TTY. Piped output,
    CI, and Lambda stay silent unless ``disable`` is set explicitly. The
    destination stream and its TTY detection are resolved when the first
    result arrives, so ``stderr`` redirection still applies. Streams without
    an ``isatty`` method count as non-TTY. This is not a progress-bar library:
    callers who want tqdm or rich can pass their own ``on_result`` instead.
    """

    if disable is not None and not isinstance(disable, bool):
        raise TypeError("disable must be a bool or None")
    ok = 0
    auth = 0
    worker = 0
    width = 0
    hidden = disable

    def on_result(result: Any, *, completed: int, total: int) -> None:
        nonlocal ok, auth, worker, width, hidden
        if getattr(result, "success", False):
            ok += 1
        elif getattr(result, "phase", None) is ExecutionPhase.AUTH:
            auth += 1
        else:
            worker += 1
        stream = sys.stderr if file is None else file
        if hidden is None:
            hidden = not _is_tty(stream)
        if hidden:
            return

        label = _target_label(result)
        line = (
            f"runacross  {completed}/{total}  ok {ok}  auth {auth}  "
            f"worker {worker}  {label}"
        )
        padding = max(0, width - len(line))
        width = len(line)
        stream.write(f"\r{line}{' ' * padding}")
        stream.flush()
        if completed >= total:
            stream.write("\n")
            stream.flush()

    return on_result


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    return bool(isatty())


def _target_label(result: AccountResult[Any] | AccountRegionResult[Any] | Any) -> str:
    account = getattr(result, "account", None)
    account_id = getattr(account, "id", None)
    if not isinstance(account_id, str):
        return "-"
    region = getattr(result, "region", None)
    if isinstance(region, str) and region:
        return f"{account_id} {region}"
    return account_id
