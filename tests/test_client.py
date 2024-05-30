# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Tests for the BaseApiClient class."""

from dataclasses import dataclass
from unittest import mock

import pytest
import pytest_mock

from frequenz.client.base import _grpchacks
from frequenz.client.base.channel import ChannelT
from frequenz.client.base.client import BaseApiClient


def _get_full_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__name__}"


def _auto_connect_name(auto_connect: bool) -> str:
    return f"{auto_connect=}"


@dataclass(kw_only=True, frozen=True)
class _ClientMocks:
    stub: mock.MagicMock
    create_stub: mock.MagicMock
    channel: mock.MagicMock
    parse_grpc_uri: mock.MagicMock


_DEFAULT_SERVER_URL = "grpc://localhost"


def create_client_with_mocks(
    mocker: pytest_mock.MockFixture,
    channel_type: type[ChannelT],
    *,
    auto_connect: bool = True,
    server_url: str = _DEFAULT_SERVER_URL,
) -> tuple[BaseApiClient[mock.MagicMock, ChannelT], _ClientMocks]:
    """Create a BaseApiClient instance with mocks."""
    mock_stub = mock.MagicMock(name="stub")
    mock_create_stub = mock.MagicMock(name="create_stub", return_value=mock_stub)
    mock_channel = mock.MagicMock(name="channel", spec=channel_type)
    mock_parse_grpc_uri = mocker.patch(
        "frequenz.client.base.client.parse_grpc_uri", return_value=mock_channel
    )
    client = BaseApiClient(
        server_url=server_url,
        create_stub=mock_create_stub,
        channel_type=channel_type,
        auto_connect=auto_connect,
    )
    return client, _ClientMocks(
        stub=mock_stub,
        create_stub=mock_create_stub,
        channel=mock_channel,
        parse_grpc_uri=mock_parse_grpc_uri,
    )


@pytest.mark.parametrize(
    "channel_type",
    [_grpchacks.GrpcioChannel, _grpchacks.GrpclibChannel],
    ids=_get_full_name,
)
@pytest.mark.parametrize("auto_connect", [True, False], ids=_auto_connect_name)
def test_base_api_client_init(
    channel_type: type[ChannelT],
    auto_connect: bool,
    mocker: pytest_mock.MockFixture,
) -> None:
    """Test initializing the BaseApiClient."""
    client, mocks = create_client_with_mocks(
        mocker, channel_type, auto_connect=auto_connect
    )
    assert client.server_url == _DEFAULT_SERVER_URL
    if auto_connect:
        mocks.parse_grpc_uri.assert_called_once_with(client.server_url, channel_type)
        assert client.channel is mocks.channel
        assert client.stub is mocks.stub
        assert client.is_connected
        mocks.create_stub.assert_called_once_with(mocks.channel)
    else:
        assert client.channel is None
        assert client.stub is None
        assert not client.is_connected
        mocks.parse_grpc_uri.assert_not_called()
        mocks.create_stub.assert_not_called()


@pytest.mark.parametrize(
    "channel_type",
    [_grpchacks.GrpcioChannel, _grpchacks.GrpclibChannel],
    ids=_get_full_name,
)
@pytest.mark.parametrize(
    "new_server_url", [None, _DEFAULT_SERVER_URL, "grpc://localhost:50051"]
)
@pytest.mark.parametrize("auto_connect", [True, False], ids=_auto_connect_name)
def test_base_api_client_connect(
    channel_type: type[ChannelT],
    new_server_url: str | None,
    auto_connect: bool,
    mocker: pytest_mock.MockFixture,
) -> None:
    """Test connecting the BaseApiClient."""
    client, mocks = create_client_with_mocks(
        mocker, channel_type, auto_connect=auto_connect
    )
    # We want to check only what happens when we call connect, so we reset the mocks
    # that were called during initialization
    mocks.parse_grpc_uri.reset_mock()
    mocks.create_stub.reset_mock()

    client.connect(new_server_url)

    assert client.channel is mocks.channel
    assert client.stub is mocks.stub
    assert client.is_connected

    same_url = new_server_url is None or new_server_url == _DEFAULT_SERVER_URL

    if same_url:
        assert client.server_url == _DEFAULT_SERVER_URL
    else:
        assert client.server_url == new_server_url

    # If we were previously connected and the URL didn't change, the client should not
    # reconnect
    if auto_connect and same_url:
        mocks.parse_grpc_uri.assert_not_called()
        mocks.create_stub.assert_not_called()
    else:
        mocks.parse_grpc_uri.assert_called_once_with(client.server_url, channel_type)
        mocks.create_stub.assert_called_once_with(mocks.channel)


@pytest.mark.parametrize(
    "channel_type",
    [_grpchacks.GrpcioChannel, _grpchacks.GrpclibChannel],
    ids=_get_full_name,
)
async def test_base_api_client_disconnect(
    channel_type: type[ChannelT],
    mocker: pytest_mock.MockFixture,
) -> None:
    """Test disconnecting the BaseApiClient."""
    client, mocks = create_client_with_mocks(mocker, channel_type, auto_connect=True)

    await client.disconnect()

    mocks.channel.__aexit__.assert_called_once_with(None, None, None)
    assert client.server_url == _DEFAULT_SERVER_URL
    assert client.channel is None
    assert client.stub is None
    assert not client.is_connected


# Tests for async context manager
@pytest.mark.parametrize(
    "channel_type",
    [_grpchacks.GrpcioChannel, _grpchacks.GrpclibChannel],
    ids=_get_full_name,
)
@pytest.mark.parametrize("auto_connect", [True, False], ids=_auto_connect_name)
async def test_base_api_client_async_context_manager(
    channel_type: type[ChannelT],
    auto_connect: bool,
    mocker: pytest_mock.MockFixture,
) -> None:
    """Test using the BaseApiClient as an async context manager."""
    client, mocks = create_client_with_mocks(
        mocker, channel_type, auto_connect=auto_connect
    )
    # We want to check only what happens when we enter the context manager, so we reset
    # the mocks that were called during initialization
    mocks.parse_grpc_uri.reset_mock()
    mocks.create_stub.reset_mock()

    async with client:
        assert client.channel is mocks.channel
        assert client.stub is mocks.stub
        assert client.is_connected
        mocks.channel.__aexit__.assert_not_called()
        # If we were previously connected, the client should not reconnect when entering
        # the context manager
        if auto_connect:
            mocks.parse_grpc_uri.assert_not_called()
            mocks.create_stub.assert_not_called()
        else:
            mocks.parse_grpc_uri.assert_called_once_with(
                client.server_url, channel_type
            )
            mocks.create_stub.assert_called_once_with(mocks.channel)

    mocks.channel.__aexit__.assert_called_once_with(None, None, None)
    assert client.server_url == _DEFAULT_SERVER_URL
    assert client.channel is None
    assert client.stub is None
    assert not client.is_connected
