# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Test cases for the channel module."""

import dataclasses
import pathlib
from unittest import mock

import pytest
from grpc import ssl_channel_credentials
from grpc.aio import Channel

from frequenz.client.base.channel import (
    ChannelOptions,
    SslOptions,
    _to_bool,
    parse_grpc_uri,
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class _ValidUrlTestCase:
    title: str
    uri: str
    expected_host: str
    expected_port: int | None
    expected_options: ChannelOptions
    defaults: ChannelOptions = ChannelOptions()


@pytest.mark.parametrize(
    "case",
    [
        _ValidUrlTestCase(
            title="default",
            uri="grpc://localhost:9090",
            expected_host="localhost",
            expected_port=9090,
            expected_options=ChannelOptions(
                ssl=SslOptions(
                    enabled=True,
                    root_certificates=None,
                    private_key=None,
                    certificate_chain=None,
                ),
            ),
        ),
        _ValidUrlTestCase(
            title="default with default port",
            uri="grpc://localhost",
            expected_host="localhost",
            expected_port=9090,
            expected_options=ChannelOptions(
                ssl=SslOptions(
                    enabled=True,
                    root_certificates=None,
                    private_key=None,
                    certificate_chain=None,
                ),
            ),
            defaults=ChannelOptions(port=9090),
        ),
        _ValidUrlTestCase(
            title="default no SSL defaults",
            uri="grpc://localhost:2355",
            defaults=ChannelOptions(ssl=SslOptions(enabled=False)),
            expected_host="localhost",
            expected_port=2355,
            expected_options=ChannelOptions(
                ssl=SslOptions(
                    enabled=False,
                    root_certificates=None,
                    private_key=None,
                    certificate_chain=None,
                ),
            ),
        ),
        _ValidUrlTestCase(
            title="default with SSL defaults",
            uri="grpc://localhost:2355",
            defaults=ChannelOptions(
                ssl=SslOptions(
                    enabled=True,
                    root_certificates=None,
                    private_key=b"key",
                    certificate_chain=pathlib.Path("/chain"),
                ),
            ),
            expected_host="localhost",
            expected_port=2355,
            expected_options=ChannelOptions(
                ssl=SslOptions(
                    enabled=True,
                    root_certificates=None,
                    private_key=b"key",
                    certificate_chain=pathlib.Path("/chain"),
                ),
            ),
        ),
        _ValidUrlTestCase(
            title="complete no defaults",
            uri="grpc://localhost:1234?ssl=1&ssl_root_certificates_path=/root_cert"
            "&ssl_private_key_path=/key&ssl_certificate_chain_path=/chain",
            expected_host="localhost",
            expected_port=1234,
            expected_options=ChannelOptions(
                ssl=SslOptions(
                    enabled=True,
                    root_certificates=pathlib.Path("/root_cert"),
                    private_key=pathlib.Path("/key"),
                    certificate_chain=pathlib.Path("/chain"),
                ),
            ),
        ),
        _ValidUrlTestCase(
            title="complete no defaults",
            uri="grpc://localhost:1234?ssl=1&ssl_root_certificates_path=/root_cert"
            "&ssl_private_key_path=/key&ssl_certificate_chain_path=/chain",
            defaults=ChannelOptions(
                ssl=SslOptions(
                    enabled=True,
                    root_certificates=pathlib.Path("/root_cert_def"),
                    private_key=b"key_def",
                    certificate_chain=b"chain_def",
                ),
            ),
            expected_host="localhost",
            expected_port=1234,
            expected_options=ChannelOptions(
                ssl=SslOptions(
                    enabled=True,
                    root_certificates=pathlib.Path("/root_cert"),
                    private_key=pathlib.Path("/key"),
                    certificate_chain=pathlib.Path("/chain"),
                ),
            ),
        ),
    ],
    ids=lambda case: case.title,
)
def test_parse_uri_ok(  # pylint: disable=too-many-locals
    case: _ValidUrlTestCase,
) -> None:
    """Test successful parsing of gRPC URIs using grpcio."""
    uri = case.uri
    defaults = case.defaults

    expected_host = case.expected_host
    expected_options = case.expected_options
    expected_channel = mock.MagicMock(name="mock_channel", spec=Channel)
    expected_credentials = mock.MagicMock(
        name="mock_credentials", spec=ssl_channel_credentials
    )
    expected_port = case.expected_port
    expected_ssl = (
        expected_options.ssl.enabled
        if "ssl=" in uri or defaults.ssl.enabled is None
        else defaults.ssl.enabled
    )
    expected_root_certificates = (
        expected_options.ssl.root_certificates
        if "ssl_root_certificates_path=" in uri
        or defaults.ssl.root_certificates is None
        else defaults.ssl.root_certificates
    )
    expected_private_key = (
        expected_options.ssl.private_key
        if "ssl_private_key_path=" in uri or defaults.ssl.private_key is None
        else defaults.ssl.private_key
    )
    expected_certificate_chain = (
        expected_options.ssl.certificate_chain
        if "ssl_certificate_chain_path=" in uri
        or defaults.ssl.certificate_chain is None
        else defaults.ssl.certificate_chain
    )

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
        mock.patch(
            "frequenz.client.base.channel._read_bytes",
            return_value=b"contents",
        ) as get_contents_mock,
    ):
        channel = parse_grpc_uri(uri, defaults)

    assert channel == expected_channel
    expected_target = f"{expected_host}:{expected_port}"
    if expected_ssl:
        if isinstance(expected_root_certificates, pathlib.Path):
            get_contents_mock.assert_any_call(
                "root certificates",
                expected_root_certificates,
            )
            expected_root_certificates = b"contents"
        if isinstance(expected_private_key, pathlib.Path):
            get_contents_mock.assert_any_call(
                "private key",
                expected_private_key,
            )
            expected_private_key = b"contents"
        if isinstance(expected_certificate_chain, pathlib.Path):
            get_contents_mock.assert_any_call(
                "certificate chain",
                expected_certificate_chain,
            )
            expected_certificate_chain = b"contents"
        ssl_channel_credentials_mock.assert_called_once_with(
            root_certificates=expected_root_certificates,
            private_key=expected_private_key,
            certificate_chain=expected_certificate_chain,
        )
        secure_channel_mock.assert_called_once_with(
            expected_target, expected_credentials
        )
    else:
        insecure_channel_mock.assert_called_once_with(expected_target)


@pytest.mark.parametrize("value", ["true", "on", "1", "TrUe", "On", "ON", "TRUE"])
def test_to_bool_true(value: str) -> None:
    """Test conversion of valid boolean values to True."""
    assert _to_bool(value) is True


@pytest.mark.parametrize("value", ["false", "off", "0", "FaLsE", "Off", "OFF", "FALSE"])
def test_to_bool_false(value: str) -> None:
    """Test conversion of valid boolean values to False."""
    assert _to_bool(value) is False


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
    (
        "grpc://localhost:1234?ssl=0&ssl_root_certificates_path=/root&"
        "ssl_private_key_path=/key&ssl_certificate_chain_path=/chain",
        r"Option\(s\) ssl_root_certificates_path, ssl_private_key_path, "
        r"ssl_certificate_chain_path found in URI 'grpc://localhost:1234\?"
        r"ssl=0\&ssl_root_certificates_path=/root\&"
        r"ssl_private_key_path=/key\&ssl_certificate_chain_path=/chain', "
        r"but SSL is disabled",
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


def test_invalid_url_no_default_port() -> None:
    """Test parsing of invalid gRPC URIs for grpclib."""
    uri = "grpc://localhost"
    with pytest.raises(
        ValueError,
        match=r"The gRPC URI 'grpc://localhost' doesn't specify a port and there is no default.",
    ):
        parse_grpc_uri(uri)
