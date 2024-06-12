# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Hacks to deal with multiple grpc libraries.

This module conditionally imports symbols from the `grpclib` and `grpcio` libraries,
assigning them a new name.

for `grpclib`:

- `GrpclibError` for `grpclib.GRPCError`
- `GrpclibChannel` for `grpclib.client.Channel`

For `grpcio`:

- `GrpcioError` for `grpc.aio.AioRpcError`
- `GrpcioChannel` for `grpc.aio.Channel`
- `GrpcioSslChannelCredentials` for `grpc.ssl_channel_credentials`
- `grpcio_insecure_channel` for `grpc.aio.insecure_channel`
- `grpcio_secure_channel` for `grpc.aio.secure_channel`

If the libraries are not installed, the module defines dummy symbols with the same names
to avoid import errors.

This way exceptions code can be written to work with both libraries assuming both are
aviailable, and the correct symbols will be imported at runtime.
"""


from typing import Any, AsyncContextManager, Self

__all__ = [
    "GrpcioChannel",
    "GrpcioChannelCredentials",
    "GrpcioError",
    "GrpclibChannel",
    "GrpclibError",
    "grpcio_insecure_channel",
    "grpcio_secure_channel",
    "grpcio_ssl_channel_credentials",
]

try:
    import grpclib.client
    from grpclib import GRPCError as GrpclibError
    from grpclib.client import Channel as GrpclibChannel

    def grpclib_create_channel(host: str, port: int, ssl: bool) -> Any:
        """Create a channel."""
        return grpclib.client.Channel(host=host, port=port, ssl=ssl)

except ImportError:

    class GrpclibError(Exception):  # type: ignore[no-redef]
        """A dummy class to avoid import errors.

        This class will never be actually used, as it is only used for catching
        exceptions from the grpclib library. If the grpclib library is not installed,
        this class will never be instantiated.
        """

    class GrpclibChannel:  # type: ignore[no-redef]
        """A dummy class to avoid import errors.

        This class will never be actually used, as it is only used for catching
        exceptions from the grpclib library. If the grpclib library is not installed,
        this class will never be instantiated.
        """

        def __init__(self, target: str):
            """Create an instance."""

        async def __aenter__(self) -> Self:
            """Enter a context manager."""
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc_val: BaseException | None,
            _exc_tb: Any | None,
        ) -> bool | None:
            """Exit a context manager."""
            return None


try:
    from grpc import ChannelCredentials as GrpcioChannelCredentials
    from grpc import ssl_channel_credentials as grpcio_ssl_channel_credentials
    from grpc.aio import AioRpcError as GrpcioError
    from grpc.aio import Channel as GrpcioChannel
    from grpc.aio import insecure_channel as grpcio_insecure_channel
    from grpc.aio import secure_channel as grpcio_secure_channel

    def grpcio_create_channel(
        host: str, port: int, ssl: bool
    ) -> AsyncContextManager[Any]:
        """Create a channel."""
        if not ssl:
            return grpcio_insecure_channel(f"{host}:{port}")
        return grpcio_secure_channel(f"{host}:{port}", grpcio_ssl_channel_credentials())

except ImportError:

    class GrpcioError(Exception):  # type: ignore[no-redef]
        """A dummy class to avoid import errors.

        This class will never be actually used, as it is only used for catching
        exceptions from the grpc library. If the grpc library is not installed,
        this class will never be instantiated.
        """

    class GrpcioChannel:  # type: ignore[no-redef]
        """A dummy class to avoid import errors.

        This class will never be actually used, as it is only used for catching
        exceptions from the grpc library. If the grpc library is not installed,
        this class will never be instantiated.
        """

        async def __aenter__(self) -> Self:
            """Enter a context manager."""
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc_val: BaseException | None,
            _exc_tb: Any | None,
        ) -> bool | None:
            """Exit a context manager."""
            return None

    def grpcio_create_channel(
        host: str, port: int, ssl: bool  # pylint: disable=unused-argument
    ) -> AsyncContextManager[Any]:
        """Create a channel."""
        return GrpcioChannel()
