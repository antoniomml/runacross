"""Typed result observers and internal synchronous callback validation."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import partial
from typing import Protocol, TypeVar

ResultT_contra = TypeVar("ResultT_contra", contravariant=True)


class ResultCallback(Protocol[ResultT_contra]):
    """An observer called serially on the thread running the executor.

    ``result`` is positional; ``completed`` and ``total`` are keyword-only.
    Observers must be synchronous and should return ``None``.
    """

    def __call__(
        self, result: ResultT_contra, /, *, completed: int, total: int
    ) -> None: ...


def _validate_callback(
    callback: object, *, label: str, positional: int, progress: bool = False
) -> None:
    if not callable(callback):
        raise TypeError(f"{label} must be callable")
    target: Callable[..., object] = callback
    while isinstance(target, partial):
        target = target.func
    # Callability is already validated; inspect the implementation for async.
    call_method = getattr(target, "__call__", None)  # noqa: B004
    if any(
        inspect.iscoroutinefunction(candidate) or inspect.isasyncgenfunction(candidate)
        for candidate in (target, call_method)
    ):
        raise TypeError(
            f"{label} must be synchronous; async callbacks are not supported"
        )
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        # Some extension/builtin callables have no inspectable signature.
        # Their invocation errors retain the normal per-target semantics.
        return
    kwargs = {"completed": 1, "total": 1} if progress else {}
    try:
        signature.bind(*([None] * positional), **kwargs)
    except TypeError as error:
        suffix = " and completed=..., total=..." if progress else ""
        raise TypeError(
            f"{label} must accept {positional} positional arguments{suffix}"
        ) from error


def _validate_callback_value(value: object, *, label: str) -> None:
    if inspect.isawaitable(value) or inspect.isasyncgen(value):
        # Close a native coroutine we will never await, avoiding a leaked
        # coroutine warning. Do not run event loops or cancel caller-owned tasks.
        if inspect.iscoroutine(value):
            value.close()
        raise TypeError(
            f"{label} returned an asynchronous value; callbacks must be synchronous"
        )
