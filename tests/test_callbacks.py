from __future__ import annotations

import asyncio
import inspect
from functools import partial, wraps
from typing import Any

import pytest

from runacross import ExecutionPhase, Profile, map_account_regions, map_accounts


class OfflineAuth:
    def bind(self, **_kwargs: Any) -> OfflineAuth:
        return self

    def session_for(self, _account: Any, **_kwargs: Any) -> object:
        return object()

    def identity(self, _account: Any) -> tuple[None, None]:
        return None, None


class UnusedAuth(OfflineAuth):
    def bind(self, **_kwargs: Any) -> OfflineAuth:
        pytest.fail("invalid callbacks must be rejected before authentication")


async def async_callback(*_args: Any, **_kwargs: Any) -> str:
    return "never executed"


async def async_generator(*_args: Any, **_kwargs: Any) -> Any:
    yield "never executed"


class AsyncCallable:
    async def __call__(self, *_args: Any, **_kwargs: Any) -> str:
        return "never executed"


class AsyncGeneratorCallable:
    async def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        yield "never executed"


ASYNC_CALLBACKS = [
    async_callback,
    async_generator,
    AsyncCallable(),
    AsyncCallable().__call__,
    AsyncGeneratorCallable(),
    partial(async_callback, "bound"),
    partial(AsyncCallable(), "bound"),
]


@pytest.mark.parametrize("callback", ASYNC_CALLBACKS)
@pytest.mark.parametrize("regional", [False, True])
def test_async_callbacks_are_rejected_before_authentication(
    callback: Any, regional: bool
) -> None:
    with pytest.raises(TypeError, match="function must be synchronous"):
        if regional:
            map_account_regions(
                callback,
                accounts=["111111111111"],
                regions=["eu-west-1"],
                auth=UnusedAuth(),
            )
        else:
            map_accounts(callback, accounts=["111111111111"], auth=UnusedAuth())


@pytest.mark.parametrize("observer", ASYNC_CALLBACKS)
def test_async_observers_are_rejected_even_for_empty_runs(observer: Any) -> None:
    with pytest.raises(TypeError, match="on_result must be synchronous"):
        map_accounts(
            lambda *_args: None, accounts=[], auth=UnusedAuth(), on_result=observer
        )


@pytest.mark.parametrize("resolver", ASYNC_CALLBACKS)
def test_async_resolvers_are_rejected_at_construction(resolver: Any) -> None:
    with pytest.raises(TypeError, match="resolver must be synchronous"):
        Profile(resolver=resolver)


@pytest.mark.parametrize("regional", [False, True])
def test_wrapped_coroutine_is_a_worker_failure_and_is_closed(regional: bool) -> None:
    created = []

    @wraps(async_callback)
    def wrapped(*args: Any) -> Any:
        coroutine = async_callback(*args)
        created.append(coroutine)
        return coroutine

    if regional:
        results = map_account_regions(
            wrapped,
            accounts=["111111111111"],
            regions=["eu-west-1"],
            auth=OfflineAuth(),
        )
    else:
        results = map_accounts(wrapped, accounts=["111111111111"], auth=OfflineAuth())
    assert results[0].phase is ExecutionPhase.WORKER
    assert isinstance(results[0].error, TypeError)
    assert "returned an asynchronous value" in str(results[0].error)
    assert inspect.getcoroutinestate(created[0]) == inspect.CORO_CLOSED


def test_wrapped_async_observer_propagates_and_stops_new_targets() -> None:
    called = []
    created = []

    def worker(_session: Any, account: Any) -> str:
        called.append(account.id)
        return account.id

    def observer(*args: Any, **kwargs: Any) -> Any:
        coroutine = async_callback(*args, **kwargs)
        created.append(coroutine)
        return coroutine

    with pytest.raises(TypeError, match="on_result returned an asynchronous value"):
        map_accounts(
            worker,
            accounts=["111111111111", "222222222222"],
            auth=OfflineAuth(),
            max_workers=1,
            on_result=observer,
        )
    assert called == ["111111111111"]
    assert inspect.getcoroutinestate(created[0]) == inspect.CORO_CLOSED


@pytest.mark.parametrize("factory", [async_generator, lambda: CustomAwaitable()])
def test_async_values_are_not_reported_as_success(factory: Any) -> None:
    result = map_accounts(
        lambda *_args: factory(), accounts=["111111111111"], auth=OfflineAuth()
    )[0]
    assert result.phase is ExecutionPhase.WORKER
    assert isinstance(result.error, TypeError)


class CustomAwaitable:
    def __await__(self) -> Any:
        pytest.fail("RunAcross must never drive a caller's awaitable")


def test_wrapped_async_resolver_is_an_auth_failure() -> None:
    created = []

    def resolver(_account: Any) -> Any:
        coroutine = async_callback()
        created.append(coroutine)
        return coroutine

    result = map_accounts(
        lambda *_args: None,
        accounts=["111111111111"],
        auth=Profile(resolver=resolver),
    )[0]
    assert result.phase is ExecutionPhase.AUTH
    assert isinstance(result.error, TypeError)
    assert inspect.getcoroutinestate(created[0]) == inspect.CORO_CLOSED


def test_sync_wrapper_that_executes_async_work_itself_remains_supported() -> None:
    @wraps(async_callback)
    def synchronous(*args: Any) -> str:
        return asyncio.run(async_callback(*args))

    result = map_accounts(synchronous, accounts=["111111111111"], auth=OfflineAuth())[0]
    assert result.success
    assert result.value == "never executed"


@pytest.mark.parametrize("callback", [lambda: None, lambda *, session, account: None])
def test_wrong_callback_signature_is_rejected_before_authentication(
    callback: Any,
) -> None:
    with pytest.raises(TypeError, match="function must accept 2 positional arguments"):
        map_accounts(callback, accounts=["111111111111"], auth=UnusedAuth())


def test_wrong_observer_keywords_are_rejected_before_authentication() -> None:
    def observer(result: Any, done: int, count: int) -> None:
        pass

    with pytest.raises(TypeError, match="on_result must accept"):
        map_accounts(
            lambda *_args: None,
            accounts=["111111111111"],
            auth=UnusedAuth(),
            on_result=observer,
        )


def test_uninspectable_callable_retains_runtime_error_isolation() -> None:
    class ExtensionLike:
        @property
        def __signature__(self) -> Any:
            raise ValueError("no signature")

        def __call__(self) -> None:
            pass

    result = map_accounts(
        ExtensionLike(), accounts=["111111111111"], auth=OfflineAuth()
    )[0]
    assert result.phase is ExecutionPhase.WORKER
    assert isinstance(result.error, TypeError)


def test_partial_sync_callback_and_keyword_observer_are_supported() -> None:
    observed = []

    def worker(prefix: str, session: Any, account: Any) -> str:
        return prefix + account.id

    def observer(result: Any, /, *, completed: int, total: int) -> None:
        observed.append((result.value, completed, total))

    result = map_accounts(
        partial(worker, "account:"),
        accounts=["111111111111"],
        auth=OfflineAuth(),
        on_result=observer,
    )[0]
    assert result.value == "account:111111111111"
    assert observed == [(result.value, 1, 1)]


@pytest.mark.parametrize("value", [1, "yes", None])
def test_discover_regions_requires_a_bool(value: Any) -> None:
    with pytest.raises(TypeError, match="discover_regions must be a bool"):
        map_account_regions(
            lambda *_args: None, accounts=[], auth=UnusedAuth(), discover_regions=value
        )
