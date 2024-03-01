# Frequenz Client Base Library Release Notes

## Summary

This release does a bit of restructuring and renaming of classes and modules. It also adds some new features and fixes some bugs.

## Upgrading

The project structure was updated to use more consistent and shorter modules and class names.

* `frequenz.client.base.grpc_streaming_helper` was renamed to `frequenz.client.base.streaming`.

   - The `GrpcStreamingHelper` class was renamed to `GrpcStreamBroadcaster`.

      + The constructor argument `retry_spec` was renamed to `retry_strategy`.

* `frequenz.client.base.retry_strategy` was renamed to `frequenz.client.base.retry`.

   - The `RetryStrategy` class was renamed to `Strategy`.

## New Features

* Functions to convert to `datetime` and protobufs `Timestamp` have been added.
* The generated documentation was improved to include information on defaults and generic parameters.

## Bug Fixes

* When copying `RetryStrategy`s, the type now will be correctly set to the original type.
