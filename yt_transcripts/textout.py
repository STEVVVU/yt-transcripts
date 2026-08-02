"""Clean subtitle text and write portable transcript files."""

import html
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
import re
import textwrap
from typing import Any


ILLEGAL_FILENAME_RE = re.compile(r'[<>:"/\\|?*]')
CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
MARKER_RE = re.compile(
    r"\[(?:music|applause|laughter|laughs|cheering|noise|silence|"
    r"inaudible|foreign|sighs?|gasps?|clapping)\]",
    re.IGNORECASE,
)
VTT_TAG_RE = re.compile(r"<[^>]+>")


def to_plain_text(
    snippets: Iterable[Any], keep_markers: bool = False
) -> str:
    """Convert transcript snippets into clean, wrapped plain text.

    Snippets may be strings, mappings with a ``text`` key, or objects exposing
    a ``text`` attribute.
    """

    chunks = [_snippet_text(snippet) for snippet in snippets]
    combined = " ".join(chunk for chunk in chunks if chunk)
    combined = combined.replace("\r\n", "\n").replace("\r", "\n")
    if not keep_markers:
        combined = MARKER_RE.sub("", combined)

    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", combined):
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        if normalized:
            paragraphs.append(
                textwrap.fill(
                    normalized,
                    width=100,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
    return "\n\n".join(paragraphs)


def safe_filename(title: str, video_id: str) -> str:
    """Create a Windows-safe, unique ``.txt`` filename."""

    cleaned = ILLEGAL_FILENAME_RE.sub("", title)
    cleaned = CONTROL_CHAR_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    cleaned = cleaned[:80].rstrip(" .-")
    if not cleaned:
        return f"{video_id}.txt"
    return f"{cleaned}-{video_id}.txt"


def parse_json3(data: Mapping[str, Any] | str) -> str:
    """Extract text from yt-dlp's structured JSON3 subtitle format."""

    document = json.loads(data) if isinstance(data, str) else data
    lines: list[str] = []
    events = document.get("events", [])
    if not isinstance(events, list):
        return ""
    for event in events:
        if not isinstance(event, Mapping):
            continue
        segments = event.get("segs", [])
        if not isinstance(segments, list):
            continue
        parts: list[str] = []
        for segment in segments:
            if not isinstance(segment, Mapping):
                continue
            text = segment.get("utf8")
            if isinstance(text, str):
                parts.append(text)
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def parse_vtt(content: str) -> str:
    """Extract visible text from VTT subtitles."""

    source_lines = content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    output: list[str] = []
    in_note = False
    for index, raw_line in enumerate(source_lines):
        line = raw_line.strip()
        if line.startswith("NOTE"):
            in_note = True
            continue
        if in_note:
            if not line:
                in_note = False
            continue
        if (
            not line
            or line == "WEBVTT"
            or line.startswith(("Kind:", "Language:", "STYLE", "REGION"))
            or "-->" in line
        ):
            continue
        next_line = (
            source_lines[index + 1].strip()
            if index + 1 < len(source_lines)
            else ""
        )
        if line.isdigit() and "-->" in next_line:
            continue
        visible = html.unescape(VTT_TAG_RE.sub("", line))
        visible = re.sub(r"\s+", " ", visible).strip()
        if not visible:
            continue
        # YouTube's rolling auto-caption cues repeat the same visible line two
        # or three times, so consecutive duplicates must be removed.
        if output and output[-1] == visible:
            continue
        output.append(visible)
    return "\n".join(output)


def write_transcript(
    path: Path,
    title: str,
    video_id: str,
    language_code: str,
    caption_kind: str,
    body: str,
) -> None:
    """Write a UTF-8 transcript with a small metadata header."""

    header = (
        f"Title: {title}\n"
        f"URL: https://www.youtube.com/watch?v={video_id}\n"
        f"Language: {language_code}\n"
        f"Captions: {caption_kind}\n\n"
        "---\n\n"
    )
    path.write_text(f"{header}{body.rstrip()}\n", encoding="utf-8")


def _snippet_text(snippet: Any) -> str:
    """Read text from one supported snippet representation."""

    if isinstance(snippet, str):
        return snippet
    if isinstance(snippet, Mapping):
        value = snippet.get("text", "")
    else:
        value = getattr(snippet, "text", "")
    return value if isinstance(value, str) else str(value)
