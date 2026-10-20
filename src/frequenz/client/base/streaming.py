# License: MIT
# Copyright © 2023 Frequenz Energy-as-a-Service GmbH

"""Implementation of the grpc streaming helper."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import AsyncIterable, Generic, Literal, TypeAlias, TypeVar, overload

import grpc.aio

from frequenz import channels

from . import retry

_logger = logging.getLogger(__name__)


InputT = TypeVar("InputT")
"""The input type of the stream."""

OutputT = TypeVar("OutputT")
"""The output type of the stream."""


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


StreamEvent: TypeAlias = StreamStarted | StreamRetrying | StreamFatalError
"""Type alias for the events that can be sent over the stream."""


# pylint: disable-next=too-many-instance-attributes
class GrpcStreamBroadcaster(Generic[InputT, OutputT]):
    """Helper class to handle grpc streaming methods.

    This class handles the grpc streaming methods, automatically reconnecting
    when the connection is lost, and broadcasting the received messages to
    multiple receivers.

    The stream is started when the class is initialized, and can be stopped
    with the `stop` method. New receivers can be created with the
    `new_receiver` method, which will receive the streamed messages.

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
        """
        self._stream_name = stream_name
        self._stream_method = stream_method
        self._transform = transform
        self._retry_strategy = (
            retry.LinearBackoff() if retry_strategy is None else retry_strategy.copy()
        )
        self._retry_on_exhausted_stream = retry_on_exhausted_stream

        # Channel for transformed data messages (OutputT)
        self._data_channel: channels.Broadcast[OutputT] = channels.Broadcast(
            name=f"GrpcStreamBroadcaster-{stream_name}-Data"
        )

        # Channel for stream events (StreamEvent), created on demand
        self._event_channel: channels.Broadcast[StreamEvent] | None = None
        self._event_sender: channels.Sender[StreamEvent] | None = None
        self._task = asyncio.create_task(self._run())

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

    def new_receiver(
        self,
        *,
        maxsize: int = 50,
        warn_on_overflow: bool = True,
        include_events: bool = False,
    ) -> channels.Receiver[StreamEvent | OutputT]:
        """Create a new receiver for the stream.

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
        if not include_events:
            return self._data_channel.new_receiver(
                limit=maxsize, warn_on_overflow=warn_on_overflow
            )

        if self._event_channel is None:
            _logger.debug(
                "%s: First request for events, creating event channel.",
                self._stream_name,
            )
            self._event_channel = channels.Broadcast[StreamEvent](
                name=f"GrpcStreamBroadcaster-{self._stream_name}-Events"
            )
            self._event_sender = self._event_channel.new_sender()

        data_rx = self._data_channel.new_receiver(
            limit=maxsize, warn_on_overflow=warn_on_overflow
        )
        event_rx = self._event_channel.new_receiver(
            limit=maxsize, warn_on_overflow=warn_on_overflow
        )
        return channels.merge(data_rx, event_rx)

    @property
    def is_running(self) -> bool:
        """Return whether the streaming helper is running.

        Returns:
            Whether the streaming helper is running.
        """
        return not self._task.done()

    async def stop(self) -> None:
        """Stop the streaming helper."""
        _logger.info("%s: stopping the stream", self._stream_name)
        if self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        await self._data_channel.aclose()
        if self._event_channel is not None:
            await self._event_channel.aclose()

    async def _run(self) -> None:
        """Run the streaming helper."""
        data_sender = self._data_channel.new_sender()

        while True:
            error: Exception | None = None
            _logger.info("%s: starting to stream", self._stream_name)
            try:
                call = self._stream_method()

                if self._event_sender:
                    await self._event_sender.send(StreamStarted())

                async for msg in call:
                    self._retry_strategy.reset()
                    try:
                        transformed = self._transform(msg)
                    except Exception:  # pylint: disable=broad-exception-caught
                        _logger.exception(
                            "%s: error transforming message: %s",
                            self._stream_name,
                            msg,
                        )
                        continue

                    await data_sender.send(transformed)

            except grpc.aio.AioRpcError as err:
                error = err

            if error is None and not self._retry_on_exhausted_stream:
                _logger.info(
                    "%s: connection closed, stream exhausted", self._stream_name
                )
                await self._data_channel.aclose()
                if self._event_channel is not None:
                    await self._event_channel.aclose()
                break

            interval = self._retry_strategy.next_interval()
            error_str = f"Error: {error}" if error else "Stream exhausted"
            if interval is None:
                _logger.error(
                    "%s: connection ended, retry limit exceeded (%s), giving up. %s.",
                    self._stream_name,
                    self._retry_strategy.get_progress(),
                    error_str,
                )
                if error is not None and self._event_sender:
                    await self._event_sender.send(StreamFatalError(error))
                await self._data_channel.aclose()
                if self._event_channel is not None:
                    await self._event_channel.aclose()
                break
            _logger.warning(
                "%s: connection ended, retrying %s in %0.3f seconds. %s.",
                self._stream_name,
                self._retry_strategy.get_progress(),
                interval,
                error_str,
            )

            if self._event_sender:
                await self._event_sender.send(
                    StreamRetrying(timedelta(seconds=interval), error)
                )
            await asyncio.sleep(interval)
