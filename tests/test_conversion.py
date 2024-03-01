# License: MIT
# Copyright © 2024 Frequenz Energy-as-a-Service GmbH

"""Test conversion helper functions."""

from datetime import datetime, timezone

# pylint: disable=no-name-in-module
from google.protobuf.timestamp_pb2 import Timestamp

# pylint: enable=no-name-in-module
from hypothesis import given
from hypothesis import strategies as st

from frequenz.client.base.conversion import to_datetime, to_timestamp

# Strategy for generating datetime objects
datetime_strategy = st.datetimes(
    min_value=datetime(1970, 1, 1),
    max_value=datetime(9999, 12, 31),
    timezones=st.just(timezone.utc),
)

# Strategy for generating Timestamp objects
timestamp_strategy = st.builds(
    Timestamp,
    seconds=st.integers(
        min_value=0,
        max_value=int(datetime(9999, 12, 31, tzinfo=timezone.utc).timestamp()),
    ),
)


@given(datetime_strategy)
def test_to_timestamp_with_datetime(dt: datetime) -> None:
    """Test conversion from datetime to Timestamp."""
    ts = to_timestamp(dt)
    assert ts is not None
    converted_back_dt = to_datetime(ts)
    assert dt.tzinfo == converted_back_dt.tzinfo
    assert dt.timestamp() == converted_back_dt.timestamp()


def test_to_timestamp_with_none() -> None:
    """Test that passing None returns None."""
    assert to_timestamp(None) is None


@given(timestamp_strategy)
def test_to_datetime(ts: Timestamp) -> None:
    """Test conversion from Timestamp to datetime."""
    dt = to_datetime(ts)
    assert dt is not None
    # Convert back to Timestamp and compare
    converted_back_ts = to_timestamp(dt)
    assert ts.seconds == converted_back_ts.seconds


@given(datetime_strategy)
def test_no_none_datetime(dt: datetime) -> None:
    """Test behavior of type hinting."""
    ts: Timestamp = to_timestamp(dt)
    dt_none: datetime | None = None

    # The test would fail without the ignore comment as it should.
    ts2: Timestamp = to_timestamp(dt_none)  # type: ignore

    assert ts is not None
    assert ts2 is None
