# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Tests for the microgrid client exceptions."""

import re
from typing import Protocol
from unittest import mock

import grpc
import grpc.aio
import pytest

from frequenz.client.base.exception import (
    ApiClientError,
    ClientNotConnected,
    DataLoss,
    EntityAlreadyExists,
    EntityNotFound,
    GrpcError,
    InternalError,
    InvalidArgument,
    OperationAborted,
    OperationCancelled,
    OperationNotImplemented,
    OperationOutOfRange,
    OperationPreconditionFailed,
    OperationTimedOut,
    OperationUnauthenticated,
    PermissionDenied,
    ResourceExhausted,
    ServiceUnavailable,
    UnknownError,
    UnrecognizedGrpcStatus,
)


def test_client_not_connected() -> None:
    """Test the ClientNotConnected exception."""
    exception = ClientNotConnected(server_url="grpc://localhost", operation="test")

    assert exception.server_url == "grpc://localhost"
    assert exception.operation == "test"
    assert exception.description == "The client is not connected to the server"
    assert exception.is_retryable is True


class _GrpcErrorCtor(Protocol):
    """A protocol for the constructor of a subclass of `GrpcErrorCtor`."""

    def __call__(
        self, *, server_url: str, operation: str, grpc_error: grpc.aio.AioRpcError
    ) -> GrpcError: ...


ERROR_TUPLES: list[tuple[type[GrpcError], grpc.StatusCode, str, bool]] = [
    (
        UnrecognizedGrpcStatus,
        mock.MagicMock(name="unknown_status"),
        "Got an unrecognized status code",
        True,
    ),
    (
        OperationCancelled,
        grpc.StatusCode.CANCELLED,
        "The operation was cancelled",
        True,
    ),
    (
        UnknownError,
        grpc.StatusCode.UNKNOWN,
        "There was an error that can't be described using other statuses",
        True,
    ),
    (
        InvalidArgument,
        grpc.StatusCode.INVALID_ARGUMENT,
        "The client specified an invalid argument",
        False,
    ),
    (
        OperationTimedOut,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        "The time limit was exceeded while waiting for the operation to complete",
        True,
    ),
    (
        EntityNotFound,
        grpc.StatusCode.NOT_FOUND,
        "The requested entity was not found",
        True,
    ),
    (
        EntityAlreadyExists,
        grpc.StatusCode.ALREADY_EXISTS,
        "The entity that we attempted to create already exists",
        True,
    ),
    (
        PermissionDenied,
        grpc.StatusCode.PERMISSION_DENIED,
        "The caller does not have permission to execute the specified operation",
        True,
    ),
    (
        ResourceExhausted,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        "Some resource has been exhausted (for example per-user quota, disk space, etc.)",
        True,
    ),
    (
        OperationPreconditionFailed,
        grpc.StatusCode.FAILED_PRECONDITION,
        "The operation was rejected because the system is not in a required state",
        True,
    ),
    (OperationAborted, grpc.StatusCode.ABORTED, "The operation was aborted", True),
    (
        OperationOutOfRange,
        grpc.StatusCode.OUT_OF_RANGE,
        "The operation was attempted past the valid range",
        True,
    ),
    (
        OperationNotImplemented,
        grpc.StatusCode.UNIMPLEMENTED,
        "The operation is not implemented or not supported/enabled in this service",
        False,
    ),
    (
        InternalError,
        grpc.StatusCode.INTERNAL,
        "Some invariants expected by the underlying system have been broken",
        True,
    ),
    (
        ServiceUnavailable,
        grpc.StatusCode.UNAVAILABLE,
        "The service is currently unavailable",
        True,
    ),
    (
        DataLoss,
        grpc.StatusCode.DATA_LOSS,
        "Unrecoverable data loss or corruption",
        False,
    ),
    (
        OperationUnauthenticated,
        grpc.StatusCode.UNAUTHENTICATED,
        "The request does not have valid authentication credentials for the operation",
        False,
    ),
]


@pytest.mark.parametrize(
    "exception_class, grpc_status, expected_description, retryable", ERROR_TUPLES
)
def test_grpc_status_error(
    exception_class: _GrpcErrorCtor,
    grpc_status: grpc.StatusCode,
    expected_description: str,
    retryable: bool,
) -> None:
    """Test gRPC status errors are correctly created from gRPC errors."""
    grpc_error = grpc.aio.AioRpcError(
        grpc_status,
        initial_metadata=mock.MagicMock(),
        trailing_metadata=mock.MagicMock(),
        debug_error_string="grpc error message",
        details="grpc error details",
    )
    exception = exception_class(
        server_url="http://testserver",
        operation="test_operation",
        grpc_error=grpc_error,
    )

    assert exception.server_url == "http://testserver"
    assert exception.operation == "test_operation"
    assert expected_description == exception.description
    assert exception.grpc_error == grpc_error
    assert exception.is_retryable == retryable


def test_grpc_unknown_status_error() -> None:
    """Test that an UnknownError is created for an unknown gRPC status."""
    expected_description = "Test error"
    grpc_error = grpc.aio.AioRpcError(
        mock.MagicMock(name="unknown_status"),
        initial_metadata=mock.MagicMock(),
        trailing_metadata=mock.MagicMock(),
        debug_error_string="grpc error message",
        details="grpc error details",
    )
    exception = GrpcError(
        server_url="http://testserver",
        operation="test_operation",
        description=expected_description,
        grpc_error=grpc_error,
        retryable=True,
    )

    assert exception.server_url == "http://testserver"
    assert exception.operation == "test_operation"
    assert expected_description in exception.description
    assert exception.grpc_error == grpc_error
    assert exception.is_retryable is True


def test_client_error() -> None:
    """Test the ApiClientError class."""
    error = ApiClientError(
        server_url="http://testserver",
        operation="test_operation",
        description="An error occurred",
        retryable=True,
    )

    assert error.server_url == "http://testserver"
    assert error.operation == "test_operation"
    assert error.description == "An error occurred"
    assert error.is_retryable is True


@pytest.mark.parametrize(
    "exception_class, grpc_status, expected_description, retryable", ERROR_TUPLES
)
def test_from_grpc_error(
    exception_class: type[GrpcError],
    grpc_status: grpc.StatusCode,
    expected_description: str,
    retryable: bool,
) -> None:
    """Test that the from_grpc_error method creates the correct exception."""
    grpc_error = grpc.aio.AioRpcError(
        grpc_status,
        initial_metadata=mock.MagicMock(),
        trailing_metadata=mock.MagicMock(),
        debug_error_string="grpc error details",
        details="grpc error message",
    )
    with pytest.raises(
        exception_class,
        match=r"Failed calling 'test_operation' on 'http://testserver': "
        rf"{re.escape(expected_description)} "
        rf"<status={re.escape(str(grpc_status.name))}>: "
        r"grpc error message \(grpc error details\)",
    ) as exc_info:
        raise ApiClientError.from_grpc_error(
            server_url="http://testserver",
            operation="test_operation",
            grpc_error=grpc_error,
        )

    exception = exc_info.value
    assert isinstance(exception, exception_class)
    assert exception.server_url == "http://testserver"
    assert exception.operation == "test_operation"
    assert exception.grpc_error == grpc_error
    assert expected_description == exception.description
    assert exception.is_retryable == retryable
