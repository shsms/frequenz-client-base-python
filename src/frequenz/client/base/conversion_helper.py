# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Helper functions to convert to/from common python types."""

from datetime import datetime, timezone
from typing import overload

# pylint: disable=no-name-in-module
from google.protobuf.timestamp_pb2 import Timestamp

# pylint: enable=no-name-in-module


@overload
def to_timestamp(dt: datetime) -> Timestamp:
    """Convert a datetime to a protobuf Timestamp.

    Args:
        dt: datetime object to convert

    Returns:
        datetime converted to Timestamp
    """


@overload
def to_timestamp(dt: None) -> None:
    """Overload to handle None values.

    Args:
        dt: None

    Returns:
        None
    """


def to_timestamp(dt: datetime | None) -> Timestamp | None:
    """Convert a datetime to a protobuf Timestamp.

    Returns None if dt is None.

    Args:
        dt: datetime object to convert

    Returns:
        datetime converted to Timestamp
    """
    if dt is None:
        return None

    ts = Timestamp()
    ts.FromDatetime(dt)
    return ts


def to_datetime(ts: Timestamp, tz: timezone = timezone.utc) -> datetime:
    """Convert a protobuf Timestamp to a datetime.

    Args:
        ts: Timestamp object to convert
        tz: Timezone to use for the datetime

    Returns:
        Timestamp converted to datetime
    """
    # Add microseconds and add nanoseconds converted to microseconds
    microseconds = int(ts.nanos / 1000)
    return datetime.fromtimestamp(ts.seconds + microseconds * 1e-6, tz=tz)
