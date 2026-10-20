# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Tests for GrpcStreamBroadcaster class."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any
from unittest import mock

import grpc
import grpc.aio
import pytest
from frequenz.channels import Receiver

from frequenz.client.base import retry, streaming
from frequenz.client.base.streaming import (
    StreamEvent,
    StreamFatalError,
    StreamRetrying,
    StreamStarted,
)


def _transformer(x: int) -> str:
    """Mock transformer."""
    return f"transformed_{x}"


@pytest.fixture
def receiver_ready_event() -> asyncio.Event:
    """Fixture for receiver ready event."""
    return asyncio.Event()


@pytest.fixture
def no_retry() -> mock.MagicMock:
    """Fixture for mocked, non-retrying retry strategy."""
    mock_retry = mock.MagicMock(spec=retry.Strategy)
    mock_retry.next_interval.return_value = None
    mock_retry.copy.return_value = mock_retry
    mock_retry.get_progress.return_value = "mock progress"
    return mock_retry


def make_error() -> grpc.aio.AioRpcError:
    """Mock error for testing."""
    return grpc.aio.AioRpcError(
        code=grpc.StatusCode.UNAVAILABLE,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="mock details",
        debug_error_string="mock debug_error_string",
    )


@pytest.fixture
async def ok_helper(
    no_retry: mock.MagicMock,  # pylint: disable=redefined-outer-name
    receiver_ready_event: asyncio.Event,  # pylint: disable=redefined-outer-name
    retry_on_exhausted_stream: bool,
) -> AsyncIterator[streaming.GrpcStreamBroadcaster[int, str]]:
    """Fixture for GrpcStreamBroadcaster."""

    async def asynciter() -> AsyncIterator[int]:
        """Mock async iterator."""
        await receiver_ready_event.wait()
        for i in range(5):
            yield i
            await asyncio.sleep(0)  # Yield control to the event loop

    helper = streaming.GrpcStreamBroadcaster(
        stream_name="test_helper",
        stream_method=asynciter,
        transform=_transformer,
        retry_strategy=no_retry,
        retry_on_exhausted_stream=retry_on_exhausted_stream,
    )
    yield helper
    await helper.stop()


async def _split_message(
    receiver: Receiver[StreamEvent | str],
) -> tuple[list[str], list[StreamEvent]]:
    """Split the items received from the receiver into items and messages.

    Args:
        receiver: The receiver to process.

    Returns:
        A tuple containing a list of transformed items and a list of messages.
    """
    items: list[str] = []
    events: list[StreamEvent] = []
    async for item in receiver:
        match item:
            case StreamStarted() | StreamRetrying() | StreamFatalError():
                events.append(item)
            case str():
                items.append(item)
    return items, events


class _ErroringAsyncIter(AsyncIterator[int]):
    """Async iterator that raises an error after a certain number of successes."""

    def __init__(
        self, error: Exception, ready_event: asyncio.Event, *, num_successes: int = 0
    ):
        self._error = error
        self._ready_event = ready_event
        self._num_successes = num_successes
        self._current = -1

    async def __anext__(self) -> int:
        self._current += 1
        await self._ready_event.wait()
        if self._current >= self._num_successes:
            raise self._error
        return self._current


@pytest.mark.parametrize("retry_on_exhausted_stream", [True])
async def test_streaming_success_retry_on_exhausted(
    ok_helper: streaming.GrpcStreamBroadcaster[
        int, str
    ],  # pylint: disable=redefined-outer-name
    no_retry: mock.MagicMock,  # pylint: disable=redefined-outer-name
    receiver_ready_event: asyncio.Event,  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test streaming success."""
    caplog.set_level(logging.INFO)
    items: list[str] = []
    events: list[StreamEvent] = []
    async with asyncio.timeout(1):
        receiver = ok_helper.new_receiver()
        receiver_ready_event.set()
        items, events = await _split_message(receiver)

    no_retry.next_interval.assert_called_once_with()
    assert items == [
        "transformed_0",
        "transformed_1",
        "transformed_2",
        "transformed_3",
        "transformed_4",
    ]
    assert events == []

    assert caplog.record_tuples == [
        (
            "frequenz.client.base.streaming",
            logging.ERROR,
            "test_helper: connection ended, retry limit exceeded (mock progress), "
            "giving up. Stream exhausted.",
        )
    ]


@pytest.mark.parametrize("retry_on_exhausted_stream", [False])
async def test_streaming_success(
    ok_helper: streaming.GrpcStreamBroadcaster[
        int, str
    ],  # pylint: disable=redefined-outer-name
    no_retry: mock.MagicMock,  # pylint: disable=redefined-outer-name
    receiver_ready_event: asyncio.Event,  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test streaming success."""
    caplog.set_level(logging.INFO)
    items: list[str] = []
    events: list[StreamEvent] = []

    async with asyncio.timeout(1):
        receiver = ok_helper.new_receiver()
        receiver_ready_event.set()
        items, events = await _split_message(receiver)

    no_retry.next_interval.assert_not_called()

    assert items == [
        "transformed_0",
        "transformed_1",
        "transformed_2",
        "transformed_3",
        "transformed_4",
    ]
    assert events == []
    assert caplog.record_tuples == [
        (
            "frequenz.client.base.streaming",
            logging.INFO,
            "test_helper: connection closed, stream exhausted",
        )
    ]


@pytest.mark.parametrize("successes", [0, 1, 5])
async def test_streaming_error(  # pylint: disable=too-many-arguments
    successes: int,
    no_retry: mock.MagicMock,  # pylint: disable=redefined-outer-name
    receiver_ready_event: asyncio.Event,  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test streaming errors."""
    caplog.set_level(logging.INFO)

    error = make_error()

    helper = streaming.GrpcStreamBroadcaster(
        stream_name="test_helper",
        stream_method=lambda: _ErroringAsyncIter(
            error, receiver_ready_event, num_successes=successes
        ),
        transform=_transformer,
        retry_strategy=no_retry,
    )

    items: list[str] = []
    async with AsyncExitStack() as stack:
        stack.push_async_callback(helper.stop)

        receiver = helper.new_receiver()
        receiver_ready_event.set()
        items, _ = await _split_message(receiver)

    no_retry.next_interval.assert_called_once_with()
    assert items == [f"transformed_{i}" for i in range(successes)]
    assert caplog.record_tuples == [
        (
            "frequenz.client.base.streaming",
            logging.INFO,
            "test_helper: starting to stream",
        ),
        (
            "frequenz.client.base.streaming",
            logging.ERROR,
            "test_helper: connection ended, retry limit exceeded (mock progress), "
            f"giving up. Error: {error}.",
        ),
        (
            "frequenz.client.base.streaming",
            logging.INFO,
            "test_helper: stopping the stream",
        ),
    ]


async def test_streaming_transform_error(  # pylint: disable=too-many-arguments
    no_retry: mock.MagicMock,  # pylint: disable=redefined-outer-name
    receiver_ready_event: asyncio.Event,  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test streaming transform errors."""
    caplog.set_level(logging.INFO)

    def transform_err(x: int) -> str:
        """Mock transform with err for odd values."""
        if x % 2 == 1:
            raise ValueError("No, you transform.")
        return f"transformed_{x}"

    async def asynciter() -> AsyncIterator[int]:
        """Mock async iterator."""
        await receiver_ready_event.wait()
        for i in range(5):
            yield i
            await asyncio.sleep(0)  # Yield control to the event loop

    rpc_mock = mock.MagicMock(
        name="ok_helper_method",
        side_effect=asynciter,
    )

    helper = streaming.GrpcStreamBroadcaster(
        stream_name="test_helper",
        stream_method=rpc_mock,
        transform=transform_err,
        retry_strategy=no_retry,
    )

    items: list[str] = []
    async with AsyncExitStack() as stack:
        stack.push_async_callback(helper.stop)

        receiver = helper.new_receiver()
        receiver_ready_event.set()
        items, _ = await _split_message(receiver)

    assert items == [
        "transformed_0",
        "transformed_2",
        "transformed_4",
    ]

    assert caplog.record_tuples == [
        (
            "frequenz.client.base.streaming",
            logging.INFO,
            "test_helper: starting to stream",
        ),
        # LogCaptureFixture can't capture tracebacks, so only the error message
        # is checked.
        (
            "frequenz.client.base.streaming",
            logging.ERROR,
            "test_helper: error transforming message: 1",
        ),
        (
            "frequenz.client.base.streaming",
            logging.ERROR,
            "test_helper: error transforming message: 3",
        ),
        (
            "frequenz.client.base.streaming",
            logging.INFO,
            "test_helper: connection closed, stream exhausted",
        ),
        (
            "frequenz.client.base.streaming",
            logging.INFO,
            "test_helper: stopping the stream",
        ),
    ]


@pytest.mark.parametrize("include_events", [True, False])
async def test_retry_next_interval_zero(  # pylint: disable=too-many-arguments
    receiver_ready_event: asyncio.Event,  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
    include_events: bool,
) -> None:
    """Test retry logic when next_interval returns 0."""
    caplog.set_level(logging.WARNING)
    error = make_error()
    mock_retry = mock.MagicMock(spec=retry.Strategy)
    mock_retry.next_interval.side_effect = [0, None]
    mock_retry.copy.return_value = mock_retry
    mock_retry.get_progress.return_value = "mock progress"
    helper = streaming.GrpcStreamBroadcaster(
        stream_name="test_helper",
        stream_method=lambda: _ErroringAsyncIter(error, receiver_ready_event),
        transform=_transformer,
        retry_strategy=mock_retry,
    )

    items: list[str] = []
    events: list[StreamEvent] = []
    async with AsyncExitStack() as stack:
        stack.push_async_callback(helper.stop)

        receiver = helper.new_receiver(include_events=include_events)
        receiver_ready_event.set()
        items, events = await _split_message(receiver)

    assert not items
    assert bool(events) == include_events

    assert mock_retry.next_interval.mock_calls == [mock.call(), mock.call()]
    assert caplog.record_tuples == [
        (
            "frequenz.client.base.streaming",
            logging.WARNING,
            "test_helper: connection ended, retrying mock progress in 0.000 "
            f"seconds. Error: {error}.",
        ),
        (
            "frequenz.client.base.streaming",
            logging.ERROR,
            "test_helper: connection ended, retry limit exceeded (mock progress), "
            f"giving up. Error: {error}.",
        ),
    ]


@pytest.mark.parametrize("include_events", [True, False])
async def test_messages_on_retry(
    receiver_ready_event: asyncio.Event,  # pylint: disable=redefined-outer-name
    include_events: bool,
) -> None:
    """Test that messages are sent on retry, and reset the retry count."""
    # We need to use a specific instance for all the test here because 2 errors created
    # with the same arguments don't compare equal (grpc.aio.AioRpcError doesn't seem to
    # provide a __eq__ method).
    error = make_error()
    successes = [2, 2, 0]

    helper = streaming.GrpcStreamBroadcaster(
        stream_name="test_helper",
        stream_method=lambda: _ErroringAsyncIter(
            error, receiver_ready_event, num_successes=successes.pop(0)
        ),
        transform=_transformer,
        retry_strategy=retry.LinearBackoff(limit=1, interval=0.0, jitter=0.0),
        retry_on_exhausted_stream=True,
    )

    items: list[str] = []
    events: list[StreamEvent] = []
    async with AsyncExitStack() as stack:
        stack.push_async_callback(helper.stop)

        receiver = helper.new_receiver(include_events=include_events)
        receiver_ready_event.set()
        items, events = await _split_message(receiver)

    assert items == [
        "transformed_0",
        "transformed_1",
        "transformed_0",
        "transformed_1",
    ]
    assert not successes
    if include_events:
        assert events == [
            StreamStarted(),
            StreamRetrying(timedelta(seconds=0.0), error),
            StreamStarted(),
            StreamRetrying(timedelta(seconds=0.0), error),
            StreamStarted(),
            StreamFatalError(error),
        ]
    else:
        assert events == []


class _HangingCall(AsyncIterator[int]):
    """Async iterator that never yields, like a server stream that stalls."""

    def __init__(self) -> None:
        self.cancelled = 0

    async def __anext__(self) -> int:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    def cancel(self) -> bool:
        """Record a cancellation, as a gRPC call would accept one."""
        self.cancelled += 1
        return True


async def _slow_stream() -> AsyncIterator[int]:
    """Yield 5 messages, 10 ms apart."""
    for i in range(5):
        await asyncio.sleep(0.01)
        yield i


def _helper(
    stream_method: Callable[[], AsyncIterator[int]], **kwargs: Any
) -> streaming.GrpcStreamBroadcaster[int, str]:
    """Create a broadcaster for the tests below."""
    return streaming.GrpcStreamBroadcaster(
        stream_name="test_helper",
        stream_method=stream_method,
        transform=_transformer,
        **kwargs,
    )


async def test_idle_timeout_retries_then_gives_up() -> None:
    """A stalled stream is cancelled, retried, and given up after the limit."""
    calls: list[_HangingCall] = []

    def stream_method() -> _HangingCall:
        calls.append(_HangingCall())
        return calls[-1]

    helper = _helper(
        stream_method,
        retry_strategy=retry.LinearBackoff(limit=1, interval=0.0, jitter=0.0),
        idle_timeout=timedelta(seconds=0.05),
    )
    async with AsyncExitStack() as stack:
        stack.push_async_callback(helper.stop)
        receiver = helper.new_receiver(include_events=True)
        items, events = await asyncio.wait_for(_split_message(receiver), timeout=5)

    assert items == []
    assert [type(e) for e in events] == [
        StreamStarted,
        StreamRetrying,
        StreamStarted,
        StreamFatalError,
    ]
    for event in (events[1], events[3]):
        assert isinstance(event, (StreamRetrying, StreamFatalError))
        assert isinstance(event.exception, streaming.StreamIdleTimeoutError)
        assert event.exception.idle_timeout == timedelta(seconds=0.05)
    assert [call.cancelled for call in calls] == [1, 1]


async def test_idle_timeout_measures_gaps_between_messages(
    no_retry: mock.MagicMock,  # pylint: disable=redefined-outer-name
) -> None:
    """A stream that keeps sending within the idle timeout is never cut off."""
    helper = _helper(
        _slow_stream, retry_strategy=no_retry, idle_timeout=timedelta(seconds=0.03)
    )
    async with AsyncExitStack() as stack:
        stack.push_async_callback(helper.stop)
        receiver = helper.new_receiver(include_events=True)
        items, events = await asyncio.wait_for(_split_message(receiver), timeout=5)

    assert items == [f"transformed_{i}" for i in range(5)]
    assert events == [StreamStarted()]


async def test_stop_during_idle_wait() -> None:
    """Stopping while waiting for a message cancels the call cleanly."""
    call = _HangingCall()
    helper = _helper(lambda: call, idle_timeout=timedelta(seconds=10))
    receiver = helper.new_receiver(include_events=True)
    await asyncio.sleep(0.01)
    await helper.stop()
    items, events = await asyncio.wait_for(_split_message(receiver), timeout=5)

    assert items == []
    assert events == [StreamStarted()]
    assert call.cancelled == 1
    assert not helper.is_running


async def test_no_idle_timeout_by_default() -> None:
    """Without an idle timeout a silent stream is left waiting."""
    call = _HangingCall()
    helper = _helper(lambda: call)
    try:
        receiver = helper.new_receiver()
        await asyncio.sleep(0.1)
        assert helper.is_running
        assert call.cancelled == 0
        receiver.close()
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


def test_idle_timeout_must_be_positive() -> None:
    """A zero or negative idle timeout is rejected."""
    for idle_timeout in (timedelta(0), timedelta(seconds=-1)):
        with pytest.raises(ValueError, match="idle_timeout"):
            _helper(_HangingCall, idle_timeout=idle_timeout)
