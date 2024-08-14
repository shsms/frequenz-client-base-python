# License: MIT
# Copyright © 2022 Frequenz Energy-as-a-Service GmbH

"""Exceptions raised by an API client."""

from __future__ import annotations

from typing import Protocol

import grpc
from grpc.aio import AioRpcError


class ApiClientError(Exception):
    """There was an error in an API client.

    To simplify retrying, errors are classified as
    [retryable][frequenz.client.base.exception.ApiClientError.is_retryable], or not.
    Retryable errors might succeed if retried, while permanent errors won't. When
    uncertain, errors are assumed to be retryable.

    The following sub-classes are available:

    - [GrpcError][frequenz.client.base.exception.GrpcError]: A gRPC operation failed.
    """

    def __init__(
        self,
        *,
        server_url: str,
        operation: str,
        description: str,
        retryable: bool,
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            description: A human-readable description of the error.
            retryable: Whether retrying the operation might succeed.
        """
        super().__init__(
            f"Failed calling {operation!r} on {server_url!r}: {description}"
        )

        self.server_url = server_url
        """The URL of the server that returned the error."""

        self.operation = operation
        """The operation that caused the error."""

        self.description = description
        """The human-readable description of the error."""

        self.is_retryable = retryable
        """Whether retrying the operation might succeed."""

    @classmethod
    def from_grpc_error(
        cls,
        *,
        server_url: str,
        operation: str,
        grpc_error: AioRpcError,
    ) -> GrpcError:
        """Create an instance of the appropriate subclass from a gRPC error.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error to convert.

        Returns:
            An instance of
                [GrpcError][frequenz.client.base.exception.GrpcError] if the gRPC status
                is not recognized, or an appropriate subclass if it is.
        """

        class Ctor(Protocol):
            """A protocol for the constructor of a subclass of `GrpcError`."""

            def __call__(
                self, *, server_url: str, operation: str, grpc_error: AioRpcError
            ) -> GrpcError: ...

        grpc_status_map: dict[grpc.StatusCode, Ctor] = {
            grpc.StatusCode.CANCELLED: OperationCancelled,
            grpc.StatusCode.UNKNOWN: UnknownError,
            grpc.StatusCode.INVALID_ARGUMENT: InvalidArgument,
            grpc.StatusCode.DEADLINE_EXCEEDED: OperationTimedOut,
            grpc.StatusCode.NOT_FOUND: EntityNotFound,
            grpc.StatusCode.ALREADY_EXISTS: EntityAlreadyExists,
            grpc.StatusCode.PERMISSION_DENIED: PermissionDenied,
            grpc.StatusCode.RESOURCE_EXHAUSTED: ResourceExhausted,
            grpc.StatusCode.FAILED_PRECONDITION: OperationPreconditionFailed,
            grpc.StatusCode.ABORTED: OperationAborted,
            grpc.StatusCode.OUT_OF_RANGE: OperationOutOfRange,
            grpc.StatusCode.UNIMPLEMENTED: OperationNotImplemented,
            grpc.StatusCode.INTERNAL: InternalError,
            grpc.StatusCode.UNAVAILABLE: ServiceUnavailable,
            grpc.StatusCode.DATA_LOSS: DataLoss,
            grpc.StatusCode.UNAUTHENTICATED: OperationUnauthenticated,
        }

        if ctor := grpc_status_map.get(grpc_error.code()):
            return ctor(
                server_url=server_url, operation=operation, grpc_error=grpc_error
            )
        return UnrecognizedGrpcStatus(
            server_url=server_url,
            operation=operation,
            grpc_error=grpc_error,
        )


class ClientNotConnected(ApiClientError):
    """The client is not connected to the server."""

    def __init__(self, *, server_url: str, operation: str) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The client is not connected to the server",
            retryable=True,
        )


class GrpcError(ApiClientError):
    """The gRPC server returned an error with a status code.

    These errors are specific to gRPC. If you want to use the client in
    a protocol-independent way, you should avoid catching this exception. Catching
    subclasses that don't have *grpc* in their name should be protocol-independent.

    The following sub-classes are available:

    - [DataLoss][frequenz.client.base.exception.DataLoss]: Unrecoverable data loss or
      corruption.
    - [EntityAlreadyExists][frequenz.client.base.exception.EntityAlreadyExists]: The
      entity that we attempted to create already exists.
    - [EntityNotFound][frequenz.client.base.exception.EntityNotFound]: The requested
      entity was not found.
    - [InternalError][frequenz.client.base.exception.InternalError]: Some invariants
      expected by the underlying system have been broken.
    - [InvalidArgument][frequenz.client.base.exception.InvalidArgument]: The client
      specified an invalid argument.
    - [OperationAborted][frequenz.client.base.exception.OperationAborted]: The
      operation was aborted.
    - [OperationCancelled][frequenz.client.base.exception.OperationCancelled]: The
      operation was cancelled.
    - [OperationNotImplemented][frequenz.client.base.exception.OperationNotImplemented]:
      The operation is not implemented or not supported/enabled in this service.
    - [OperationOutOfRange][frequenz.client.base.exception.OperationOutOfRange]: The
      operation was attempted past the valid range.
    - [OperationPreconditionFailed][frequenz.client.base.exception.OperationPreconditionFailed]:
      The operation was rejected because the system is not in a required state.
    - [OperationTimedOut][frequenz.client.base.exception.OperationTimedOut]: The time
      limit was exceeded while waiting for the operation to complete.
    - [OperationUnauthenticated][frequenz.client.base.exception.OperationUnauthenticated]:
      The request does not have valid authentication credentials for the operation.
    - [PermissionDenied][frequenz.client.base.exception.PermissionDenied]: The caller
      does not have permission to execute the specified operation.
    - [ResourceExhausted][frequenz.client.base.exception.ResourceExhausted]: Some
      resource has been exhausted (for example per-user quota, disk space, etc.).
    - [ServiceUnavailable][frequenz.client.base.exception.ServiceUnavailable]: The
      service is currently unavailable.
    - [UnknownError][frequenz.client.base.exception.UnknownError]: There was an error
      that can't be described using other statuses.
    - [UnrecognizedGrpcStatus][frequenz.client.base.exception.UnrecognizedGrpcStatus]:
      The gRPC server returned an unrecognized status code.

    References:
        * [gRPC status
           codes](https://github.com/grpc/grpc/blob/master/doc/statuscodes.md)
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        server_url: str,
        operation: str,
        description: str,
        grpc_error: AioRpcError,
        retryable: bool,
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            description: A human-readable description of the error.
            grpc_error: The gRPC error originating this exception.
            retryable: Whether retrying the operation might succeed.
        """
        status_name = grpc_error.code().name
        message = grpc_error.details()
        details = grpc_error.debug_error_string()
        message = f": {message}" if message else ""
        details = f" ({details})" if details else ""
        super().__init__(
            server_url=server_url,
            operation=operation,
            description=f"{description} <status={status_name}>{message}{details}",
            retryable=retryable,
        )
        self.description: str = description
        """The human-readable description of the error."""

        self.grpc_error: AioRpcError = grpc_error
        """The original gRPC error."""


class UnrecognizedGrpcStatus(GrpcError):
    """The gRPC server returned an unrecognized status code."""

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="Got an unrecognized status code",
            grpc_error=grpc_error,
            retryable=True,  # We don't know so we assume it's retryable
        )


class OperationCancelled(GrpcError):
    """The operation was cancelled."""

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The operation was cancelled",
            grpc_error=grpc_error,
            retryable=True,
        )


class UnknownError(GrpcError):
    """There was an error that can't be described using other statuses."""

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="There was an error that can't be described using other statuses",
            grpc_error=grpc_error,
            retryable=True,  # We don't know so we assume it's retryable
        )


class InvalidArgument(GrpcError, ValueError):
    """The client specified an invalid argument.

    Note that this error differs from
    [OperationPreconditionFailed][frequenz.client.base.exception.OperationPreconditionFailed].
    This error indicates arguments that are problematic regardless of the state of the
    system (e.g., a malformed file name).
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The client specified an invalid argument",
            grpc_error=grpc_error,
            retryable=False,
        )


class OperationTimedOut(GrpcError):
    """The time limit was exceeded while waiting for the operationt o complete.

    For operations that change the state of the system, this error may be returned even
    if the operation has completed successfully. For example, a successful response from
    a server could have been delayed long.
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The time limit was exceeded while waiting for the operation "
            "to complete",
            grpc_error=grpc_error,
            retryable=True,
        )


class EntityNotFound(GrpcError):
    """The requested entity was not found.

    Note that this error differs from
    [PermissionDenied][frequenz.client.base.exception.PermissionDenied]. This error is
    used when the requested entity is not found, regardless of the user's permissions.
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The requested entity was not found",
            grpc_error=grpc_error,
            retryable=True,  # If the entity is added later it might succeed
        )


class EntityAlreadyExists(GrpcError):
    """The entity that we attempted to create already exists."""

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The entity that we attempted to create already exists",
            grpc_error=grpc_error,
            retryable=True,  # If the entity is deleted later it might succeed
        )


class PermissionDenied(GrpcError):
    """The caller does not have permission to execute the specified operation.

    Note that when the operation is rejected due to other reasons, such as the resources
    being exhausted or the user not being authenticated at all, different errors should
    be catched instead
    ([ResourceExhausted][frequenz.client.base.exception.ResourceExhausted] and
    [OperationUnauthenticated][frequenz.client.base.exception.OperationUnauthenticated]
    respectively).
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The caller does not have permission to execute the specified "
            "operation",
            grpc_error=grpc_error,
            retryable=True,  # If the user is granted permission it might succeed
        )


class ResourceExhausted(GrpcError):
    """Some resource has been exhausted (for example per-user quota, disk space, etc.)."""

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="Some resource has been exhausted (for example per-user quota, "
            "disk space, etc.)",
            grpc_error=grpc_error,
            retryable=True,  # If the resource is freed it might succeed
        )


class OperationPreconditionFailed(GrpcError):
    """The operation was rejected because the system is not in a required state.

    For example, the directory to be deleted is non-empty, an rmdir operation is applied
    to a non-directory, etc. The user should perform some corrective action before
    retrying the operation.
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The operation was rejected because the system is not in a "
            "required state",
            grpc_error=grpc_error,
            retryable=True,  # If the system state changes it might succeed
        )


class OperationAborted(GrpcError):
    """The operation was aborted.

    Typically due to a concurrency issue or transaction abort.
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The operation was aborted",
            grpc_error=grpc_error,
            retryable=True,
        )


class OperationOutOfRange(GrpcError):
    """The operation was attempted past the valid range.

    Unlike [InvalidArgument][frequenz.client.base.exception.InvalidArgument], this error
    indicates a problem that may be fixed if the system state changes.

    There is a fair bit of overlap with
    [OperationPreconditionFailed][frequenz.client.base.exception.OperationPreconditionFailed],
    this error is just a more specific version of that error and could be the result of
    an operation that doesn't even take any arguments.
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The operation was attempted past the valid range",
            grpc_error=grpc_error,
            retryable=True,  # If the system state changes it might succeed
        )


class OperationNotImplemented(GrpcError):
    """The operation is not implemented or not supported/enabled in this service."""

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The operation is not implemented or not supported/enabled in "
            "this service",
            grpc_error=grpc_error,
            retryable=False,
        )


class InternalError(GrpcError):
    """Some invariants expected by the underlying system have been broken.

    This error code is reserved for serious errors.
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="Some invariants expected by the underlying system have been "
            "broken",
            grpc_error=grpc_error,
            retryable=True,  # If the system state changes it might succeed
        )


class ServiceUnavailable(GrpcError):
    """The service is currently unavailable.

    This is most likely a transient condition, which can be corrected by retrying with
    a backoff. Note that it is not always safe to retry non-idempotent operations.
    """

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The service is currently unavailable",
            grpc_error=grpc_error,
            retryable=True,  # If the service becomes available it might succeed
        )


class DataLoss(GrpcError):
    """Unrecoverable data loss or corruption."""

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="Unrecoverable data loss or corruption",
            grpc_error=grpc_error,
            retryable=False,
        )


class OperationUnauthenticated(GrpcError):
    """The request does not have valid authentication credentials for the operation."""

    def __init__(
        self, *, server_url: str, operation: str, grpc_error: AioRpcError
    ) -> None:
        """Create a new instance.

        Args:
            server_url: The URL of the server that returned the error.
            operation: The operation that caused the error.
            grpc_error: The gRPC error originating this exception.
        """
        super().__init__(
            server_url=server_url,
            operation=operation,
            description="The request does not have valid authentication credentials "
            "for the operation",
            grpc_error=grpc_error,
            retryable=False,
        )
