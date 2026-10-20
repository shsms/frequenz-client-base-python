# Frequenz Client Base Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

<!-- Here goes notes on how to upgrade from previous versions, including deprecations and what they should be replaced with -->

- The retry count of `GrpcStreamBroadcaster` is now reset when a message arrives. A limit in `retry_strategy` now counts only the retries in a row that receive no message, so a limit above 0 no longer stops a stream that gets a message on every connection. With `ExponentialBackoff`, the wait also starts again from `initial_interval`.
## New Features

<!-- Here goes the main new features and examples or instructions on how to use them -->

- `GrpcStreamBroadcaster` takes an `idle_timeout`, which must be positive. A call that receives no message for that long is cancelled and retried according to `retry_strategy`. The `StreamRetrying` event, or the `StreamFatalError` event once retries run out, then carries a `StreamIdleTimeoutError`.

## Bug Fixes

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->
