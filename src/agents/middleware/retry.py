"""
Retry middleware — wraps LLM calls with exponential backoff.

When Groq (or any provider) returns 400/429/500, we retry with increasing
delays instead of failing the entire chunk.

Usage
-----
    from src.agents.middleware import retry_with_backoff

    # As a decorator on any function that calls the LLM:
    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def call_llm(chain, inputs):
        return chain.invoke(inputs)

    # Or wrap inline:
    result = retry_with_backoff(max_retries=3)(lambda: chain.invoke(inputs))()
"""
from __future__ import annotations

import functools
import time
from typing import Callable, TypeVar, Any

from src.utils.logger import setup_logger

log = setup_logger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator: retry a function with exponential backoff.

    Parameters
    ----------
    max_retries : int
        Maximum number of retry attempts (not counting the first call).
    initial_delay : float
        Seconds to wait before the first retry.
    backoff_factor : float
        Multiply the delay by this after each retry.
        Set to 0.0 for constant delay.
    retryable_exceptions : tuple
        Exception types that trigger a retry.

    Returns
    -------
    The decorated function's return value on success.

    Raises
    ------
    The last exception if all retries are exhausted.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exception: Exception | None = None

            for attempt in range(1 + max_retries):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exception = exc
                    if attempt < max_retries:
                        log.warning(
                            f"Retry {attempt + 1}/{max_retries} after "
                            f"{type(exc).__name__}: {exc!s:.200s} "
                            f"(waiting {delay:.1f}s)"
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        log.error(
                            f"All {max_retries} retries exhausted for "
                            f"{func.__name__}: {exc!s:.200s}"
                        )

            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
