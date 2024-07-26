# Frequenz Client Base Library Release Notes

## Summary

The main features of this release is the new base class for API clients, gRPC exception wrappers and a new utility function to call stub methods.

## Upgrading

- `channel.parse_grpc_uri()` takes an extra argument, the channel type (which can be either `grpclib.client.Channel` or `grpcio.aio.Channel`).

## New Features

- Add a `exception` module to provide client exceptions, including gRPC errors with one subclass per gRPC error status code.
- `channel.parse_grpc_uri()` can now be used with `grpcio` too.
- A new `BaseApiClient` class is introduced to provide a base class for API clients. It is strongly recommended to use this class as a base class for all API clients.
- A new `call_stub_method()` function to simplify calling stub methods, converting gRPC errors to `ApiClientError`s, checking if the client is connected and optionally wrapping the response.
