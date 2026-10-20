# License: MIT
# Copyright © 2023 Frequenz Energy-as-a-Service GmbH

"""Implementation of the grpc streaming helper."""

import asyncio
import contextlib
import functools
import logging
import weakref
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import (
    AsyncIterable,
    Generic,
    Literal,
    TypeAlias,
    TypeVar,
    overload,
)

import grpc.aio

from frequenz import channels

from . import retry

_logger = logging.getLogger(__name__)


InputT = TypeVar("InputT")
"""The input type of the stream."""

OutputT = TypeVar("OutputT")
"""The output type of the stream."""

_T = TypeVar("_T")
"""The message type of a tracked receiver."""


@dataclass(frozen=True)
class StreamStarted:
    """Event indicating that the stream has started."""


@dataclass(frozen=True)
class StreamRetrying:
    """Event indicating that the stream has stopped."""

    delay: timedelta
    """Time to wait before retrying to start the stream again."""

    exception: Exception | None = None
    """The exception that caused the stream to stop, if any.

    If `None`, the stream was stopped without an error, e.g. the server closed the
    stream.
    """


@dataclass(frozen=True)
class StreamFatalError:
    """Event indicating that the stream has stopped due to an unrecoverable error."""

    exception: Exception
    """The exception that caused the stream to stop."""


class StreamIdleTimeoutError(TimeoutError):
    """The stream received no message within its idle timeout.

    It is not an `ApiClientError`, because the broadcaster does not know the
    server URL.
    """

    def __init__(self, stream_name: str, idle_timeout: timedelta) -> None:
        """Initialize the error.

        Args:
            stream_name: The name of the stream.
            idle_timeout: The idle timeout that expired.
        """
        super().__init__(f"no message received for {idle_timeout}")
        self.stream_name = stream_name
        """The name of the stream."""
        self.idle_timeout = idle_timeout
        """The idle timeout that expired."""


StreamEvent: TypeAlias = StreamStarted | StreamRetrying | StreamFatalError
"""Type alias for the events that can be sent over the stream."""


# pylint: disable-next=too-many-instance-attributes
class GrpcStreamBroadcaster(Generic[InputT, OutputT]):
    """Helper class to handle grpc streaming methods.

    This class handles the grpc streaming methods, automatically reconnecting
    when the connection is lost, and broadcasting the received messages to
    multiple receivers.

    The stream starts when the broadcaster is created. It stops when `stop()` is
    called, or when the stream ends, gives up or fails. New receivers can be
    created with the `new_receiver` method, which will receive the streamed
    messages.

    Once receivers were handed out, the stream also stops by itself when every
    one of them is closed or garbage-collected. Keep a receiver referenced while
    it is in use.

    If `include_events=True` is passed to `new_receiver`, the receiver will
    also get state change messages (`StreamStarted`, `StreamRetrying`,
    `StreamFatalError`) indicating the state of the stream.

    Example:
        ```python
        from frequenz.client.base import (
            GrpcStreamBroadcaster,
            StreamFatalError,
            StreamRetrying,
            StreamStarted,
        )
        from frequenz.channels import Receiver # Assuming Receiver is available

        # Dummy async iterable for demonstration
        async def async_range(fail_after: int = -1) -> AsyncIterable[int]:
            for i in range(10):
                if fail_after != -1 and i >= fail_after:
                    raise grpc.aio.AioRpcError(
                        code=grpc.StatusCode.UNAVAILABLE,
                        initial_metadata=grpc.aio.Metadata(),
                        trailing_metadata=grpc.aio.Metadata(),
                        details="Simulated error"
                    )
                yield i
                await asyncio.sleep(0.1)

        async def main():
            streamer = GrpcStreamBroadcaster(
                stream_name="example_stream",
                stream_method=lambda: async_range(fail_after=3),
                transform=lambda msg: msg * 2, # transform messages
                retry_on_exhausted_stream=False,
            )

            # Receiver for data only
            data_recv: Receiver[int] = streamer.new_receiver()

            # Receiver for data and events
            mixed_recv: Receiver[int | StreamEvent] = streamer.new_receiver(
                include_events=True
            )

            async def consume_mixed():
                async for msg in mixed_recv:
                    match msg:
                        case StreamStarted():
                            print("Mixed: Stream started")
                        case StreamRetrying(delay, error):
                            print(
                                "Mixed: Stream retrying in " +
                                f"{delay.total_seconds():.1f}s: {error or 'closed'}"
                            )
                        case StreamFatalError(error):
                            print(f"Mixed: Stream fatal error: {error}")
                            break # Stop consuming on fatal error
                        case int() as output:
                            print(f"Mixed: Received data: {output}")
                    if isinstance(msg, StreamFatalError):
                        break
                print("Mixed: Consumer finished")


            async def consume_data():
                async for data_msg in data_recv:
                    print(f"DataOnly: Received data: {data_msg}")
                print("DataOnly: Consumer finished")

            mixed_consumer_task = asyncio.create_task(consume_mixed())
            data_consumer_task = asyncio.create_task(consume_data())

            await asyncio.sleep(5) # Let it run for a bit
            print("Stopping streamer...")
            await streamer.stop()
            await mixed_consumer_task
            await data_consumer_task
            print("Streamer stopped.")

        if __name__ == "__main__":
            asyncio.run(main())
        ```
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        stream_name: str,
        stream_method: Callable[[], AsyncIterable[InputT]],
        transform: Callable[[InputT], OutputT],
        retry_strategy: retry.Strategy | None = None,
        retry_on_exhausted_stream: bool = False,
        idle_timeout: timedelta | None = None,
    ):
        """Initialize the streaming helper.

        Args:
            stream_name: A name to identify the stream in the logs.
            stream_method: A function that returns the grpc stream. This function is
                called every time the connection is lost and we want to retry.
            transform: A function to transform the input type to the output type.
            retry_strategy: The retry strategy to use, when the connection is lost. Defaults
                to retries every 3 seconds, with a jitter of 1 second, indefinitely.
                The retry count is reset when a message arrives, so a limit counts
                the retries in a row that receive no message. So a limit above 0
                never stops a stream that receives a message on every
                connection. With `ExponentialBackoff`, the wait also starts again
                from its initial interval.
            retry_on_exhausted_stream: Whether to retry when the stream is exhausted, i.e.
                when the server closes the stream. Defaults to False.
            idle_timeout: If set, a call that receives no message for this long is
                cancelled and handled like a failed call: it is retried according to
                `retry_strategy`, with a `StreamIdleTimeoutError` as the error.

        Raises:
            ValueError: If `idle_timeout` is not positive.
        """
        if idle_timeout is not None and idle_timeout <= timedelta(0):
            raise ValueError(f"idle_timeout must be positive, not {idle_timeout}")
        self._stream_name = stream_name
        self._stream_method = stream_method
        self._transform = transform
        self._retry_strategy = (
            retry.LinearBackoff() if retry_strategy is None else retry_strategy
        )
        self._retry_on_exhausted_stream = retry_on_exhausted_stream
        self._idle_timeout = idle_timeout
        self._stop_requested = False
        self._runs: set[_Run[OutputT]] = set()
        self._current_run = self._start_run()

    def _start_run(self) -> "_Run[OutputT]":
        """Start streaming with new channels and a fresh retry strategy.

        Returns:
            The new run.
        """
        run = _Run[OutputT](
            f"GrpcStreamBroadcaster-{self._stream_name}",
            self._retry_strategy.copy(),
            asyncio.get_running_loop(),
        )
        run.task = asyncio.create_task(self._run(run))
        self._runs = {r for r in self._runs if not r.task.done()} | {run}
        return run

    @overload
    def new_receiver(
        self,
        *,
        maxsize: int = 50,
        warn_on_overflow: bool = True,
        include_events: Literal[False] = False,
    ) -> channels.Receiver[OutputT]: ...

    @overload
    def new_receiver(
        self,
        *,
        maxsize: int = 50,
        warn_on_overflow: bool = True,
        include_events: bool,
    ) -> channels.Receiver[StreamEvent | OutputT]: ...

    # `pydoclint` counts the `raise` that passes on an error of `subscribe()`.
    def new_receiver(  # noqa: DOC501, DOC503
        self,
        *,
        maxsize: int = 50,
        warn_on_overflow: bool = True,
        include_events: bool = False,
    ) -> channels.Receiver[StreamEvent | OutputT]:
        """Create a new receiver for the stream.

        If the stream has stopped, the receiver ends at once without data.

        Args:
            maxsize: The maximum number of messages to buffer in underlying receivers.
            warn_on_overflow: Whether to log a warning when a receiver's
                buffer is full and a message is dropped.
            include_events: Whether to include stream events (e.g. StreamStarted,
                StreamRetrying, StreamFatalError) in the receiver. If `False` (default),
                only transformed data messages will be received.

        Returns:
            A new receiver. If `include_events` is True, the receiver will yield
            both `OutputT` and `StreamEvent` types. Otherwise, only `OutputT`.
        """
        run = self._current_run
        # Count the receiver before subscribing: a garbage collection while
        # subscribing could otherwise release the run's last receiver and stop
        # the run under the new one.
        release = run.receiver_counter.acquire()

        if include_events and run.event_sender is None and not run.closed:
            _logger.debug(
                "%s: First request for events, creating event channel.",
                self._stream_name,
            )
        try:
            receiver = run.subscribe(maxsize, warn_on_overflow, include_events)
        except BaseException:
            release()
            raise
        return _TrackedReceiver(receiver, release)

    @property
    def is_running(self) -> bool:
        """Return whether the streaming helper is running.

        This is False after `stop()`, and once the stream has ended, given up or
        failed. It is also False once every receiver handed out was closed or
        garbage-collected.

        Returns:
            Whether the streaming helper is running.
        """
        run = self._current_run
        return not (run.task.done() or run.receivers_gone)

    async def stop(self) -> None:
        """Stop the streaming helper."""
        _logger.info("%s: stopping the stream", self._stream_name)
        self._stop_requested = True
        tasks = [run.task for run in self._runs if not run.task.done()]
        for task in tasks:
            task.cancel()
        try:
            # Collects the runs' cancellations; a cancellation of the caller still
            # propagates.
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # A run cancelled before its first step never closes its own channels.
            for run in self._runs:
                await run.close()

    async def _run(self, run: "_Run[OutputT]") -> None:
        """Run the stream until it ends, gives up, fails or is cancelled.

        Args:
            run: The run to stream for.
        """
        try:
            await self._stream(run)
        except Exception as err:  # pylint: disable=broad-exception-caught
            _logger.exception("%s: unexpected error, stopping", self._stream_name)
            await run.send_event(StreamFatalError(err))
        finally:
            if run.receivers_gone:
                _logger.info("%s: all receivers are gone, stopping", self._stream_name)
            await run.close()

    async def _stream(self, run: "_Run[OutputT]") -> None:
        """Stream, retrying according to the retry strategy.

        Args:
            run: The run to stream for.
        """
        while True:
            error: Exception | None = None
            _logger.info("%s: starting to stream", self._stream_name)
            try:
                call = self._stream_method()

                await run.send_event(StreamStarted())

                async with contextlib.aclosing(self._call_messages(call)) as messages:
                    async for msg in messages:
                        run.retry_strategy.reset()
                        try:
                            transformed = self._transform(msg)
                        except Exception:  # pylint: disable=broad-exception-caught
                            _logger.exception(
                                "%s: error transforming message: %s",
                                self._stream_name,
                                msg,
                            )
                            continue

                        await run.data_sender.send(transformed)

            except (grpc.aio.AioRpcError, StreamIdleTimeoutError) as err:
                error = err

            if run.receivers_gone:
                return
            if error is None and not self._retry_on_exhausted_stream:
                _logger.info(
                    "%s: connection closed, stream exhausted", self._stream_name
                )
                return

            interval = run.retry_strategy.next_interval()
            error_str = f"Error: {error}" if error else "Stream exhausted"
            if interval is None:
                _logger.error(
                    "%s: connection ended, retry limit exceeded (%s), giving up. %s.",
                    self._stream_name,
                    run.retry_strategy.get_progress(),
                    error_str,
                )
                if error is not None:
                    await run.send_event(StreamFatalError(error))
                return
            _logger.warning(
                "%s: connection ended, retrying %s in %0.3f seconds. %s.",
                self._stream_name,
                run.retry_strategy.get_progress(),
                interval,
                error_str,
            )

            await run.send_event(StreamRetrying(timedelta(seconds=interval), error))
            await asyncio.sleep(interval)

    async def _call_messages(
        self, call: AsyncIterable[InputT]
    ) -> AsyncGenerator[InputT, None]:
        """Yield the messages of a call, enforcing the idle timeout.

        When this generator is closed before the call ends, e.g. on an idle
        timeout or when the broadcaster is stopped, the call is cancelled if it
        has a `cancel()` method. gRPC calls also cancel themselves when the
        cancellation reaches them while they wait for a message.

        Args:
            call: The call returned by the stream method.

        Yields:
            The messages of the call.

        Raises:
            StreamIdleTimeoutError: If no message arrives within the idle timeout.
            TimeoutError: If the call itself raises it.
        """
        idle_timeout = self._idle_timeout
        exhausted = False
        try:
            if idle_timeout is None:
                async for msg in call:
                    yield msg
                exhausted = True
                return
            iterator = aiter(call)
            while True:
                timer = asyncio.timeout(idle_timeout.total_seconds())
                try:
                    async with timer:
                        msg = await anext(iterator)
                except StopAsyncIteration:
                    exhausted = True
                    return
                except TimeoutError as err:
                    if not timer.expired():
                        raise
                    raise StreamIdleTimeoutError(
                        self._stream_name, idle_timeout
                    ) from err
                yield msg
        finally:
            if not exhausted:
                _cancel_call(call)


def _cancel_call(call: object) -> None:
    """Cancel a gRPC call, if the object supports it.

    Args:
        call: The object returned by the stream method.
    """
    cancel = getattr(call, "cancel", None)
    if callable(cancel):
        cancel()


# pylint: disable-next=too-many-instance-attributes
class _Run(Generic[OutputT]):
    """The channels, receiver counter and task of one run of a broadcaster's stream."""

    def __init__(
        self,
        name: str,
        retry_strategy: retry.Strategy,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Initialize the run.

        Args:
            name: The name prefix for the run's channels.
            retry_strategy: The retry strategy of this run.
            loop: The event loop the run streams on.
        """
        self._name = name
        self.retry_strategy = retry_strategy
        """The retry strategy of this run."""
        self._data_channel = channels.Broadcast[OutputT](name=f"{name}-Data")
        self.data_sender = self._data_channel.new_sender()
        """The sender of the data channel."""
        self._event_channel: channels.Broadcast[StreamEvent] | None = None
        self.event_sender: channels.Sender[StreamEvent] | None = None
        """The sender of the event channel, created on demand."""
        self.receiver_counter = _ReceiverCounter(self._on_receivers_gone, loop)
        """Counts the receivers handed out for this run."""
        self.receivers_gone = False
        """Whether every receiver was closed or dropped, which stops the run."""
        self.task: asyncio.Task[None]
        """The task streaming for this run."""

    def _on_receivers_gone(self) -> None:
        """Stop streaming, as every receiver handed out was closed or dropped."""
        if self.task.done() or self.receivers_gone:
            return
        self.receivers_gone = True
        self.task.cancel()

    def subscribe(
        self, maxsize: int, warn_on_overflow: bool, include_events: bool
    ) -> channels.Receiver[StreamEvent | OutputT]:
        """Create a receiver for the run's data, and its events if asked.

        Once the run is closed, only the data receiver is returned, and it ends at
        once.

        Args:
            maxsize: The maximum number of messages to buffer per channel.
            warn_on_overflow: Whether to log a warning when a message is dropped.
            include_events: Whether to also receive the stream events.

        Returns:
            The new receiver.
        """
        data_rx = self._data_channel.new_receiver(
            limit=maxsize, warn_on_overflow=warn_on_overflow
        )
        # An event channel created after `close()` would never be closed.
        if not include_events or self.closed:
            return data_rx
        if self._event_channel is None:
            self._event_channel = channels.Broadcast[StreamEvent](
                name=f"{self._name}-Events"
            )
            self.event_sender = self._event_channel.new_sender()
        event_rx = self._event_channel.new_receiver(
            limit=maxsize, warn_on_overflow=warn_on_overflow
        )
        return channels.merge(data_rx, event_rx)

    @property
    def closed(self) -> bool:
        """Whether the run's channels were closed."""
        return self._data_channel.is_closed

    async def send_event(self, event: StreamEvent) -> None:
        """Send an event to the event receivers, if there are any.

        Args:
            event: The event to send.
        """
        if self.event_sender is not None:
            await self.event_sender.send(event)

    async def close(self) -> None:
        """Close the channels, which ends the receivers."""
        await self._data_channel.aclose()
        if self._event_channel is not None:
            await self._event_channel.aclose()


class _ReceiverCounter:
    """Counts the receivers handed out that are not yet closed or dropped."""

    def __init__(
        self, on_all_gone: Callable[[], None], loop: asyncio.AbstractEventLoop
    ) -> None:
        """Initialize the counter.

        Args:
            on_all_gone: A bound method to call, on `loop`, when the last receiver
                is gone. It is held weakly, so receivers do not keep its object
                alive.
            loop: The event loop to count on.
        """
        self._on_all_gone = weakref.WeakMethod(on_all_gone)
        self._loop = loop
        self._open = 0

    def acquire(self) -> Callable[[], None]:
        """Count a new receiver.

        Returns:
            The function to call, once and from any thread, when the receiver is
                gone.
        """
        self._open += 1
        return functools.partial(_call_on_loop, self._loop, self._release)

    def _release(self) -> None:
        """Count a receiver as gone."""
        self._open -= 1
        on_all_gone = self._on_all_gone()
        if self._open == 0 and on_all_gone is not None:
            on_all_gone()


class _TrackedReceiver(channels.Receiver[_T]):
    """A receiver that reports when it is closed or garbage-collected."""

    def __init__(self, receiver: channels.Receiver[_T], release: Callable[[], None]):
        """Initialize the receiver.

        Args:
            receiver: The receiver to wrap.
            release: The function to call once the receiver is closed or dropped.
        """
        self._receiver = receiver
        self._release = weakref.finalize(self, release)
        # typeshed gives `finalize` empty `__slots__`, so mypy rejects this.
        self._release.atexit = False  # type: ignore[misc]

    async def ready(self) -> bool:
        """Wait until a message is ready.

        Returns:
            Whether a message is ready; False once the receiver has stopped.
        """
        return await self._receiver.ready()

    def consume(self) -> _T:
        """Return the message that is ready.

        Returns:
            The message.
        """
        return self._receiver.consume()

    def close(self) -> None:
        """Close the receiver."""
        try:
            self._receiver.close()
        finally:
            self._release()

    def __str__(self) -> str:
        """Return a string representation of the wrapped receiver."""
        return str(self._receiver)

    def __repr__(self) -> str:
        """Return a representation of the wrapped receiver."""
        return repr(self._receiver)


def _call_on_loop(loop: asyncio.AbstractEventLoop, func: Callable[[], None]) -> None:
    """Call a function on an event loop, from any thread.

    The call is immediate when made from the loop itself, and is dropped when the
    loop is already closed.

    Args:
        loop: The event loop to call the function on.
        func: The function to call.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        func()
        return
    with contextlib.suppress(RuntimeError):  # The loop is closed.
        loop.call_soon_threadsafe(func)
