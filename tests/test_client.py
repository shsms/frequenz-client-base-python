# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Tests for the BaseApiClient class."""

from collections.abc import Callable
from dataclasses import dataclass
from unittest import mock

import grpc.aio
import pytest
import pytest_mock

from frequenz.client.base.client import BaseApiClient, StubT, call_stub_method
from frequenz.client.base.exception import ClientNotConnected, UnknownError


def _auto_connect_name(auto_connect: bool) -> str:
    return f"{auto_connect=}"


def _assert_is_disconnected(client: BaseApiClient[StubT]) -> None:
    """Assert that the client is disconnected."""
    assert not client.is_connected

    with pytest.raises(ClientNotConnected, match=r"") as exc_info:
        _ = client.channel
    exc = exc_info.value
    assert exc.server_url == _DEFAULT_SERVER_URL
    assert exc.operation == "channel"

    with pytest.raises(ClientNotConnected, match=r"") as exc_info:
        _ = client.stub
    exc = exc_info.value
    assert exc.server_url == _DEFAULT_SERVER_URL
    assert exc.operation == "stub"


@dataclass(kw_only=True, frozen=True)
class _ClientMocks:
    stub: mock.MagicMock
    create_stub: mock.MagicMock
    channel: mock.MagicMock
    parse_grpc_uri: mock.MagicMock


_DEFAULT_SERVER_URL = "grpc://localhost"


def create_client_with_mocks(
    mocker: pytest_mock.MockFixture,
    *,
    auto_connect: bool = True,
    server_url: str = _DEFAULT_SERVER_URL,
) -> tuple[BaseApiClient[mock.MagicMock], _ClientMocks]:
    """Create a BaseApiClient instance with mocks."""
    mock_stub = mock.MagicMock(name="stub")
    mock_create_stub = mock.MagicMock(name="create_stub", return_value=mock_stub)
    mock_channel = mock.MagicMock(name="channel", spec=grpc.aio.Channel)
    mock_parse_grpc_uri = mocker.patch(
        "frequenz.client.base.client.parse_grpc_uri", return_value=mock_channel
    )
    client = BaseApiClient(
        server_url=server_url,
        create_stub=mock_create_stub,
        connect=auto_connect,
    )
    return client, _ClientMocks(
        stub=mock_stub,
        create_stub=mock_create_stub,
        channel=mock_channel,
        parse_grpc_uri=mock_parse_grpc_uri,
    )


@pytest.mark.parametrize("auto_connect", [True, False], ids=_auto_connect_name)
def test_base_api_client_init(
    auto_connect: bool,
    mocker: pytest_mock.MockFixture,
) -> None:
    """Test initializing the BaseApiClient."""
    client, mocks = create_client_with_mocks(mocker, auto_connect=auto_connect)
    assert client.server_url == _DEFAULT_SERVER_URL
    if auto_connect:
        mocks.parse_grpc_uri.assert_called_once_with(client.server_url)
        assert client.channel is mocks.channel
        assert client.stub is mocks.stub
        assert client.is_connected
        mocks.create_stub.assert_called_once_with(mocks.channel)
    else:
        _assert_is_disconnected(client)
        mocks.parse_grpc_uri.assert_not_called()
        mocks.create_stub.assert_not_called()


@pytest.mark.parametrize(
    "new_server_url", [None, _DEFAULT_SERVER_URL, "grpc://localhost:50051"]
)
@pytest.mark.parametrize("auto_connect", [True, False], ids=_auto_connect_name)
def test_base_api_client_connect(
    new_server_url: str | None,
    auto_connect: bool,
    mocker: pytest_mock.MockFixture,
) -> None:
    """Test connecting the BaseApiClient."""
    client, mocks = create_client_with_mocks(mocker, auto_connect=auto_connect)
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
        mocks.parse_grpc_uri.assert_called_once_with(client.server_url)
        mocks.create_stub.assert_called_once_with(mocks.channel)


async def test_base_api_client_disconnect(mocker: pytest_mock.MockFixture) -> None:
    """Test disconnecting the BaseApiClient."""
    client, mocks = create_client_with_mocks(mocker, auto_connect=True)

    await client.disconnect()

    mocks.channel.__aexit__.assert_called_once_with(None, None, None)
    assert client.server_url == _DEFAULT_SERVER_URL
    _assert_is_disconnected(client)


@pytest.mark.parametrize("auto_connect", [True, False], ids=_auto_connect_name)
async def test_base_api_client_async_context_manager(
    auto_connect: bool,
    mocker: pytest_mock.MockFixture,
) -> None:
    """Test using the BaseApiClient as an async context manager."""
    client, mocks = create_client_with_mocks(mocker, auto_connect=auto_connect)
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
            mocks.parse_grpc_uri.assert_called_once_with(client.server_url)
            mocks.create_stub.assert_called_once_with(mocks.channel)

    mocks.channel.__aexit__.assert_called_once_with(None, None, None)
    assert client.server_url == _DEFAULT_SERVER_URL
    _assert_is_disconnected(client)


def _transform_name(transform: bool) -> str:
    return "transform" if transform else "no_transform"


@pytest.fixture
def mock_transform() -> mock.MagicMock:
    """Return a mock transform function."""
    return mock.MagicMock(name="transform", spec=Callable[[int], int], return_value=2)


@pytest.mark.parametrize(
    "method_name",
    [None, "method"],
)
@pytest.mark.parametrize(
    "transform",
    [True, False],
    ids=_transform_name,
)
async def test_call_stub_method_not_connected(
    method_name: str, transform: bool, mock_transform: mock.MagicMock | None
) -> None:
    """Test calling a stub method when the client is not connected."""
    mock_client = mock.MagicMock(name="client", spec=BaseApiClient)
    mock_client.is_connected = False
    mock_client.server_url = "server_url"
    mock_stub_method = mock.AsyncMock(name="stub_method")
    if not transform:
        mock_transform = None

    with pytest.raises(ClientNotConnected) as exc_info:
        _ = await call_stub_method(
            mock_client,
            mock_stub_method,
            transform=mock_transform,
            method_name=method_name,
        )
    mock_stub_method.assert_not_called()
    assert exc_info.value.server_url == "server_url"
    assert exc_info.value.operation == (
        method_name or "test_call_stub_method_not_connected"
    )
    if mock_transform:
        mock_transform.assert_not_called()


@pytest.mark.parametrize(
    "method_name",
    [None, "method"],
)
@pytest.mark.parametrize(
    "transform",
    [True, False],
    ids=_transform_name,
)
async def test_call_stub_method_exception(
    method_name: str,
    transform: bool,
    mock_transform: mock.MagicMock | None,
) -> None:
    """Test calling a stub method that raises an exception."""
    mock_client = mock.MagicMock(name="client", spec=BaseApiClient)
    mock_client.is_connected = True
    mock_client.server_url = "server_url"
    exception = grpc.aio.AioRpcError(
        grpc.StatusCode.UNKNOWN,
        mock.MagicMock(name="initial_metadata"),
        mock.MagicMock(name="trailing_metadata"),
        "details",
        "debug_error_string",
    )
    mock_stub_method = mock.MagicMock(name="stub_method", side_effect=exception)
    if not transform:
        mock_transform = None

    with pytest.raises(UnknownError) as exc_info:
        _ = await call_stub_method(
            mock_client,
            mock_stub_method,
            transform=mock_transform,
            method_name=method_name,
        )
    mock_stub_method.assert_called_once_with()
    assert exc_info.value.server_url == "server_url"
    assert exc_info.value.operation == (
        method_name or "test_call_stub_method_exception"
    )
    assert exc_info.value.__cause__ is exception
    assert exc_info.value.grpc_error is exception
    if mock_transform:
        mock_transform.assert_not_called()


@pytest.mark.parametrize(
    "method_name",
    [None, "method"],
)
@pytest.mark.parametrize(
    "transform",
    [True, False],
    ids=_transform_name,
)
async def test_call_stub_method_success(
    method_name: str,
    transform: bool,
    mock_transform: mock.MagicMock | None,
) -> None:
    """Test calling a stub method that succeeds."""
    mock_client = mock.MagicMock(name="client", spec=BaseApiClient)
    mock_client.is_connected = True
    mock_client.server_url = "server_url"
    mock_stub_method = mock.AsyncMock(name="stub_method", return_value=1)
    if not transform:
        mock_transform = None

    response = await call_stub_method(
        mock_client,
        mock_stub_method,
        transform=mock_transform,
        method_name=method_name,
    )

    mock_stub_method.assert_called_once_with()
    assert response == (2 if transform else 1)
    if mock_transform:
        mock_transform.assert_called_once_with(1)
