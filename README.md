# Frequenz Client Base Library

[![Build Status](https://github.com/frequenz-floss/frequenz-client-base-python/actions/workflows/ci.yaml/badge.svg)](https://github.com/frequenz-floss/frequenz-client-base-python/actions/workflows/ci.yaml)
[![PyPI Package](https://img.shields.io/pypi/v/frequenz-client-base)](https://pypi.org/project/frequenz-client-base/)
[![Docs](https://img.shields.io/badge/docs-latest-informational)](https://frequenz-floss.github.io/frequenz-client-base-python/)

## Introduction

This library provides base utilities and classes for creating Frequenz API
clients. It simplifies the process of creating clients that can connect to the
Frequenz platform, handle authentication, and manage communication channels.

## Supported Platforms

The following platforms are officially supported (tested):

- **Python:** 3.11
- **Operating System:** Ubuntu Linux 24.04
- **Architectures:** amd64, arm64

> [!NOTE]
> Newer Python versions and other operating systems and architectures might
> work too, but they are not automatically tested, so we cannot guarantee it.

## Quick Start

### Installing

Assuming a [supported](#supported-platforms) working Python environment:

```sh
python3 -m pip install frequenz-client-base
```

### gRPC URLs

The `BaseApiClient` and its subclasses use a gRPC URL to specify the connection
parameters. The URL must have the following format:

`grpc://hostname[:port][?param=value&...]`

A few things to consider about URI components:

- If any other components are present in the URI, a `ValueError` is raised.
- If the port is omitted, a default port must be configured in the client,
  otherwise a `ValueError` is raised.
- If a query parameter is passed many times, the last value is used.
- Boolean query parameters can be specified with the following values
  (case-insensitive): `true`, `1`, `on`, `false`, `0`, `off`.

Supported query parameters:

- `ssl` (bool): Enable or disable SSL. Defaults to `True`.
- `ssl_root_certificates_path` (str): Path to the root certificates file. Only
  valid if SSL is enabled. Will raise a `ValueError` if the file cannot be read.
- `ssl_private_key_path` (str): Path to the private key file. Only valid if SSL
  is enabled. Will raise a `ValueError` if the file cannot be read.
- `ssl_certificate_chain_path` (str): Path to the certificate chain file. Only
  valid if SSL is enabled. Will raise a `ValueError` if the file cannot be read.
- `keep_alive` (bool): Enable or disable HTTP2 keep-alive. Defaults to `True`.
- `keep_alive_interval_s` (float): The interval between HTTP2 pings in seconds.
  Defaults to 60.
- `keep_alive_timeout_s` (float): The time to wait for a HTTP2 keep-alive
  response in seconds. Defaults to 20.

For example:

- `grpc://localhost:50051?ssl=off`: Connect to `localhost:50051` without SSL.
- `grpc://api.frequenz.io:443?keep_alive_interval_s=30`: Connect to
  `api.frequenz.io:443` with SSL and a keep-alive interval of 30 seconds.
- `grpc://localhost:8443?ssl_root_certificates_path=/path/to/ca.pem&ssl_private_key_path=/path/to/key.pem&ssl_certificate_chain_path=/path/to/cert.pem`:
  Connect to `localhost:8443` with SSL and custom certificates.

### Examples

Examples assume you have generated Python code from the `helloworld.proto` file
from the `grpc` examples, which you can find
[here](https://raw.githubusercontent.com/grpc/grpc/89341001058172bd25ff1392dd7653b48d39dc62/examples/protos/helloworld.proto).

We will not explain in detail on how to generate Python files from protobuf
files, but this should be able to get you started:

```sh
mkdir example
cd example
python3 -m venv .venv
. .venv/bin/activate
curl -sO https://raw.githubusercontent.com/grpc/grpc/89341001058172bd25ff1392dd7653b48d39dc62/examples/protos/helloworld.proto
python3 -m pip install grpcio-tools mypy-protobuf
python3 -m grpc_tools.protoc -I. --python_out=. --mypy_out=. --grpc_python_out=. --mypy_grpc_out=. helloworld.proto
```

This will generate `helloworld_pb2.py`, `helloworld_pb2.pyi`, and `helloworld_pb2_grpc.py`.

#### Creating a Client

This example shows how to create a client by subclassing `BaseApiClient`.

```python
from __future__ import annotations

import asyncio

from frequenz.client.base.client import BaseApiClient, call_stub_method
from frequenz.client.base.exception import ClientNotConnected

# The following imports are from the generated files
import helloworld_pb2
import helloworld_pb2_grpc


class GreeterApiClient(BaseApiClient[helloworld_pb2_grpc.GreeterStub]):
    """A client for the Greeter service."""

    def __init__(
        self,
        server_url: str,
        *,
        connect: bool = True,
    ) -> None:
        """Create a new Greeter client.

        Args:
            server_url: The URL of the Greeter service.
            connect: Whether to connect to the server immediately.
        """
        super().__init__(
            server_url,
            helloworld_pb2_grpc.GreeterStub,
            connect=connect,
        )

    @property
    def stub(self) -> helloworld_pb2_grpc.GreeterAsyncStub:
        """The gRPC stub for the API.

        Raises:
            ClientNotConnected: if the client is not connected.

        Returns:
            The gRPC stub.
        """
        if self._stub is None:
            raise ClientNotConnected(server_url=self.server_url, operation="stub")
        # This type: ignore is needed because we need to cast the sync stub to
        # the async stub, but we can't use cast because the async stub doesn't
        # actually exists to the eyes of the interpreter, it only exists for the
        # type-checker, so it can only be used for type hints.
        return self._stub  # type: ignore

    async def say_hello(self, name: str) -> str:
        """Send a greeting to the server.

        Args:
            name: The name to greet.

        Returns:
            The greeting message from the server.
        """
        response = await call_stub_method(
            self,
            lambda: self.stub.SayHello(
                helloworld_pb2.HelloRequest(name=name), timeout=5
            ),
            method_name="SayHello",
        )
        return response.message


async def main() -> None:
    """Create a client and connect to the server."""
    async with GreeterApiClient(server_url="grpc://localhost:50051?ssl=off") as client:
        print(await client.say_hello("Frequenz"))


if __name__ == "__main__":
    asyncio.run(main())
```

> [!NOTE]
> * We need to create a `stub` property that returns the async stub because the
>   regular stub interface is dynamic and supports both sync and async stubs, the
>   typing information is not correct. The `GreeterAsyncStub` is defined in the
>   generated `.pyi` file, so the interpreter does not know about it, so we need
>   to use a `type: ignore`.
> * We use the `call_stub_method` utility function to call the stub method, so gRPC
>   errors are converted automatically to the more idiomatic
>  `frequenz.client.base.exception.ApiClientError` exceptions.

If you want to test it, you can use the [example Python
server](https://github.com/grpc/grpc/blob/89341001058172bd25ff1392dd7653b48d39dc62/examples/python/helloworld/async_greeter_server.py):

```console
$ curl -sO https://raw.githubusercontent.com/grpc/grpc/89341001058172bd25ff1392dd7653b48d39dc62/examples/python/helloworld/async_greeter_server.py
$ python async_greeter_server.py
INFO:root:Starting server on [::]:50051
```

Running the client:

```console
$ python3 client.py
Hello, Frequenz!
```

#### Streaming

This example shows how to use the `GrpcStreamBroadcaster` to handle streaming RPCs.

For this, we will use the `hellostreamingworld.proto` file from the `grpc`
examples. You can get it and generate the Python code with:

```sh
curl -sO https://raw.githubusercontent.com/grpc/grpc/89341001058172bd25ff1392dd7653b48d39dc62/examples/protos/hellostreamingworld.proto
python3 -m grpc_tools.protoc -I. --python_out=. --mypy_out=. --grpc_python_out=. --mypy_grpc_out=. hellostreamingworld.proto
```

This will generate `hellostreamingworld_pb2.py`, `hellostreamingworld_pb2.pyi`,
`hellostreamingworld_pb2_grpc.py` and `hellostreamingworld_pb2_grpc.pyi`.

The following client uses the `GrpcStreamBroadcaster` to automatically manage
the stream and broadcast messages to multiple receivers. It also shows how to
reuse the broadcaster for requests with the same `name`.

> [!NOTE]
> You'll need to install the `frequenz-channels` package to use the
> `Receiver` class:
>
> ```sh
> python3 -m pip install frequenz-channels
> ```

```python
from __future__ import annotations

import asyncio

from frequenz.channels import Receiver, merge
from frequenz.client.base.streaming import GrpcStreamBroadcaster
from frequenz.client.base.client import BaseApiClient
from frequenz.client.base.exception import ClientNotConnected

# The following imports are from the generated files
import hellostreamingworld_pb2 as hsw_pb2
import hellostreamingworld_pb2_grpc as hsw_pb2_grpc


class StreamingGreeterApiClient(BaseApiClient[hsw_pb2_grpc.MultiGreeterStub]):
    """A client for the MultiGreeter service."""

    def __init__(
        self,
        server_url: str,
        *,
        connect: bool = True,
    ) -> None:
        """Create a new StreamingGreeter client.

        Args:
            server_url: The URL of the Greeter service.
            connect: Whether to connect to the server immediately.
        """
        super().__init__(
            server_url,
            hsw_pb2_grpc.MultiGreeterStub,
            connect=connect,
        )
        self._stream_broadcasters: dict[
            str, GrpcStreamBroadcaster[hsw_pb2.HelloReply, str]
        ] = {}

    @property
    def stub(self) -> hsw_pb2_grpc.MultiGreeterAsyncStub:
        """The gRPC stub for the API.

        Raises:
            ClientNotConnected: if the client is not connected.

        Returns:
            The gRPC stub.
        """
        if self._stub is None:
            raise ClientNotConnected(server_url=self.server_url, operation="stub")
        # This type: ignore is needed because we need to cast the sync stub to
        # the async stub, but we can't use cast because the async stub doesn't
        # actually exists to the eyes of the interpreter, it only exists for the
        # type-checker, so it can only be used for type hints.
        return self._stub  # type: ignore

    def say_hello_stream(self, name: str, *, buffer_size: int = 50) -> Receiver[str]:
        """Stream greetings from the server.

        This method reuses the stream for the same name. If every receiver of
        that stream was closed, the next call starts the stream again. A stream
        that has ended is not started again.

        Args:
            name: The name to greet.
            buffer_size: The size of the receiver buffer.

        Returns:
            A receiver that will receive the greeting messages.
        """
        broadcaster = self._stream_broadcasters.get(name)
        if broadcaster is None:
            client_id = hex(id(self))[2:]
            stream_name = f"greeter-client-{client_id}-say-hello-stream-{name}"
            broadcaster = GrpcStreamBroadcaster(
                stream_name,
                lambda: self.stub.sayHello(
                    # We hardcode the number of greetings to 10,000 for this
                    # example, just to simulate a continuous stream.
                    hsw_pb2.HelloRequest(name=name, num_greetings=str(10_000))
                ),
                lambda reply: reply.message,
            )
            self._stream_broadcasters[name] = broadcaster
        return broadcaster.new_receiver(maxsize=buffer_size)


async def main() -> None:
    """Create a client and stream greetings."""
    async with StreamingGreeterApiClient(
        server_url="grpc://localhost:50051?ssl=off"
    ) as client:
        # Create two receivers for the same stream
        receiver1 = client.say_hello_stream("Frequenz")
        receiver2 = client.say_hello_stream("Frequenz")  # This will reuse the stream

        # Create a receiver for a different stream
        receiver3 = client.say_hello_stream("world")

        async def print_greetings(name: str, receiver: Receiver[str]) -> None:
            """Print greetings from a receiver."""
            async for message in receiver:
                print(f"{name}: {message}")
            print(f"{name}: Stream finished.")

        i = 0
        async for msg in merge(receiver1, receiver2, receiver3):
            print(f"Received message {i}: {msg}")
            i += 1
            if i >= 10:
                print("Stopping after 10 messages.")
                break


if __name__ == "__main__":
    asyncio.run(main())
```

If you want to test it, you can use the [example Python
server](https://github.com/grpc/grpc/blob/89341001058172bd25ff1392dd7653b48d39dc62/examples/python/hellostreamingworld/async_greeter_server.py):

```console
$ curl -sO https://raw.githubusercontent.com/grpc/grpc/89341001058172bd25ff1392dd7653b48d39dc62/examples/python/hellostreamingworld/async_greeter_server.py
$ python async_greeter_server.py
INFO:root:Starting server on [::]:50051
```

Running the client:

```console
$ python3 streaming_client.py
Received message 0: Hello number 0, Frequenz!
Received message 1: Hello number 0, Frequenz!
Received message 2: Hello number 1, Frequenz!
Received message 3: Hello number 1, Frequenz!
Received message 4: Hello number 2, Frequenz!
Received message 5: Hello number 0, world!
Received message 6: Hello number 2, Frequenz!
Received message 7: Hello number 1, world!
Received message 8: Hello number 3, Frequenz!
Received message 9: Hello number 3, Frequenz!
Stopping after 10 messages.
```

#### Authorization and Signing

This library also provides utilities for handling authorization and message
signing. You can just pass to the `BaseApiClient` constructor an `auth_key` and
`sign_secret` to enable these features.  The base client will handle adding
the necessary headers to the requests and signing the messages automatically by
using gRPC interceptors.

```python
from __future__ import annotations

import asyncio

from frequenz.client.base.client import BaseApiClient, call_stub_method
from frequenz.client.base.exception import ClientNotConnected

# The following imports are from the generated files
import helloworld_pb2
import helloworld_pb2_grpc


class GreeterApiClient(BaseApiClient[helloworld_pb2_grpc.GreeterStub]):
    """A client for the Greeter service."""

    def __init__(
        self,
        server_url: str,
        *,
        auth_key: str | None = None,
        sign_secret: str | None = None,
        connect: bool = True,
    ) -> None:
        """Create a new Greeter client.

        Args:
            server_url: The URL of the Greeter service.
            connect: Whether to connect to the server immediately.
            auth_key: The authorization key to use for the client.
            sign_secret: The secret used to sign messages sent by the client.
        """
        super().__init__(
            server_url,
            helloworld_pb2_grpc.GreeterStub,
            connect=connect,
            auth_key=auth_key,
            sign_secret=sign_secret,
        )
```

## Documentation

For more information, please read the [documentation
website](https://frequenz-floss.github.io/frequenz-client-base-python/).

## Contributing

If you want to know how to build this project and contribute to it, please
check out the [Contributing Guide](CONTRIBUTING.md).
