# License: MIT
# Copyright © 2023 Frequenz Energy-as-a-Service GmbH

"""Implementation of the grpc streaming helper."""

import asyncio
import logging
import typing

import grpc
from grpc.aio import UnaryStreamCall  # type: ignore[import]

from frequenz import channels

from . import retry_strategy

_logger = logging.getLogger(__name__)


_InputT = typing.TypeVar("_InputT")
_OutputT = typing.TypeVar("_OutputT")


class GrpcStreamingHelper(typing.Generic[_InputT, _OutputT]):
    """Helper class to handle grpc streaming methods."""

    def __init__(
        self,
        stream_name: str,
        stream_method: typing.Callable[[], UnaryStreamCall[typing.Any, _InputT]],
        transform: typing.Callable[[_InputT], _OutputT],
        retry_spec: retry_strategy.RetryStrategy | None = None,
    ):
        """Initialize the streaming helper.

        Args:
            stream_name: A name to identify the stream in the logs.
            stream_method: A function that returns the grpc stream. This function is
                called everytime the connection is lost and we want to retry.
            transform: A function to transform the input type to the output type.
            retry_spec: The retry strategy to use, when the connection is lost. Defaults
                to retries every 3 seconds, with a jitter of 1 second, indefinitely.
        """
        self._stream_name = stream_name
        self._stream_method = stream_method
        self._transform = transform
        self._retry_spec = (
            retry_strategy.LinearBackoff() if retry_spec is None else retry_spec.copy()
        )

        self._channel: channels.Broadcast[_OutputT] = channels.Broadcast(
            f"GrpcStreamingHelper-{stream_name}"
        )
        self._task = asyncio.create_task(self._run())

    def new_receiver(self, maxsize: int = 50) -> channels.Receiver[_OutputT]:
        """Create a new receiver for the stream.

        Args:
            maxsize: The maximum number of messages to buffer.

        Returns:
            A new receiver.
        """
        return self._channel.new_receiver(maxsize=maxsize)

    async def stop(self) -> None:
        """Stop the streaming helper."""
        if self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        await self._channel.close()

    async def _run(self) -> None:
        """Run the streaming helper."""
        sender = self._channel.new_sender()

        while True:
            _logger.debug("Making call to grpc streaming method: %s", self._stream_name)

            try:
                call = self._stream_method()
                async for msg in call:
                    await sender.send(self._transform(msg))
            except grpc.aio.AioRpcError:
                _logger.exception(
                    "Error in grpc streaming method: %s", self._stream_name
                )
            if interval := self._retry_spec.next_interval():
                _logger.warning(
                    "`%s`, connection ended, retrying %s in %0.3f seconds.",
                    self._stream_name,
                    self._retry_spec.get_progress(),
                    interval,
                )
                await asyncio.sleep(interval)
            else:
                _logger.warning(
                    "`%s`, connection ended, retry limit exceeded %s.",
                    self._stream_name,
                    self._retry_spec.get_progress(),
                )
                await self._channel.close()
                break
