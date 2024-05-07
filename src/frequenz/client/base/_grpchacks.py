# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Hacks to deal with multiple grpc libraries.

This module conditionally imports the base exceptions from the `grpclib` and `grpcio`
libraries, assigning them a new name:

- [`GrpclibError`][] for [`grpclib.GRPCError`][]
- [`GrpcioError`][] for [`grpc.aio.AioRpcError`][]

If the libraries are not installed, the module defines dummy classes with the same names
to avoid import errors.

This way exceptions can be caught from both libraries independently of which one is
used. The unused library will just never raise any exceptions.
"""


try:
    from grpclib import GRPCError as GrpclibError
except ImportError:

    class GrpclibError(Exception):  # type: ignore[no-redef]
        """A dummy class to avoid import errors.

        This class will never be actually used, as it is only used for catching
        exceptions from the grpclib library. If the grpclib library is not installed,
        this class will never be instantiated.
        """


try:
    from grpc.aio import AioRpcError as GrpcioError
except ImportError:

    class GrpcioError(Exception):  # type: ignore[no-redef]
        """A dummy class to avoid import errors.

        This class will never be actually used, as it is only used for catching
        exceptions from the grpc library. If the grpc library is not installed,
        this class will never be instantiated.
        """


__all__ = ["GrpclibError", "GrpcioError"]
