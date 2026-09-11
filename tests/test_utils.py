import datetime

import pytest

from verification_bot.utils import chunked, format_timedelta


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (datetime.timedelta(seconds=5), "5s"),
        (datetime.timedelta(minutes=2, seconds=3), "2m 3s"),
        (datetime.timedelta(hours=1, minutes=1, seconds=1), "1h 1m 1s"),
        (datetime.timedelta(days=3, hours=4), "3d 4h 0m 0s"),
    ],
)
def test_format_timedelta(delta, expected):
    assert format_timedelta(delta) == expected


def test_chunked_splits_evenly():
    assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunked_rejects_zero_size():
    with pytest.raises(ValueError):
        chunked([1], 0)
