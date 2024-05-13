# Frequenz Client Base Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

- You should now install the dependency using `frequenz-client-base[grpcio]` (or `frequenz-client-base[grpclib]`) if you want to migrate to `grpclib`).

## New Features

- `GrpcStreamBroadcaster` is now compatible with both `grpcio` and `grpclib` implementations of gRPC. Just install `frequenz-client-base[grpcio]` or `frequenz-client-base[grpclib]` to use the desired implementation and everything should work as expected.

## Bug Fixes

- Fixed retrying for `GrpcStreamBroadcaster` when the retry interval is set to 0 (before it would stop retrying if the interval was set to 0).
