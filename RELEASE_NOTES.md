# Frequenz Client Base Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

- `grpclib` was removed, if you used `grpclib` you should switch to `grpcio` instead.

  You should also update your dependency to `frequenz-client-base` (without any `[grpclib]` or `[grpcio]` suffix).

- The `parse_grpc_uri` function (and `BaseApiClient` constructor) now enables SSL by default (`ssl=false` should be passed to disable it).

- The `parse_grpc_uri` function now accepts an optional `default_ssl` parameter to set the default value for the `ssl` parameter when not present in the URI.

## New Features

<!-- Here goes the main new features and examples or instructions on how to use them -->

## Bug Fixes

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->
