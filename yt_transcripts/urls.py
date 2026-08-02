"""Parse YouTube video and playlist references."""

from dataclasses import dataclass
import re
from typing import Literal
from urllib.parse import ParseResult, parse_qs, urlparse


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_PREFIXES = ("PL", "UU", "OL", "LL", "FL")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
# "videoseries" is a playlist placeholder path, not a video, but it happens to be
# exactly 11 URL-safe characters and so matches VIDEO_ID_RE.
PLAYLIST_PLACEHOLDER_PATHS = {"videoseries"}


@dataclass(frozen=True)
class InputRef:
    """A normalized video or playlist reference."""

    kind: Literal["video", "playlist"]
    value: str


def parse_input(raw: str, force_playlist: bool = False) -> InputRef:
    """Normalize a supported YouTube URL or bare ID.

    Any URL that identifies a specific video -- whether through ``v`` or through
    a ``youtu.be`` / ``/shorts/`` / ``/embed/`` path -- is a video even when it
    also carries ``list``, unless ``force_playlist`` is true.
    """

    value = raw.strip()
    if not value:
        raise ValueError(f"Unrecognized YouTube input: {raw!r}")

    # The bare video ID test must come first: a video ID may legitimately start
    # with a playlist prefix. Real playlist IDs are never exactly 11 characters
    # (PL + 16 or 32 characters, UU + 22), so an exactly-11-character match is
    # unambiguously a video ID.
    if VIDEO_ID_RE.fullmatch(value):
        return InputRef("video", value)
    if value.startswith(PLAYLIST_PREFIXES) and re.fullmatch(
        r"[A-Za-z0-9_-]+", value
    ):
        return InputRef("playlist", value)

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unrecognized YouTube input: {raw!r}")

    query = parse_qs(parsed.query, keep_blank_values=True)
    query_video_id = _first_nonempty(query.get("v", []))
    playlist_id = _first_nonempty(query.get("list", []))

    # youtu.be, /shorts/ and /embed/ links carry the video in the path instead
    # of a v= query, so the path must be resolved before the playlist-only
    # branch below. Otherwise a shared "watching inside a playlist" link such as
    # youtu.be/VIDEO_ID?list=PL... would silently expand to the whole playlist.
    video_id = query_video_id or _path_video_id(parsed)

    if video_id is not None and playlist_id is not None:
        selected = playlist_id if force_playlist else video_id
        kind: Literal["video", "playlist"] = (
            "playlist" if force_playlist else "video"
        )
        if kind == "video" and not VIDEO_ID_RE.fullmatch(selected):
            raise ValueError(f"Unrecognized YouTube input: {raw!r}")
        return InputRef(kind, selected)

    # A list query is accepted on any URL because YouTube emits playlist links
    # through several hostnames and redirect surfaces.
    if playlist_id is not None:
        return InputRef("playlist", playlist_id)

    if video_id is not None and VIDEO_ID_RE.fullmatch(video_id):
        return InputRef("video", video_id)
    raise ValueError(f"Unrecognized YouTube input: {raw!r}")


def _path_video_id(parsed: ParseResult) -> str | None:
    """Return the video ID carried in a URL path, if the path holds one.

    Only a structurally valid ID is returned so that playlist surfaces such as
    ``youtu.be/videoseries?list=PL...`` still resolve to their playlist.
    """

    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in YOUTUBE_HOSTS:
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed"}:
            candidate = path_parts[1]
        else:
            candidate = ""
    else:
        candidate = ""
    if candidate in PLAYLIST_PLACEHOLDER_PATHS:
        return None
    return candidate if VIDEO_ID_RE.fullmatch(candidate) else None


def _first_nonempty(values: list[str]) -> str | None:
    """Return the first non-empty query value."""

    return next((value for value in values if value), None)
