# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Handling of gRPC channels."""

from typing import TypeVar
from urllib.parse import parse_qs, urlparse

from . import _grpchacks


def _to_bool(value: str) -> bool:
    value = value.lower()
    if value in ("true", "on", "1"):
        return True
    if value in ("false", "off", "0"):
        return False
    raise ValueError(f"Invalid boolean value '{value}'")


ChannelT = TypeVar("ChannelT", _grpchacks.GrpclibChannel, _grpchacks.GrpcioChannel)
"""A `grpclib` or `grpcio` channel type."""


def parse_grpc_uri(
    uri: str, channel_type: type[ChannelT], /, *, default_port: int = 9090
) -> ChannelT:
    """Create a grpclib client channel from a URI.

    The URI must have the following format:

    ```
    grpc://hostname[:port][?ssl=false]
    ```

    A few things to consider about URI components:

    - If any other components are present in the URI, a [`ValueError`][] is raised.
    - If the port is omitted, the `default_port` is used.
    - If a query parameter is passed many times, the last value is used.
    - The only supported query parameter is `ssl`, which must be a boolean value and
      defaults to `false`.
    - Boolean query parameters can be specified with the following values
      (case-insensitive): `true`, `1`, `on`, `false`, `0`, `off`.

    Args:
        uri: The gRPC URI specifying the connection parameters.
        channel_type: The type of channel to create.
        default_port: The default port number to use if the URI does not specify one.

    Returns:
        A grpclib client channel object.

    Raises:
        ValueError: If the URI is invalid or contains unexpected components.
    """
    parsed_uri = urlparse(uri)
    if parsed_uri.scheme != "grpc":
        raise ValueError(
            f"Invalid scheme '{parsed_uri.scheme}' in the URI, expected 'grpc'", uri
        )
    if not parsed_uri.hostname:
        raise ValueError(f"Host name is missing in URI '{uri}'", uri)
    for attr in ("path", "fragment", "params", "username", "password"):
        if getattr(parsed_uri, attr):
            raise ValueError(
                f"Unexpected {attr} '{getattr(parsed_uri, attr)}' in the URI '{uri}'",
                uri,
            )

    options = {k: v[-1] for k, v in parse_qs(parsed_uri.query).items()}
    ssl = _to_bool(options.pop("ssl", "false"))
    if options:
        raise ValueError(
            f"Unexpected query parameters {options!r} in the URI '{uri}'",
            uri,
        )

    host = parsed_uri.hostname
    port = parsed_uri.port or default_port
    match channel_type:
        case _grpchacks.GrpcioChannel:
            target = f"{host}:{port}"
            return (
                _grpchacks.grpcio_secure_channel(
                    target, _grpchacks.grpcio_ssl_channel_credentials()
                )
                if ssl
                else _grpchacks.grpcio_insecure_channel(target)
            )
        case _grpchacks.GrpclibChannel:
            return _grpchacks.GrpclibChannel(host=host, port=port, ssl=ssl)
        case _:
            assert False, "Unexpected channel type: {channel_type}"
