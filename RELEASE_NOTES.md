# Frequenz Client Base Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

<!-- Here goes notes on how to upgrade from previous versions, including deprecations and what they should be replaced with -->

- The retry count of `GrpcStreamBroadcaster` is now reset when a message arrives. A limit in `retry_strategy` now counts only the retries in a row that receive no message, so a limit above 0 no longer stops a stream that gets a message on every connection. With `ExponentialBackoff`, the wait also starts again from `initial_interval`.
- `GrpcStreamBroadcaster` now stops its stream once every receiver it handed out is closed or garbage-collected, and `is_running` is then False. Keep a receiver referenced for as long as you read from it. Calling `new_receiver()` again starts the stream again, unless `stop()` was called.
- `GrpcStreamBroadcaster.new_receiver()` now returns a plain `Receiver` that wraps the channel receiver. `len()` on it and `Merger.stop()` no longer work; use `close()` to stop receiving.

## New Features

<!-- Here goes the main new features and examples or instructions on how to use them -->

- `GrpcStreamBroadcaster` takes an `idle_timeout`, which must be positive. A call that receives no message for that long is cancelled and retried according to `retry_strategy`. The `StreamRetrying` event, or the `StreamFatalError` event once retries run out, then carries a `StreamIdleTimeoutError`.
- `GrpcStreamBroadcaster` stops, and cancels its call, once every receiver it handed out is closed or garbage-collected. This also happens while the stream is stalled or retrying, so an abandoned stream no longer retries forever.
- A `GrpcStreamBroadcaster` that never handed out a receiver is not stopped for lack of receivers. It runs until its stream ends, gives up or fails, or `stop()` is called.

## Bug Fixes

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->

- `GrpcStreamBroadcaster` now ends its receivers when the stream fails with an unexpected error, and sends `StreamFatalError` to receivers with events. Before, they waited forever.
- `GrpcStreamBroadcaster.stop()` no longer swallows a cancellation of the task that awaits it.
- `GrpcStreamBroadcaster.new_receiver(include_events=True)` now returns a receiver that ends at once when called after `stop()`, or after the stream ended or gave up. If no receiver with events was created before, it used to wait forever.
