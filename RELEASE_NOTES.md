# Frequenz Client Base Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

- `grpclib` was removed, if you used `grpclib` you should switch to `grpcio` instead.

  You should also update your dependency to `frequenz-client-base` (without any `[grpclib]` or `[grpcio]` suffix).

- The `parse_grpc_uri` function (and `BaseApiClient` constructor) now enables SSL by default (`ssl=false` should be passed to disable it).

- The `parse_grpc_uri` and `BaseApiClient` function now accepts a set of defaults to use when the URI does not specify a value for a given option.

## New Features

- The connection URI can now have a few new SSL options:

  * `ssl_root_certificates_path` to specify the path to the root certificates file.
  * `ssl_private_key_path` to specify the path to the private key file.
  * `ssl_certificate_chain_path` to specify the path to the certificate chain file.

## Bug Fixes

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->
