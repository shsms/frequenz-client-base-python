# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Tests for GrpcStreamBroadcaster class."""

import asyncio
import gc
import itertools
import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any
from unittest import mock

import grpc
import grpc.aio
import pytest
from frequenz.channels import Receiver, ReceiverStoppedError

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


async def _endless_stream() -> AsyncIterator[int]:
    """Yield a message every 10 ms, forever."""
    for i in itertools.count():
        yield i
        await asyncio.sleep(0.01)


def _collect_garbage_before(
    monkeypatch: pytest.MonkeyPatch, cls: type, name: str
) -> None:
    """Make `cls.name` run a full garbage collection before it does its work."""
    original = getattr(cls, name)

    def collecting(*args: Any, **kwargs: Any) -> Any:
        gc.collect()
        return original(*args, **kwargs)

    monkeypatch.setattr(cls, name, collecting)


def _drop_in_a_cycle(receiver: Any) -> None:
    """Drop a receiver so that only a garbage collection can free it."""
    cycle: list[Any] = [receiver]
    cycle.append(cycle)


class _SlowToCancel(_HangingCall):
    """A call that takes 0.1 s to clean up when it is cancelled."""

    def __init__(self, cleanups: list[str], finished: asyncio.Event) -> None:
        super().__init__()
        self._cleanups = cleanups
        self._finished = finished

    async def __anext__(self) -> int:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                self._cleanups.append("interrupted")
                raise
            finally:
                self._finished.set()
            self._cleanups.append("done")
            raise
        raise AssertionError("unreachable")


class _AlwaysFailing:
    """Stream method whose calls always fail, counting how often it is called."""

    def __init__(self) -> None:
        self.calls = 0
        self._ready_event = asyncio.Event()
        self._ready_event.set()

    def __call__(self) -> AsyncIterator[int]:
        self.calls += 1
        return _ErroringAsyncIter(make_error(), self._ready_event)


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


async def test_stops_when_all_receivers_closed_while_retrying() -> None:
    """A retrying stream stops once its only receiver is closed."""
    stream_method = _AlwaysFailing()
    helper = _helper(
        stream_method,
        retry_strategy=retry.LinearBackoff(limit=None, interval=0.01, jitter=0.0),
    )
    try:
        receiver = helper.new_receiver()
        await asyncio.sleep(0.05)
        receiver.close()
        await asyncio.sleep(0.05)
        assert not helper.is_running
        calls = stream_method.calls
        await asyncio.sleep(0.05)
        assert stream_method.calls == calls
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_stops_when_all_receivers_closed_while_stalled() -> None:
    """A stalled stream stops and cancels its call once its receiver is closed."""
    call = _HangingCall()
    helper = _helper(lambda: call)
    try:
        receiver = helper.new_receiver()
        await asyncio.sleep(0.01)
        receiver.close()
        assert not helper.is_running
        await asyncio.sleep(0.05)
        assert call.cancelled == 1
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_stops_when_receiver_is_garbage_collected() -> None:
    """A retrying stream stops once its only receiver is dropped."""
    helper = _helper(
        _AlwaysFailing(),
        retry_strategy=retry.LinearBackoff(limit=None, interval=0.01, jitter=0.0),
    )
    try:
        receiver = helper.new_receiver()
        del receiver
        gc.collect()
        await asyncio.sleep(0.05)
        assert not helper.is_running
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_stops_when_events_receiver_is_garbage_collected() -> None:
    """A stalled stream stops once its only receiver, with events, is dropped."""
    call = _HangingCall()
    helper = _helper(lambda: call)
    try:
        receiver = helper.new_receiver(include_events=True)
        await asyncio.sleep(0.01)
        del receiver
        gc.collect()
        await asyncio.sleep(0.05)
        assert not helper.is_running
        assert call.cancelled == 1
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_keeps_running_while_a_receiver_is_open(
    no_retry: mock.MagicMock,  # pylint: disable=redefined-outer-name
) -> None:
    """Closing one receiver leaves the stream running for the others."""
    helper = _helper(_slow_stream, retry_strategy=no_retry)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(helper.stop)
        closed = helper.new_receiver()
        kept = helper.new_receiver()
        closed.close()
        first = await asyncio.wait_for(kept.receive(), timeout=5)
        assert helper.is_running
        rest, _ = await asyncio.wait_for(_split_message(kept), timeout=5)

    assert [first, *rest] == [f"transformed_{i}" for i in range(5)]


async def test_events_receiver_keeps_the_stream_running() -> None:
    """A receiver with events keeps the stream alive until it is closed."""
    helper = _helper(_HangingCall)
    try:
        receiver = helper.new_receiver(include_events=True)
        await asyncio.sleep(0.05)
        assert helper.is_running
        receiver.close()
        await asyncio.sleep(0.05)
        assert not helper.is_running
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_new_receiver_restarts_after_receivers_gone() -> None:
    """A stream stopped for lack of receivers restarts for a new receiver."""
    stream = _CountingStream()
    helper = _helper(stream)
    try:
        first = helper.new_receiver()
        assert await asyncio.wait_for(first.receive(), timeout=5) == "transformed_1"
        first.close()
        await asyncio.sleep(0.05)
        assert not helper.is_running

        second = helper.new_receiver()
        assert helper.is_running
        assert await asyncio.wait_for(second.receive(), timeout=5) == "transformed_2"
        assert stream.calls == 2
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


@pytest.mark.parametrize("include_events", [False, True])
async def test_new_receiver_after_stop_is_stopped(include_events: bool) -> None:
    """After stop(), a new receiver ends without data."""
    helper = _helper(_HangingCall)
    await helper.stop()
    receiver = helper.new_receiver(include_events=include_events)
    assert not helper.is_running
    assert await asyncio.wait_for(_split_message(receiver), timeout=5) == ([], [])


class _CountingStream:
    """Stream method whose calls yield their number, then hang."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> AsyncIterator[int]:
        self.calls += 1
        yield self.calls
        await asyncio.Event().wait()


async def test_close_then_new_receiver_in_the_same_tick() -> None:
    """A receiver requested right after the last one closed gets data."""
    helper = _helper(_CountingStream())
    try:
        first = helper.new_receiver()
        assert await asyncio.wait_for(first.receive(), timeout=5) == "transformed_1"
        first.close()
        second = helper.new_receiver()
        assert await asyncio.wait_for(second.receive(), timeout=5) == "transformed_2"
        assert helper.is_running
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_new_receiver_after_breaking_out_of_a_loop() -> None:
    """A loop that breaks out and drops its receiver does not starve the next one."""
    helper = _helper(_endless_stream)
    received = []

    async def first_item() -> None:
        async for item in helper.new_receiver():
            received.append(item)
            break

    try:
        for _ in range(2):
            await asyncio.wait_for(first_item(), timeout=5)
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)
    assert len(received) == 2


async def test_close_before_the_stream_started() -> None:
    """Closing the only receiver before the stream ran does not hang the next one."""
    helper = _helper(_CountingStream())
    try:
        helper.new_receiver().close()
        receiver = helper.new_receiver()
        assert await asyncio.wait_for(receiver.receive(), timeout=5) == "transformed_1"
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_stop_after_receivers_gone_stays_stopped() -> None:
    """After stop(), a new receiver does not restart a stream whose receivers left."""
    helper = _helper(_HangingCall)
    receiver = helper.new_receiver()
    await asyncio.sleep(0.01)
    receiver.close()
    await helper.stop()
    late = helper.new_receiver()
    assert not helper.is_running
    assert await asyncio.wait_for(_split_message(late), timeout=5) == ([], [])


async def test_closing_events_receiver_keeps_data_flowing(
    no_retry: mock.MagicMock,  # pylint: disable=redefined-outer-name
) -> None:
    """Closing the only receiver with events does not stop the data receivers."""
    helper = _helper(_slow_stream, retry_strategy=no_retry)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(helper.stop)
        events = helper.new_receiver(include_events=True)
        data = helper.new_receiver()
        events.close()
        items = await asyncio.wait_for(_split_message(data), timeout=5)

    assert items == ([f"transformed_{i}" for i in range(5)], [])


async def test_messages_before_the_first_receiver_do_not_stop_the_stream() -> None:
    """Messages sent before any receiver exists do not stop the stream."""
    calls: list[int] = []
    sent = asyncio.Event()

    async def stream() -> AsyncIterator[int]:
        calls.append(len(calls))
        yield 0
        sent.set()
        await asyncio.sleep(0.01)
        yield 1
        await asyncio.Event().wait()

    helper = _helper(stream)
    try:
        await asyncio.wait_for(sent.wait(), timeout=5)
        receiver = helper.new_receiver()
        assert await asyncio.wait_for(receiver.receive(), timeout=5) == "transformed_1"
        assert calls == [0]
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_restart_gets_a_fresh_retry_budget() -> None:
    """A restarted stream does not inherit the retries the previous run used."""
    stream_method = _AlwaysFailing()
    helper = _helper(
        stream_method,
        retry_strategy=retry.LinearBackoff(limit=1, interval=0.0, jitter=0.0),
    )
    try:
        first = helper.new_receiver()
        await asyncio.sleep(0)
        first.close()
        await asyncio.sleep(0.01)
        second = helper.new_receiver(include_events=True)
        _, events = await asyncio.wait_for(_split_message(second), timeout=5)
        assert [type(e) for e in events] == [
            StreamStarted,
            StreamRetrying,
            StreamStarted,
            StreamFatalError,
        ]
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_unexpected_error_ends_the_receivers() -> None:
    """An unexpected error from the call ends the receivers instead of hanging them."""

    async def stream() -> AsyncIterator[int]:
        yield 1
        raise ValueError("unexpected")

    helper = _helper(stream)
    receiver = helper.new_receiver(include_events=True)
    items, events = await asyncio.wait_for(_split_message(receiver), timeout=5)
    assert items == ["transformed_1"]
    assert [type(e) for e in events] == [StreamStarted, StreamFatalError]
    assert isinstance(events[1], StreamFatalError)
    assert isinstance(events[1].exception, ValueError)
    await helper.stop()


async def test_receiver_dropped_in_another_thread() -> None:
    """A receiver collected in another thread stops the stream on the loop."""
    call = _HangingCall()
    helper = _helper(lambda: call)
    try:
        holder = [helper.new_receiver()]
        await asyncio.sleep(0.01)
        thread = threading.Thread(target=holder.clear)
        thread.start()
        thread.join()
        await asyncio.wait_for(_wait_until_stopped(helper), timeout=5)
        assert call.cancelled == 1
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def _wait_until_stopped(
    helper: streaming.GrpcStreamBroadcaster[int, str],
) -> None:
    """Wait until the broadcaster is no longer running."""
    while helper.is_running:
        await asyncio.sleep(0.01)


async def test_stop_before_the_stream_started() -> None:
    """A receiver handed out right before stop() ends instead of hanging."""
    helper = _helper(_HangingCall)
    receiver = helper.new_receiver()
    await helper.stop()
    assert await asyncio.wait_for(_split_message(receiver), timeout=5) == ([], [])


async def test_garbage_collection_while_subscribing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A receiver collected while a new one subscribes does not end the new one."""
    helper = _helper(_endless_stream)
    gc.disable()
    try:
        first = helper.new_receiver()
        await asyncio.wait_for(first.receive(), timeout=5)
        _drop_in_a_cycle(first)
        del first
        _collect_garbage_before(
            monkeypatch, streaming._Run, "subscribe"  # pylint: disable=protected-access
        )
        second = helper.new_receiver()
        await asyncio.wait_for(second.receive(), timeout=5)
        assert helper.is_running
    finally:
        gc.enable()
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_closed_receiver_stops_while_others_continue() -> None:
    """A closed receiver ends even while the stream keeps running for others."""
    helper = _helper(_endless_stream)
    try:
        closed = helper.new_receiver()
        kept = helper.new_receiver()
        await asyncio.wait_for(kept.receive(), timeout=5)
        closed.close()
        with pytest.raises(ReceiverStoppedError):
            await asyncio.wait_for(closed.receive(), timeout=5)
        await asyncio.wait_for(kept.receive(), timeout=5)
        assert helper.is_running
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_call_timeout_error_is_not_an_idle_timeout() -> None:
    """A TimeoutError raised by the call is a failure, not an idle timeout."""
    calls = 0

    async def stream() -> AsyncIterator[int]:
        nonlocal calls
        calls += 1
        raise TimeoutError("from the call")
        yield 0  # pylint: disable=unreachable

    helper = _helper(stream, idle_timeout=timedelta(seconds=10))
    try:
        receiver = helper.new_receiver(include_events=True)
        _, events = await asyncio.wait_for(_split_message(receiver), timeout=5)
        assert [type(e) for e in events] == [StreamStarted, StreamFatalError]
        assert isinstance(events[1], StreamFatalError)
        # pylint: disable-next=unidiomatic-typecheck
        assert type(events[1].exception) is TimeoutError
        assert calls == 1
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_stop_does_not_swallow_the_callers_cancellation() -> None:
    """Cancelling the task that awaits stop() cancels it."""
    helper = _helper(lambda: _SlowToCancel([], asyncio.Event()))
    receiver = helper.new_receiver()
    await asyncio.sleep(0.01)
    stopper = asyncio.create_task(helper.stop())
    await asyncio.sleep(0.01)
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert await asyncio.wait_for(_split_message(receiver), timeout=5) == ([], [])


async def test_stop_closes_receivers_when_its_caller_is_cancelled() -> None:
    """A cancelled stop() still ends the receivers of a run that never started."""
    receivers: list[Receiver[str]] = []

    async def make_and_stop() -> None:
        helper = _helper(_HangingCall)
        receivers.append(helper.new_receiver())
        await helper.stop()

    stopper = asyncio.create_task(make_and_stop())
    await asyncio.sleep(0)
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert await asyncio.wait_for(_split_message(receivers[0]), timeout=5) == (
        [],
        [],
    )


async def test_closing_a_receiver_twice_counts_it_once() -> None:
    """A receiver closed twice, then collected, leaves the others running."""
    helper = _helper(_endless_stream)
    try:
        closed = helper.new_receiver()
        kept = helper.new_receiver()
        await asyncio.wait_for(kept.receive(), timeout=5)
        closed.close()
        closed.close()
        del closed
        gc.collect()
        await asyncio.sleep(0.02)
        assert helper.is_running
        await asyncio.wait_for(kept.receive(), timeout=5)
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_failed_new_receiver_is_not_counted() -> None:
    """A new_receiver() call that raises does not keep the stream running."""
    helper = _helper(_HangingCall)
    try:
        receiver = helper.new_receiver()
        with pytest.raises(ValueError):
            helper.new_receiver(maxsize=-1)
        receiver.close()
        assert not helper.is_running
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_failed_close_still_counts_the_receiver_as_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A receiver whose close() raises no longer keeps the stream running."""

    def failing_close() -> None:
        raise RuntimeError("close failed")

    helper = _helper(_HangingCall)
    try:
        receiver = helper.new_receiver()
        monkeypatch.setattr(getattr(receiver, "_receiver"), "close", failing_close)
        with pytest.raises(RuntimeError, match="close failed"):
            receiver.close()
        assert not helper.is_running
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_restart_after_release_inside_the_stream_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stream whose last receiver goes away in its own step restarts later."""
    caplog.set_level(logging.WARNING)
    receivers: list[Receiver[str]] = []

    async def stream() -> AsyncIterator[int]:
        if not receivers:
            raise AssertionError("no receiver yet")
        if len(receivers) == 1:
            receivers[0].close()
            raise make_error()
        yield 1
        await asyncio.Event().wait()

    helper = _helper(stream, retry_strategy=retry.LinearBackoff(interval=0.0))
    try:
        receivers.append(helper.new_receiver())
        await asyncio.wait_for(_wait_until_stopped(helper), timeout=5)
        assert not [r for r in caplog.records if r.name == streaming.__name__]
        receivers.append(helper.new_receiver())
        assert await asyncio.wait_for(receivers[1].receive(), timeout=5) == (
            "transformed_1"
        )
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_runs_do_not_pile_up() -> None:
    """Receivers closed right after they are created do not leave runs behind."""
    helper = _helper(_CountingStream())
    try:
        for _ in range(20):
            helper.new_receiver().close()
        await asyncio.sleep(0)
        helper.new_receiver()
        assert len(helper._runs) <= 2  # pylint: disable=protected-access
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_garbage_collection_while_counting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A receiver collected while a new one is counted makes the stream restart."""
    helper = _helper(_CountingStream())
    gc.disable()
    try:
        first = helper.new_receiver()
        assert await asyncio.wait_for(first.receive(), timeout=5) == "transformed_1"
        _drop_in_a_cycle(first)
        del first
        _collect_garbage_before(
            monkeypatch,
            streaming._ReceiverCounter,  # pylint: disable=protected-access
            "acquire",
        )
        second = helper.new_receiver()
        assert await asyncio.wait_for(second.receive(), timeout=5) == "transformed_2"
    finally:
        gc.enable()
        await asyncio.wait_for(helper.stop(), timeout=5)


@pytest.mark.parametrize("fails", [False, True], ids=["ended", "gave-up"])
async def test_finished_stream_stays_finished(fails: bool) -> None:
    """A stream that ended or gave up on its own is not restarted."""
    calls = 0

    async def stream() -> AsyncIterator[int]:
        nonlocal calls
        calls += 1
        yield 1
        if fails:
            raise make_error()

    helper = _helper(
        stream, retry_strategy=retry.LinearBackoff(limit=0, interval=0.0, jitter=0.0)
    )
    try:
        first = helper.new_receiver()
        assert await asyncio.wait_for(_split_message(first), timeout=5) == (
            ["transformed_1"],
            [],
        )
        first.close()
        late = helper.new_receiver()
        assert await asyncio.wait_for(_split_message(late), timeout=5) == ([], [])
        late_events = helper.new_receiver(include_events=True)
        assert await asyncio.wait_for(_split_message(late_events), timeout=5) == (
            [],
            [],
        )
        assert calls == 1
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_restart_lets_the_old_call_finish_its_cleanup() -> None:
    """Starting a new run does not interrupt the old call's cleanup."""
    cleanups: list[str] = []
    finished = asyncio.Event()
    calls: list[_SlowToCancel] = []

    def stream_method() -> _SlowToCancel:
        calls.append(
            _SlowToCancel(cleanups, finished if not calls else asyncio.Event())
        )
        return calls[-1]

    helper = _helper(stream_method)
    try:
        first = helper.new_receiver()
        await asyncio.sleep(0.01)
        first.close()
        await asyncio.sleep(0.01)
        second = helper.new_receiver()
        await asyncio.wait_for(finished.wait(), timeout=5)
        assert cleanups == ["done"]
        assert helper.is_running
        second.close()
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


async def test_stop_waits_for_older_runs() -> None:
    """stop() waits until the calls of earlier runs have finished their cleanup."""
    finished = asyncio.Event()
    calls: list[_HangingCall] = []

    def stream_method() -> _HangingCall:
        calls.append(_SlowToCancel([], finished) if not calls else _HangingCall())
        return calls[-1]

    helper = _helper(stream_method)
    first = helper.new_receiver()
    await asyncio.sleep(0.01)
    first.close()
    second = helper.new_receiver()
    await asyncio.sleep(0.01)
    await asyncio.wait_for(helper.stop(), timeout=5)
    assert finished.is_set()
    second.close()


async def test_restart_after_a_failed_cleanup() -> None:
    """A stream that fails while it stops for lack of receivers still restarts."""
    calls = 0

    async def stream() -> AsyncIterator[int]:
        nonlocal calls
        calls += 1
        yield calls
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("cleanup failed") from None

    helper = _helper(stream)
    try:
        first = helper.new_receiver()
        assert await asyncio.wait_for(first.receive(), timeout=5) == "transformed_1"
        first.close()
        await asyncio.sleep(0.05)
        second = helper.new_receiver()
        assert await asyncio.wait_for(second.receive(), timeout=5) == "transformed_2"
    finally:
        await asyncio.wait_for(helper.stop(), timeout=5)


class _CollectGarbage(logging.Filter):
    """A log filter that runs a full garbage collection for every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Collect garbage and keep the record."""
        gc.collect()
        return True


@pytest.mark.parametrize(
    "error",
    [None, make_error(), ValueError("unexpected")],
    ids=["ended", "gave-up", "failed"],
)
async def test_receiver_collected_as_the_stream_finishes(
    error: Exception | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stream whose last receiver is collected after it ended stays finished."""
    caplog.set_level(logging.INFO, logger=streaming.__name__)
    calls = 0
    finish = asyncio.Event()

    async def stream() -> AsyncIterator[int]:
        nonlocal calls
        calls += 1
        yield 1
        await finish.wait()
        if error is not None:
            raise error

    helper = _helper(
        stream, retry_strategy=retry.LinearBackoff(limit=0, interval=0.0, jitter=0.0)
    )
    logger = logging.getLogger(streaming.__name__)
    collect = _CollectGarbage()
    gc.disable()
    try:
        first = helper.new_receiver()
        assert await asyncio.wait_for(first.receive(), timeout=5) == "transformed_1"
        _drop_in_a_cycle(first)
        del first
        logger.addFilter(collect)
        finish.set()
        await asyncio.wait_for(_wait_until_stopped(helper), timeout=5)
        await asyncio.sleep(0.01)
        logger.removeFilter(collect)
        late = helper.new_receiver()
        assert await asyncio.wait_for(_split_message(late), timeout=5) == ([], [])
        assert calls == 1
    finally:
        logger.removeFilter(collect)
        gc.enable()
        await asyncio.wait_for(helper.stop(), timeout=5)
