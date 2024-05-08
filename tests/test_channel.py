# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Test cases for the channel module."""

import unittest.mock
from dataclasses import dataclass

import pytest

from frequenz.client.base.channel import parse_grpc_uri


@dataclass(frozen=True)
class _FakeChannel:
    host: str
    port: int
    ssl: bool


@pytest.mark.parametrize(
    "uri, host, port, ssl",
    [
        ("grpc://localhost", "localhost", 9090, False),
        ("grpc://localhost:1234", "localhost", 1234, False),
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
    ],
)
def test_parse_uri_ok(
    uri: str,
    host: str,
    port: int,
    ssl: bool,
) -> None:
    """Test successful parsing of gRPC URIs."""
    with unittest.mock.patch(
        "frequenz.client.base.channel.Channel",
        return_value=_FakeChannel(host, port, ssl),
    ):
        channel = parse_grpc_uri(uri)

    assert isinstance(channel, _FakeChannel)
    assert channel.host == host
    assert channel.port == port
    assert channel.ssl == ssl


@pytest.mark.parametrize(
    "uri, error_msg",
    [
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
            "Unexpected query parameters {'ffl': 'true'}",
        ),
    ],
)
def test_parse_uri_error(uri: str, error_msg: str) -> None:
    """Test parsing of invalid gRPC URIs."""
    with pytest.raises(ValueError, match=error_msg):
        parse_grpc_uri(uri)
