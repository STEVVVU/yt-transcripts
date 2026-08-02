"""Enumerate YouTube playlists and retrieve video metadata with yt-dlp."""

import logging
from collections.abc import Mapping
from typing import Any

from yt_dlp import YoutubeDL


LOGGER = logging.getLogger(__name__)


class PlaylistError(RuntimeError):
    """Raised when yt-dlp cannot retrieve playlist or video metadata."""


def enumerate_playlist(playlist_id: str) -> list[tuple[str, str]]:
    """Return ``(video_id, title)`` pairs for available playlist entries."""

    # The string limits flat extraction to playlists; True changes behavior for
    # other nested URL results and is not equivalent.
    opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise PlaylistError(
            f"Could not enumerate playlist {playlist_id}: {exc}"
        ) from exc

    if not isinstance(info, Mapping):
        raise PlaylistError(f"Playlist {playlist_id} returned no metadata")

    results: list[tuple[str, str]] = []
    entries = info.get("entries") or []
    for position, entry in enumerate(entries, start=1):
        if entry is None:
            LOGGER.warning(
                "Skipping unavailable playlist entry %d in %s",
                position,
                playlist_id,
            )
            continue
        if not isinstance(entry, Mapping):
            LOGGER.warning(
                "Skipping malformed playlist entry %d in %s",
                position,
                playlist_id,
            )
            continue
        video_id = entry.get("id")
        if not isinstance(video_id, str) or not video_id:
            LOGGER.warning(
                "Skipping playlist entry %d without a video ID in %s",
                position,
                playlist_id,
            )
            continue
        title_value: Any = entry.get("title")
        title = title_value if isinstance(title_value, str) and title_value else video_id
        results.append((video_id, title))
    return results


def get_video_title(video_id: str) -> str:
    """Return a video's title using a metadata-only yt-dlp extraction."""

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise PlaylistError(
            f"Could not retrieve metadata for video {video_id}: {exc}"
        ) from exc

    if not isinstance(info, Mapping):
        raise PlaylistError(f"Video {video_id} returned no metadata")
    title = info.get("title")
    return title if isinstance(title, str) and title else video_id
