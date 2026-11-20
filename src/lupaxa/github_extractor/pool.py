"""Run one function across many items on a bounded thread pool."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import concurrent.futures
from typing import TypeVar

T = TypeVar("T")


def run_workers(items: Sequence[T], worker: Callable[[T], None], max_workers: int) -> None:
    """Run worker on each item, a few at a time, and cancel the rest on failure."""
    if not items:
        return
    worker_count = min(max_workers, len(items))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=worker_count)
    item_iterator = iter(items)
    pending = {executor.submit(worker, item) for item in (next(item_iterator, None) for _ in range(worker_count)) if item is not None}
    try:
        while pending:
            done, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                future.result()
            for _ in done:
                item = next(item_iterator, None)
                if item is not None:
                    pending.add(executor.submit(worker, item))
    except Exception:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)
