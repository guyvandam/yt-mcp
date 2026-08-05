"""Tests for transcript chunking and windowing."""

from dataclasses import dataclass

from yt_mcp.transcripts import _chunk, _within


@dataclass
class Cue:
    """Stand-in for a youtube_transcript_api caption cue."""

    text: str
    start: float
    duration: float


CUES = [
    Cue("the new battery", 0.0, 2.0),
    Cue("is 17% larger", 2.0, 2.0),
    Cue("than last\nyear", 31.0, 2.0),
]


def test_chunk_merges_cues_within_window() -> None:
    """Cues inside one window collapse into a single timestamped line."""
    assert _chunk(CUES, 30.0) == [
        "[00:00] the new battery is 17% larger",
        "[00:31] than last year",
    ]


def test_chunk_zero_keeps_raw_cues() -> None:
    """A zero window keeps YouTube's own cue boundaries."""
    assert _chunk(CUES, 0) == [
        "[00:00] the new battery",
        "[00:02] is 17% larger",
        "[00:31] than last year",
    ]


def test_chunk_uses_hour_timestamps_for_long_videos() -> None:
    """Past an hour the timestamp gains an hour component."""
    assert _chunk([Cue("still going", 3675.0, 2.0)], 30.0) == ["[1:01:15] still going"]


def test_within_bounds() -> None:
    """The window is inclusive at the start and exclusive at the end."""
    assert _within(10.0, None, None)
    assert _within(10.0, 10.0, 20.0)
    assert not _within(9.9, 10.0, None)
    assert not _within(20.0, None, 20.0)
