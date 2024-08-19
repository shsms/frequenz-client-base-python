# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Handling of gRPC channels."""

import dataclasses
import pathlib
from typing import assert_never
from urllib.parse import parse_qs, urlparse

from grpc import ssl_channel_credentials
from grpc.aio import Channel, insecure_channel, secure_channel


@dataclasses.dataclass(frozen=True)
class SslOptions:
    """SSL options for a gRPC channel."""

    enabled: bool = True
    """Whether SSL should be enabled."""

    root_certificates: pathlib.Path | bytes | None = None
    """The PEM-encoded root certificates.

    This can be a path to a file containing the certificates, a byte string, or None to
    retrieve them from a default location chosen by gRPC runtime.
    """


@dataclasses.dataclass(frozen=True)
class ChannelOptions:
    """Options for a gRPC channel."""

    port: int = 9090
    """The port number to connect to."""

    ssl: SslOptions = SslOptions()
    """SSL options for the channel."""


def parse_grpc_uri(
    uri: str,
    /,
    defaults: ChannelOptions = ChannelOptions(),
) -> Channel:
    """Create a client channel from a URI.

    The URI must have the following format:

    ```
    grpc://hostname[:port][?param=value&...]
    ```

    A few things to consider about URI components:

    - If any other components are present in the URI, a [`ValueError`][] is raised.
    - If the port is omitted, the `default_port` is used.
    - If a query parameter is passed many times, the last value is used.
    - Boolean query parameters can be specified with the following values
      (case-insensitive): `true`, `1`, `on`, `false`, `0`, `off`.

    Supported query parameters:

    - `ssl` (bool): Enable or disable SSL. Defaults to `default_ssl`.
    - `ssl_root_certificates_path` (str): Path to the root certificates file. Only
      valid if SSL is enabled. Will raise a `ValueError` if the file cannot be read.

    Args:
        uri: The gRPC URI specifying the connection parameters.
        defaults: The default options use to create the channel when not specified in
            the URI.

    Returns:
        A client channel object.

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

    options = _parse_query_params(uri, parsed_uri.query)

    host = parsed_uri.hostname
    port = parsed_uri.port or defaults.port
    target = f"{host}:{port}"

    ssl = defaults.ssl.enabled if options.ssl is None else options.ssl
    if ssl:
        return secure_channel(
            target,
            ssl_channel_credentials(
                root_certificates=_get_contents(
                    "root certificates",
                    options.ssl_root_certificates_path,
                    defaults.ssl.root_certificates,
                )
            ),
        )
    return insecure_channel(target)


def _to_bool(value: str) -> bool:
    value = value.lower()
    if value in ("true", "on", "1"):
        return True
    if value in ("false", "off", "0"):
        return False
    raise ValueError(f"Invalid boolean value '{value}'")


@dataclasses.dataclass(frozen=True)
class _QueryParams:
    ssl: bool | None
    ssl_root_certificates_path: pathlib.Path | None


def _parse_query_params(uri: str, query_string: str) -> _QueryParams:
    """Parse query parameters from a URI.

    Args:
        uri: The URI from which the query parameters were extracted.
        query_string: The query string to parse.

    Returns:
        A `_QueryParams` object with the parsed query parameters.

    Raises:
        ValueError: If the query string contains unexpected components.
    """
    options = {k: v[-1] for k, v in parse_qs(query_string).items()}
    ssl_option = options.pop("ssl", None)
    ssl: bool | None = None
    if ssl_option is not None:
        ssl = _to_bool(ssl_option)

    ssl_root_cert_path = options.pop("ssl_root_certificates_path", None)
    if ssl is False and ssl_root_cert_path is not None:
        raise ValueError(
            f"'ssl_root_certificates_path' option found in URI {uri!r}, but SSL is disabled",
        )

    if options:
        names = ", ".join(options)
        raise ValueError(
            f"Unexpected query parameters [{names}] in the URI '{uri}'",
            uri,
        )

    return _QueryParams(
        ssl=ssl,
        ssl_root_certificates_path=(
            pathlib.Path(ssl_root_cert_path) if ssl_root_cert_path else None
        ),
    )


def _get_contents(
    name: str, source: pathlib.Path | None, default: pathlib.Path | bytes | None
) -> bytes | None:
    """Get the contents of a file or use a default value.

    If the `source` is `None`, the `default` value is used instead. If the source (or
    default) is a path, the contents of the file are returned. If the source is a byte
    string (or default) the byte string is returned without doing any reading.

    Args:
        name: The name of the contents (used for error messages).
        source: The source of the contents.
        default: The default value to use if the source is None.

    Returns:
        The contents of the source file or the default value.

    Raises:
        ValueError: If the file cannot be read.
    """
    file_path: pathlib.Path
    match source:
        case None:
            match default:
                case None:
                    return None
                case bytes() as default_bytes:
                    return default_bytes
                case pathlib.Path() as file_path:
                    pass
                case unexpected:
                    assert_never(unexpected)
        case pathlib.Path() as file_path:
            pass
        case unexpected:
            assert_never(unexpected)
    try:
        return file_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Failed to read {name} from '{file_path}': {exc}") from exc
