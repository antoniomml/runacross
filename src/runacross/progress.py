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
    CI, and Lambda stay silent unless ``disable`` is set explicitly. This is
    not a progress-bar library: callers who want tqdm or rich can pass their
    own ``on_result`` instead.
    """

    if disable is not None and not isinstance(disable, bool):
        raise TypeError("disable must be a bool or None")
    stream = sys.stderr if file is None else file
    hidden = (not stream.isatty()) if disable is None else disable
    ok = 0
    auth = 0
    worker = 0
    width = 0

    def on_result(result: Any, *, completed: int, total: int) -> None:
        nonlocal ok, auth, worker, width
        if getattr(result, "success", False):
            ok += 1
        elif getattr(result, "phase", None) is ExecutionPhase.AUTH:
            auth += 1
        else:
            worker += 1
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


def _target_label(result: AccountResult[Any] | AccountRegionResult[Any] | Any) -> str:
    account = getattr(result, "account", None)
    account_id = getattr(account, "id", None)
    if not isinstance(account_id, str):
        return "-"
    region = getattr(result, "region", None)
    if isinstance(region, str) and region:
        return f"{account_id} {region}"
    return account_id
