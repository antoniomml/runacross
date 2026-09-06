"""Compare executor overhead with the eager scheduling used in 0.6.0.

Run from an editable development install: python benchmarks/pool.py
No AWS access, credentials, or third-party benchmark dependencies are needed.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import time
import tracemalloc
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from runacross.executor import _run_pool


def eager(items: range, workers: int) -> list[int]:
    ordered = [0] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        indexes = {
            executor.submit(int, item): index for index, item in enumerate(items)
        }
        for future in as_completed(indexes):
            ordered[indexes[future]] = future.result()
    return ordered


def bounded(items: range, workers: int) -> list[int]:
    return _run_pool(items, int, max_workers=workers)


def measure(
    runner: Callable[[range, int], list[int]], count: int, workers: int
) -> dict[str, float]:
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    results = runner(range(count), workers)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert results == list(range(count))
    return {"seconds": elapsed, "peak_mib": peak / (1024 * 1024)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=int, default=20000)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if min(args.targets, args.workers, args.repeats) < 1:
        parser.error("targets, workers and repeats must be positive")
    output: dict[str, object] = {"python": platform.python_version(), **vars(args)}
    for name, runner in (("eager_0_6_0", eager), ("bounded", bounded)):
        samples = [
            measure(runner, args.targets, args.workers) for _ in range(args.repeats)
        ]
        output[name] = {
            key: round(statistics.median(sample[key] for sample in samples), 4)
            for key in ("seconds", "peak_mib")
        }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
