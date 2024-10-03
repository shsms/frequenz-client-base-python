# License: MIT
# Copyright © 2022 Frequenz Energy-as-a-Service GmbH

"""Implementations for retry strategies."""

import random
from abc import ABC, abstractmethod
from collections.abc import Iterator
from copy import deepcopy
from typing import Self

DEFAULT_RETRY_INTERVAL = 3.0
"""Default retry interval, in seconds."""

DEFAULT_RETRY_JITTER = 1.0
"""Default retry jitter, in seconds."""


class Strategy(ABC):
    """Interface for implementing retry strategies."""

    _limit: int | None
    _count: int

    @abstractmethod
    def next_interval(self) -> float | None:
        """Return the time to wait before the next retry.

        Returns `None` if the retry limit has been reached, and no more retries
        are possible.

        Returns:
            Time until next retry when below retry limit, and None otherwise.
        """

    def get_progress(self) -> str:
        """Return a string denoting the retry progress.

        Returns:
            String denoting retry progress in the form "(count/limit)"
        """
        if self._limit is None:
            return f"({self._count}/∞)"

        return f"({self._count}/{self._limit})"

    def reset(self) -> None:
        """Reset the retry counter.

        To be called as soon as a connection is successful.
        """
        self._count = 0

    def copy(self) -> Self:
        """Create a new instance of `self`.

        Returns:
            A deepcopy of `self`.
        """
        ret = deepcopy(self)
        ret.reset()
        return ret

    def __iter__(self) -> Iterator[float]:
        """Return an iterator over the retry intervals.

        Yields:
            Next retry interval in seconds.
        """
        while True:
            interval = self.next_interval()
            if interval is None:
                break
            yield interval


class LinearBackoff(Strategy):
    """Provides methods for calculating the interval between retries."""

    def __init__(
        self,
        *,
        interval: float = DEFAULT_RETRY_INTERVAL,
        jitter: float = DEFAULT_RETRY_JITTER,
        limit: int | None = None,
    ) -> None:
        """Create a `LinearBackoff` instance.

        Args:
            interval: time to wait for before the next retry, in seconds.
            jitter: a jitter to add to the retry interval.
            limit: max number of retries before giving up.  `None` means no
                limit, and `0` means no retry.
        """
        self._interval = interval
        self._jitter = jitter
        self._limit = limit

        self._count = 0

    def next_interval(self) -> float | None:
        """Return the time to wait before the next retry.

        Returns `None` if the retry limit has been reached, and no more retries
        are possible.

        Returns:
            Time until next retry when below retry limit, and None otherwise.
        """
        if self._limit is not None and self._count >= self._limit:
            return None
        self._count += 1
        return self._interval + random.uniform(0.0, self._jitter)


class ExponentialBackoff(Strategy):
    """Provides methods for calculating the exponential interval between retries."""

    DEFAULT_INTERVAL = DEFAULT_RETRY_INTERVAL
    """Default retry interval, in seconds."""

    DEFAULT_MAX_INTERVAL = 60.0
    """Default maximum retry interval, in seconds."""

    DEFAULT_MULTIPLIER = 2.0
    """Default multiplier for exponential increment."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        initial_interval: float = DEFAULT_INTERVAL,
        max_interval: float = DEFAULT_MAX_INTERVAL,
        multiplier: float = DEFAULT_MULTIPLIER,
        jitter: float = DEFAULT_RETRY_JITTER,
        limit: int | None = None,
    ) -> None:
        """Create a `ExponentialBackoff` instance.

        Args:
            initial_interval: time to wait for before the first retry, in
                seconds.
            max_interval: maximum interval, in seconds.
            multiplier: exponential increment for interval.
            jitter: a jitter to add to the retry interval.
            limit: max number of retries before giving up.  `None` means no
                limit, and `0` means no retry.
        """
        self._initial = initial_interval
        self._max = max_interval
        self._multiplier = multiplier
        self._jitter = jitter
        self._limit = limit

        self._count = 0

    def next_interval(self) -> float | None:
        """Return the time to wait before the next retry.

        Returns `None` if the retry limit has been reached, and no more retries
        are possible.

        Returns:
            Time until next retry when below retry limit, and None otherwise.
        """
        if self._limit is not None and self._count >= self._limit:
            return None
        self._count += 1
        exp_backoff_interval = self._initial * self._multiplier ** (self._count - 1)
        return min(exp_backoff_interval + random.uniform(0.0, self._jitter), self._max)
