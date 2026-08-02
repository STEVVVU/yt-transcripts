"""Unit tests for transcript text and filename handling."""

from yt_transcripts.textout import (
    parse_json3,
    parse_vtt,
    safe_filename,
    to_plain_text,
)


def test_safe_filename_removes_windows_illegal_characters() -> None:
    """Windows-reserved filename punctuation is removed."""

    assert (
        safe_filename('A <bad>: "title" / test?*', "dQw4w9WgXcQ")
        == "A-bad-title-test-dQw4w9WgXcQ.txt"
    )


def test_safe_filename_empty_title_uses_video_id() -> None:
    """An all-illegal title falls back to the bare video ID."""

    assert safe_filename('<>:"/\\|?*', "dQw4w9WgXcQ") == "dQw4w9WgXcQ.txt"


def test_safe_filename_truncates_title_portion() -> None:
    """Long title portions are limited to 80 characters."""

    filename = safe_filename("x" * 100, "dQw4w9WgXcQ")
    assert filename == f"{'x' * 80}-dQw4w9WgXcQ.txt"


def test_to_plain_text_collapses_whitespace_and_removes_markers() -> None:
    """Text is normalized while common non-speech markers are omitted."""

    snippets = [{"text": "Hello   world"}, {"text": "\n[Music]\tAgain"}]
    assert to_plain_text(snippets) == "Hello world Again"
    assert to_plain_text(snippets, keep_markers=True) == "Hello world [Music] Again"


def test_parse_vtt_deduplicates_consecutive_rolling_cues() -> None:
    """Repeated lines from rolling YouTube cues appear only once."""

    content = """WEBVTT

00:00:00.000 --> 00:00:01.000
<c>Hello</c>

00:00:01.000 --> 00:00:02.000
<00:00:01.000><c>Hello</c>

00:00:02.000 --> 00:00:03.000
world
"""
    assert parse_vtt(content) == "Hello\nworld"


def test_parse_json3_joins_event_segments() -> None:
    """JSON3 segment text is joined in event order."""

    fixture = {
        "events": [
            {"segs": [{"utf8": "Hello "}, {"utf8": "world"}]},
            {"segs": [{"utf8": "Next line"}]},
            {"tStartMs": 5000},
        ]
    }
    assert parse_json3(fixture) == "Hello world\nNext line"
