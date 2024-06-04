# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Base class for API clients."""

import abc
from collections.abc import Callable
from typing import Any, Generic, Self, TypeVar

from .channel import ChannelT, parse_grpc_uri
from .exception import ClientNotConnected

StubT = TypeVar("StubT")
"""The type of the gRPC stub."""


class BaseApiClient(abc.ABC, Generic[StubT, ChannelT]):
    """A base class for API clients.

    This class provides a common interface for API clients that communicate with a API
    server. It is designed to be subclassed by specific API clients that provide a more
    specific interface.
    """

    def __init__(
        self,
        server_url: str,
        create_stub: Callable[[ChannelT], StubT],
        channel_type: type[ChannelT],
        *,
        auto_connect: bool = True,
    ) -> None:
        """Create an instance and connect to the server.

        Args:
            server_url: The URL of the server to connect to.
            create_stub: A function that creates a stub from a channel.
            channel_type: The type of channel to use.
            auto_connect: Whether to automatically connect to the server. If `False`, the
                client will not connect to the server until
                [connect()][frequenz.client.base.client.BaseApiClient.connect] is
                called.
        """
        self._server_url: str = server_url
        self._create_stub: Callable[[ChannelT], StubT] = create_stub
        self._channel_type: type[ChannelT] = channel_type
        self._channel: ChannelT | None = None
        self._stub: StubT | None = None
        if auto_connect:
            self.connect(server_url)

    @property
    def server_url(self) -> str:
        """The URL of the server."""
        return self._server_url

    @property
    def channel(self) -> ChannelT:
        """The underlying gRPC channel used to communicate with the server.

        Warning:
            This channel is provided as a last resort for advanced users. It is not
            recommended to use this property directly unless you know what you are
            doing and you don't care about being tied to a specific gRPC library.

        Raises:
            ClientNotConnected: If the client is not connected to the server.
        """
        if self._channel is None:
            raise ClientNotConnected(server_url=self.server_url, operation="channel")
        return self._channel

    @property
    def stub(self) -> StubT:
        """The underlying gRPC stub.

        Warning:
            This stub is provided as a last resort for advanced users. It is not
            recommended to use this property directly unless you know what you are
            doing and you don't care about being tied to a specific gRPC library.

        Raises:
            ClientNotConnected: If the client is not connected to the server.
        """
        if self._stub is None:
            raise ClientNotConnected(server_url=self.server_url, operation="stub")
        return self._stub

    @property
    def is_connected(self) -> bool:
        """Whether the client is connected to the server."""
        return self._channel is not None

    def connect(self, server_url: str | None = None) -> None:
        """Connect to the server, possibly using a new URL.

        If the client is already connected and the URL is the same as the previous URL,
        this method does nothing. If you want to force a reconnection, you can call
        [disconnect()][frequenz.client.base.client.BaseApiClient.disconnect] first.

        Args:
            server_url: The URL of the server to connect to. If not provided, the
                previously used URL is used.
        """
        if server_url is not None and server_url != self._server_url:  # URL changed
            self._server_url = server_url
        elif self.is_connected:
            return
        self._channel = parse_grpc_uri(self._server_url, self._channel_type)
        self._stub = self._create_stub(self._channel)

    async def disconnect(self) -> None:
        """Disconnect from the server.

        If the client is not connected, this method does nothing.
        """
        await self.__aexit__(None, None, None)

    async def __aenter__(self) -> Self:
        """Enter a context manager."""
        self.connect()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: Any | None,
    ) -> bool | None:
        """Exit a context manager."""
        if self._channel is None:
            return None
        # We need to ignore the return type here because the __aexit__ method of grpclib
        # is not annotated correctly, it is annotated to return None but __aexit__
        # should return a bool | None. This should be harmless if grpclib never handle
        # any exceptions in __aexit__, so it is just a type checker issue. This is the
        # error produced by mypy:
        # Function does not return a value (it only ever returns None)
        # [func-returns-value]
        # See https://github.com/vmagamedov/grpclib/issues/193 for more details.
        result = await self._channel.__aexit__(_exc_type, _exc_val, _exc_tb)
        self._channel = None
        self._stub = None
        return result
