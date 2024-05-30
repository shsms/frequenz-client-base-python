# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Tests for the microgrid client exceptions."""

import re
from typing import Protocol
from unittest import mock

import grpclib
import pytest

from frequenz.client.base.exception import (
    ApiClientError,
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


class _GrpcErrorCtor(Protocol):
    """A protocol for the constructor of a subclass of `GrpcErrorCtor`."""

    def __call__(
        self, *, server_url: str, operation: str, grpc_error: grpclib.GRPCError
    ) -> GrpcError: ...


ERROR_TUPLES: list[tuple[type[GrpcError], grpclib.Status, str, bool]] = [
    (
        UnrecognizedGrpcStatus,
        mock.MagicMock(name="unknown_status"),
        "Got an unrecognized status code",
        True,
    ),
    (
        OperationCancelled,
        grpclib.Status.CANCELLED,
        "The operation was cancelled",
        True,
    ),
    (
        UnknownError,
        grpclib.Status.UNKNOWN,
        "There was an error that can't be described using other statuses",
        True,
    ),
    (
        InvalidArgument,
        grpclib.Status.INVALID_ARGUMENT,
        "The client specified an invalid argument",
        False,
    ),
    (
        OperationTimedOut,
        grpclib.Status.DEADLINE_EXCEEDED,
        "The time limit was exceeded while waiting for the operation to complete",
        True,
    ),
    (
        EntityNotFound,
        grpclib.Status.NOT_FOUND,
        "The requested entity was not found",
        True,
    ),
    (
        EntityAlreadyExists,
        grpclib.Status.ALREADY_EXISTS,
        "The entity that we attempted to create already exists",
        True,
    ),
    (
        PermissionDenied,
        grpclib.Status.PERMISSION_DENIED,
        "The caller does not have permission to execute the specified operation",
        True,
    ),
    (
        ResourceExhausted,
        grpclib.Status.RESOURCE_EXHAUSTED,
        "Some resource has been exhausted (for example per-user quota, disk space, etc.)",
        True,
    ),
    (
        OperationPreconditionFailed,
        grpclib.Status.FAILED_PRECONDITION,
        "The operation was rejected because the system is not in a required state",
        True,
    ),
    (OperationAborted, grpclib.Status.ABORTED, "The operation was aborted", True),
    (
        OperationOutOfRange,
        grpclib.Status.OUT_OF_RANGE,
        "The operation was attempted past the valid range",
        True,
    ),
    (
        OperationNotImplemented,
        grpclib.Status.UNIMPLEMENTED,
        "The operation is not implemented or not supported/enabled in this service",
        False,
    ),
    (
        InternalError,
        grpclib.Status.INTERNAL,
        "Some invariants expected by the underlying system have been broken",
        True,
    ),
    (
        ServiceUnavailable,
        grpclib.Status.UNAVAILABLE,
        "The service is currently unavailable",
        True,
    ),
    (
        DataLoss,
        grpclib.Status.DATA_LOSS,
        "Unrecoverable data loss or corruption",
        False,
    ),
    (
        OperationUnauthenticated,
        grpclib.Status.UNAUTHENTICATED,
        "The request does not have valid authentication credentials for the operation",
        False,
    ),
]


@pytest.mark.parametrize(
    "exception_class, grpc_status, expected_description, retryable", ERROR_TUPLES
)
def test_grpc_status_error(
    exception_class: _GrpcErrorCtor,
    grpc_status: grpclib.Status,
    expected_description: str,
    retryable: bool,
) -> None:
    """Test gRPC status errors are correctly created from gRPC errors."""
    grpc_error = grpclib.GRPCError(
        grpc_status, "grpc error message", "grpc error details"
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
    grpc_error = grpclib.GRPCError(
        mock.MagicMock(name="unknown_status"),
        "grpc error message",
        "grpc error details",
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
    grpc_status: grpclib.Status,
    expected_description: str,
    retryable: bool,
) -> None:
    """Test that the from_grpc_error method creates the correct exception."""
    grpc_error = grpclib.GRPCError(
        grpc_status, "grpc error message", "grpc error details"
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
