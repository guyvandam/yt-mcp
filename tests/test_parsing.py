"""Tests for reference, date, duration and link parsing."""

from datetime import UTC, datetime, timedelta

import pytest

from yt_mcp.errors import InvalidDateError
from yt_mcp.parsing import (
    extract_links,
    format_timestamp,
    format_timestamp_link,
    parse_channel_reference,
    parse_date_filter,
    parse_iso_duration,
    parse_video_id,
    timestamp_url,
    to_rfc3339,
)

CHANNEL_ID = "UCBJycsmduvYEL83R_U4JriQ"


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (CHANNEL_ID, ("id", CHANNEL_ID)),
        ("@mkbhd", ("handle", "mkbhd")),
        ("https://www.youtube.com/@mkbhd", ("handle", "mkbhd")),
        ("https://www.youtube.com/@mkbhd/videos", ("handle", "mkbhd")),
        (f"https://www.youtube.com/channel/{CHANNEL_ID}", ("id", CHANNEL_ID)),
        ("https://www.youtube.com/c/MKBHD", ("username", "MKBHD")),
        (
            "https://www.youtube.com/user/marquesbrownlee",
            ("username", "marquesbrownlee"),
        ),
        ("Marques Brownlee", ("search", "Marques Brownlee")),
    ],
)
def test_parse_channel_reference(reference: str, expected: tuple[str, str]) -> None:
    """Every supported channel reference form is classified correctly."""
    assert parse_channel_reference(reference) == expected


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("not a video", None),
    ],
)
def test_parse_video_id(reference: str, expected: str | None) -> None:
    """Video ids are extracted from ids and every URL shape."""
    assert parse_video_id(reference) == expected


def test_parse_date_filter_relative() -> None:
    """A relative offset resolves to roughly that far in the past."""
    result = parse_date_filter("1y")
    expected = datetime.now(UTC) - timedelta(days=365)
    assert abs((result - expected).total_seconds()) < 60


def test_parse_date_filter_absolute() -> None:
    """A plain date is read as midnight UTC."""
    assert parse_date_filter("2025-01-31") == datetime(2025, 1, 31, tzinfo=UTC)


def test_parse_date_filter_rfc3339() -> None:
    """A trailing Z is accepted and preserved as UTC."""
    assert parse_date_filter("2025-01-31T12:30:00Z") == datetime(
        2025, 1, 31, 12, 30, tzinfo=UTC
    )


def test_parse_date_filter_rejects_garbage() -> None:
    """An unparseable filter raises a tool-facing error."""
    with pytest.raises(InvalidDateError):
        parse_date_filter("last tuesday-ish")


def test_to_rfc3339_normalises_to_utc() -> None:
    """Datetimes are rendered in the Z-suffixed form the API expects."""
    assert to_rfc3339(datetime(2025, 1, 31, tzinfo=UTC)) == "2025-01-31T00:00:00Z"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PT12M34S", 754),
        ("PT1H2M3S", 3723),
        ("PT45S", 45),
        ("P1DT2H", 93600),
        ("", None),
        (None, None),
    ],
)
def test_parse_iso_duration(value: str | None, expected: int | None) -> None:
    """ISO 8601 durations convert to whole seconds."""
    assert parse_iso_duration(value) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (195, "03:15"), (3661, "1:01:01")],
)
def test_format_timestamp(seconds: int, expected: str) -> None:
    """Timestamps drop the hour component below one hour."""
    assert format_timestamp(seconds) == expected


def test_extract_links_dedupes_and_trims() -> None:
    """Description links keep their order, lose trailing punctuation, dedupe."""
    description = (
        "Gear: https://shop.example.com/gear\n"
        "Sources: https://arxiv.org/abs/1234.5678.\n"
        "More gear at https://shop.example.com/gear too"
    )
    assert extract_links(description) == [
        "https://shop.example.com/gear",
        "https://arxiv.org/abs/1234.5678",
    ]


def test_extract_links_handles_empty() -> None:
    """A description with no links yields an empty list."""
    assert extract_links("") == []


def test_timestamp_url_appends_whole_seconds() -> None:
    """A seek URL carries the offset truncated to whole seconds."""
    assert (
        timestamp_url("dQw4w9WgXcQ", 195.7)
        == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=195"
    )


def test_timestamp_url_clamps_negative_offsets() -> None:
    """A negative offset seeks to the start rather than emitting a bad URL."""
    assert timestamp_url("dQw4w9WgXcQ", -5.0).endswith("&t=0")


def test_format_timestamp_link_keeps_the_bracketed_timestamp() -> None:
    """The link text stays '[MM:SS]' so it still reads as a citation."""
    assert format_timestamp_link("dQw4w9WgXcQ", 195.0) == (
        "[[03:15]](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=195)"
    )
