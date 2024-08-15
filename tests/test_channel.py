# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Test cases for the channel module."""

from typing import NotRequired, TypedDict
from unittest import mock

import pytest
from grpc import ssl_channel_credentials
from grpc.aio import Channel

from frequenz.client.base.channel import parse_grpc_uri

VALID_URLS = [
    ("grpc://localhost", "localhost", 9090, True),
    ("grpc://localhost:1234", "localhost", 1234, True),
    ("grpc://localhost:1234?ssl=true", "localhost", 1234, True),
    ("grpc://localhost:1234?ssl=false", "localhost", 1234, False),
    ("grpc://localhost:1234?ssl=1", "localhost", 1234, True),
    ("grpc://localhost:1234?ssl=0", "localhost", 1234, False),
    ("grpc://localhost:1234?ssl=on", "localhost", 1234, True),
    ("grpc://localhost:1234?ssl=off", "localhost", 1234, False),
    ("grpc://localhost:1234?ssl=TRUE", "localhost", 1234, True),
    ("grpc://localhost:1234?ssl=FALSE", "localhost", 1234, False),
    ("grpc://localhost:1234?ssl=ON", "localhost", 1234, True),
    ("grpc://localhost:1234?ssl=OFF", "localhost", 1234, False),
    ("grpc://localhost:1234?ssl=0&ssl=1", "localhost", 1234, True),
    ("grpc://localhost:1234?ssl=1&ssl=0", "localhost", 1234, False),
]


class _CreateChannelKwargs(TypedDict):
    default_port: NotRequired[int]
    default_ssl: NotRequired[bool]


@pytest.mark.parametrize("uri, host, port, ssl", VALID_URLS)
@pytest.mark.parametrize(
    "default_port", [None, 9090, 1234], ids=lambda x: f"default_port={x}"
)
@pytest.mark.parametrize(
    "default_ssl", [None, True, False], ids=lambda x: f"default_ssl={x}"
)
def test_parse_uri_ok(  # pylint: disable=too-many-arguments,too-many-locals
    uri: str,
    host: str,
    port: int,
    ssl: bool,
    default_port: int | None,
    default_ssl: bool | None,
) -> None:
    """Test successful parsing of gRPC URIs using grpcio."""
    expected_channel = mock.MagicMock(name="mock_channel", spec=Channel)
    expected_credentials = mock.MagicMock(
        name="mock_credentials", spec=ssl_channel_credentials
    )
    expected_port = port if f":{port}" in uri or default_port is None else default_port
    expected_ssl = ssl if "ssl" in uri or default_ssl is None else default_ssl

    kwargs = _CreateChannelKwargs()
    if default_port is not None:
        kwargs["default_port"] = default_port
    if default_ssl is not None:
        kwargs["default_ssl"] = default_ssl

    with (
        mock.patch(
            "frequenz.client.base.channel.insecure_channel",
            return_value=expected_channel,
        ) as insecure_channel_mock,
        mock.patch(
            "frequenz.client.base.channel.secure_channel",
            return_value=expected_channel,
        ) as secure_channel_mock,
        mock.patch(
            "frequenz.client.base.channel.ssl_channel_credentials",
            return_value=expected_credentials,
        ) as ssl_channel_credentials_mock,
    ):
        channel = parse_grpc_uri(uri, **kwargs)

    assert channel == expected_channel
    expected_target = f"{host}:{expected_port}"
    if expected_ssl:
        ssl_channel_credentials_mock.assert_called_once_with(root_certificates=None)
        secure_channel_mock.assert_called_once_with(
            expected_target, expected_credentials
        )
    else:
        insecure_channel_mock.assert_called_once_with(expected_target)


INVALID_URLS = [
    ("http://localhost", "Invalid scheme 'http' in the URI, expected 'grpc'"),
    ("grpc://", "Host name is missing in URI 'grpc://'"),
    ("grpc://localhost:1234?ssl=invalid", "Invalid boolean value 'invalid'"),
    ("grpc://localhost:1234?ssl=1&ssl=invalid", "Invalid boolean value 'invalid'"),
    ("grpc://:1234", "Host name is missing"),
    ("grpc://host:1234;param", "Port could not be cast to integer value"),
    ("grpc://host:1234/path", "Unexpected path '/path'"),
    ("grpc://host:1234#frag", "Unexpected fragment 'frag'"),
    ("grpc://user@host:1234", "Unexpected username 'user'"),
    ("grpc://:pass@host:1234?user:pass", "Unexpected password 'pass'"),
    (
        "grpc://localhost?ssl=1&ssl=1&ssl=invalid",
        "Invalid boolean value 'invalid'",
    ),
    (
        "grpc://localhost:1234?ssl=1&ffl=true",
        r"Unexpected query parameters \[ffl\]",
    ),
]


@pytest.mark.parametrize("uri, error_msg", INVALID_URLS)
def test_parse_uri_error(
    uri: str,
    error_msg: str,
) -> None:
    """Test parsing of invalid gRPC URIs for grpclib."""
    with pytest.raises(ValueError, match=error_msg):
        parse_grpc_uri(uri)
