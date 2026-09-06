from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from runacross.executor import _run_pool


def test_pool_bounds_submissions_and_notifies_on_the_calling_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted = 0
    caller = threading.get_ident()

    class RecordingPool(ThreadPoolExecutor):
        def submit(self, *args: Any, **kwargs: Any) -> Any:
            nonlocal submitted
            submitted += 1
            return super().submit(*args, **kwargs)

    def observe(result: int, *, completed: int, total: int) -> None:
        assert threading.get_ident() == caller
        assert submitted - completed < 3
        assert total == 1000
        assert result % 2 == 0

    monkeypatch.setattr("runacross.executor.ThreadPoolExecutor", RecordingPool)
    assert _run_pool(
        range(1000), lambda item: item * 2, max_workers=3, on_result=observe
    ) == list(range(0, 2000, 2))


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_observer_failure_does_not_start_remaining_targets(
    error_type: type[BaseException],
) -> None:
    called: list[int] = []

    def worker(item: int) -> int:
        called.append(item)
        return item

    def observe(_result: int, **_kwargs: int) -> None:
        raise error_type("stop")

    with pytest.raises(error_type, match="stop"):
        _run_pool(range(100), worker, max_workers=1, on_result=observe)
    assert called == [0]


def test_observer_failure_waits_for_running_worker() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def worker(item: int) -> int:
        if item == 0:
            assert started.wait(5)
        else:
            started.set()
            assert release.wait(5)
            finished.set()
        return item

    def observe(_result: int, **_kwargs: int) -> None:
        release.set()
        raise RuntimeError("stop")

    with pytest.raises(RuntimeError, match="stop"):
        _run_pool(range(100), worker, max_workers=2, on_result=observe)
    assert finished.is_set()


def test_worker_base_exception_propagates_without_starting_more_work() -> None:
    called: list[int] = []

    def worker(item: int) -> None:
        called.append(item)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run_pool(range(100), worker, max_workers=1)
    assert called == [0]
