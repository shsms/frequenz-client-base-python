# Frequenz Client Base Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

- `channel.parse_grpc_uri()` takes an extra argument, the channel type (which can be either `grpclib.client.Channel` or `grpcio.aio.Channel`).

## New Features

- Add a `exception` module to provide client exceptions, including gRPC errors with one subclass per gRPC error status code.
- `channel.parse_grpc_uri()` can now be used with `grpcio` too.
- A new `BaseApiClient` class is introduced to provide a base class for API clients. It is strongly recommended to use this class as a base class for all API clients.

## Bug Fixes

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->
