# Frequenz Client Base Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

- You should now install the dependency using `frequenz-client-base[grpcio]` (or `frequenz-client-base[grpclib]`) if you want to migrate to `grpclib`).

## New Features

- `GrpcStreamBroadcaster` is now compatible with both `grpcio` and `grpclib` implementations of gRPC. Just install `frequenz-client-base[grpcio]` or `frequenz-client-base[grpclib]` to use the desired implementation and everything should work as expected.

## Bug Fixes

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->
