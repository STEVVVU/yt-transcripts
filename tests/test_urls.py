"""Unit tests for YouTube input parsing."""

import pytest

from yt_transcripts.urls import InputRef, parse_input


VIDEO_ID = "dQw4w9WgXcQ"
PLAYLIST_ID = "PL1234567890abcdef"


@pytest.mark.parametrize(
    "raw",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        VIDEO_ID,
    ],
)
def test_parse_video_forms(raw: str) -> None:
    """Every supported video form normalizes to a bare ID."""

    assert parse_input(raw) == InputRef("video", VIDEO_ID)


@pytest.mark.parametrize(
    "raw",
    [
        f"https://www.youtube.com/playlist?list={PLAYLIST_ID}",
        f"https://example.com/redirect?list={PLAYLIST_ID}",
        PLAYLIST_ID,
        "UUabcdefghijk",
        "OLabcdefghijk",
        "LLabcdefghijk",
        "FLabcdefghijk",
    ],
)
def test_parse_playlist_forms(raw: str) -> None:
    """Playlist URLs and supported bare playlist IDs are accepted."""

    expected = raw if "://" not in raw else PLAYLIST_ID
    assert parse_input(raw) == InputRef("playlist", expected)


def test_video_wins_for_watch_url_inside_playlist() -> None:
    """A watch URL defaults to its single video."""

    raw = (
        f"https://www.youtube.com/watch?v={VIDEO_ID}"
        f"&list={PLAYLIST_ID}"
    )
    assert parse_input(raw) == InputRef("video", VIDEO_ID)


def test_force_playlist_for_watch_url_inside_playlist() -> None:
    """The force flag selects the playlist from a mixed watch URL."""

    raw = (
        f"https://www.youtube.com/watch?v={VIDEO_ID}"
        f"&list={PLAYLIST_ID}"
    )
    assert parse_input(raw, force_playlist=True) == InputRef(
        "playlist", PLAYLIST_ID
    )


@pytest.mark.parametrize(
    "raw",
    [
        f"https://youtu.be/{VIDEO_ID}?list={PLAYLIST_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}?list={PLAYLIST_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}?list={PLAYLIST_ID}",
    ],
)
def test_video_wins_for_path_video_inside_playlist(raw: str) -> None:
    """A path-borne video ID beats list=, as YouTube's Share button adds it."""

    assert parse_input(raw) == InputRef("video", VIDEO_ID)


@pytest.mark.parametrize(
    "raw",
    [
        f"https://youtu.be/{VIDEO_ID}?list={PLAYLIST_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}?list={PLAYLIST_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}?list={PLAYLIST_ID}",
    ],
)
def test_force_playlist_for_path_video_inside_playlist(raw: str) -> None:
    """The force flag still selects the playlist from a path-borne video URL."""

    assert parse_input(raw, force_playlist=True) == InputRef(
        "playlist", PLAYLIST_ID
    )


def test_videoseries_placeholder_path_stays_a_playlist() -> None:
    """``videoseries`` is a playlist placeholder that is also 11 characters."""

    raw = f"https://youtu.be/videoseries?list={PLAYLIST_ID}"
    assert parse_input(raw) == InputRef("playlist", PLAYLIST_ID)


def test_youtu_be_timestamp_parameter_is_a_video() -> None:
    """An unrelated query parameter does not disturb video detection."""

    assert parse_input(f"https://youtu.be/{VIDEO_ID}?t=42") == InputRef(
        "video", VIDEO_ID
    )


def test_eleven_character_pl_prefixed_id_is_a_video() -> None:
    """Playlist IDs are never 11 characters, so this length means video."""

    assert parse_input("PL2mF9zPobc") == InputRef("video", "PL2mF9zPobc")


def test_full_length_pl_prefixed_id_is_a_playlist() -> None:
    """A real-length PL id is still recognized as a playlist."""

    assert parse_input(PLAYLIST_ID) == InputRef("playlist", PLAYLIST_ID)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not-a-youtube-reference",
        "https://www.youtube.com/watch?v=too-short",
        "https://example.com/video/dQw4w9WgXcQ",
    ],
)
def test_invalid_inputs_raise_value_error(raw: str) -> None:
    """Unrecognized values report the offending input."""

    with pytest.raises(ValueError, match="Unrecognized YouTube input"):
        parse_input(raw)
