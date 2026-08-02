"""Fetch transcripts through youtube-transcript-api with a yt-dlp fallback."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tempfile
from typing import Any

import youtube_transcript_api
from youtube_transcript_api import YouTubeTranscriptApi
from yt_dlp import YoutubeDL

from yt_transcripts.textout import parse_json3, parse_vtt, to_plain_text


# Import each upstream error defensively because the library has changed its
# public exception set between minor releases. A name that cannot be imported is
# aliased to its own never-raised sentinel class rather than to Exception: an
# Exception alias would turn the surrounding `except` clause into a catch-all
# that swallows ordinary bugs, trigger the blocked-request backoff sleeps for
# them, and make later `except` clauses dead code.
class _UnavailableUpstreamError(Exception):
    """Base for placeholders standing in for errors this version lacks."""


def _import_error(name: str) -> type[BaseException]:
    """Return an upstream exception class or a distinct sentinel subclass."""

    imported = getattr(youtube_transcript_api, name, None)
    if isinstance(imported, type) and issubclass(imported, BaseException):
        return imported
    return type(f"_Missing{name}", (_UnavailableUpstreamError,), {})


TranscriptsDisabled = _import_error("TranscriptsDisabled")
NoTranscriptFound = _import_error("NoTranscriptFound")
VideoUnavailable = _import_error("VideoUnavailable")
RequestBlocked = _import_error("RequestBlocked")
IpBlocked = _import_error("IpBlocked")
PoTokenRequired = _import_error("PoTokenRequired")
AgeRestricted = _import_error("AgeRestricted")
YouTubeDataUnparsable = _import_error("YouTubeDataUnparsable")


class TranscriptError(RuntimeError):
    """Raised when no transcript can be fetched for a video."""


class _EmptyTranscriptError(RuntimeError):
    """Signal that a nominally successful primary response had no text."""


@dataclass(frozen=True)
class TranscriptResult:
    """The normalized transcript and its source metadata."""

    text: str
    language_code: str
    caption_kind: str


def fetch_transcript(
    video_id: str,
    languages: list[str],
    *,
    allow_fallback: bool = True,
    keep_markers: bool = False,
) -> TranscriptResult:
    """Fetch one video's original-language transcript.

    yt-dlp subtitle extraction is attempted only for primary failures known to
    benefit from the alternate extraction path.
    """

    try:
        return _fetch_primary(video_id, languages, keep_markers)
    except (RequestBlocked, IpBlocked):
        raise
    except (
        PoTokenRequired,
        NoTranscriptFound,
        TranscriptsDisabled,
        YouTubeDataUnparsable,
        _EmptyTranscriptError,
    ) as exc:
        if not allow_fallback:
            raise TranscriptError(
                f"Primary transcript fetch failed for {video_id}: {exc}"
            ) from exc
        try:
            return _fetch_with_ytdlp(video_id, languages, keep_markers)
        except Exception as fallback_exc:
            raise TranscriptError(
                f"Both transcript methods failed for {video_id}: "
                f"{fallback_exc}"
            ) from fallback_exc
    except (VideoUnavailable, AgeRestricted) as exc:
        raise TranscriptError(
            f"Transcript unavailable for {video_id}: {exc}"
        ) from exc


def _fetch_primary(
    video_id: str, languages: list[str], keep_markers: bool
) -> TranscriptResult:
    """Fetch captions with youtube-transcript-api's instance API."""

    ytt = YouTubeTranscriptApi()
    transcript_list = ytt.list(video_id)
    try:
        # Human-created captions are generally cleaner than generated captions.
        transcript = transcript_list.find_manually_created_transcript(languages)
        caption_kind = "manual"
    except Exception:
        transcript = transcript_list.find_generated_transcript(languages)
        caption_kind = "auto-generated"

    # Deliberately do not call translate(): translated tracks are especially
    # prone to YouTube HTTP 429 responses. Only original tracks are fetched.
    fetched = transcript.fetch()
    text = to_plain_text(fetched, keep_markers=keep_markers)
    if not text:
        raise _EmptyTranscriptError("the primary caption response was empty")
    language_code = getattr(transcript, "language_code", "unknown")
    return TranscriptResult(text, str(language_code), caption_kind)


def _fetch_with_ytdlp(
    video_id: str, languages: list[str], keep_markers: bool
) -> TranscriptResult:
    """Fetch and parse subtitle files using yt-dlp."""

    with tempfile.TemporaryDirectory() as temp_name:
        temp_dir = Path(temp_name)
        base_opts: dict[str, Any] = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json3/vtt/best",
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        url = f"https://www.youtube.com/watch?v={video_id}"

        # yt-dlp matches subtitleslangs as regexes, so asking for "en.*" on a
        # non-English video also matches YouTube's machine-TRANSLATED
        # auto-caption tracks. Those translated tracks are exactly the ones that
        # answer HTTP 429 (yt-dlp issue #13831), which is the failure this tool
        # avoids by never calling translate(). So probe the available tracks
        # first and request only original ones by their exact language key.
        with YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        selected = _select_original_langs(info, languages)
        if not selected:
            raise TranscriptError(
                "yt-dlp found no original-language caption track matching "
                f"{', '.join(languages)}"
            )

        opts = {
            **base_opts,
            "subtitleslangs": [_subtitle_pattern(lang) for lang in selected],
        }
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        subtitle_path = _find_subtitle_file(temp_dir, video_id, selected)
        if subtitle_path is None:
            raise TranscriptError("yt-dlp produced no supported subtitle file")

        raw = subtitle_path.read_text(encoding="utf-8")
        if subtitle_path.suffix.lower() == ".json3":
            parsed = parse_json3(json.loads(raw))
        else:
            parsed = parse_vtt(raw)
        text = to_plain_text([parsed], keep_markers=keep_markers)
        if not text:
            raise TranscriptError("yt-dlp produced an empty subtitle")

        track_key = _language_from_path(subtitle_path, video_id)
        caption_kind = _ytdlp_caption_kind(info, track_key)
        # yt-dlp labels the original auto-caption track "<code>-orig"; report the
        # plain language code because the suffix is an internal marker.
        language_code = _strip_orig_suffix(track_key)
        return TranscriptResult(text, language_code, caption_kind)


def _subtitle_pattern(language: str) -> str:
    """Convert a resolved caption track key into a yt-dlp subtitle pattern.

    yt-dlp treats ``subtitleslangs`` entries as full-match regexes. The keys are
    already exact, so they are escaped rather than widened with a wildcard: a
    wildcard would also match machine-translated tracks.
    """

    return re.escape(language)


ORIG_SUFFIX = "-orig"


def _select_original_langs(info: Any, languages: list[str]) -> list[str]:
    """Resolve requested languages to the video's original caption tracks.

    Returns yt-dlp caption keys in the caller's language preference order.
    Machine-translated automatic-caption tracks are never returned: they are the
    tracks YouTube answers with HTTP 429 (yt-dlp issue #13831), so a video whose
    only match is a translation is reported as having no transcript instead.
    """

    if not isinstance(info, dict):
        return []
    manual = _track_keys(info.get("subtitles"))
    auto = _track_keys(info.get("automatic_captions"))

    # Keys ending in "-orig" mark the original audio language explicitly; the
    # extractor also exposes it as info["language"]. An unsuffixed automatic key
    # is the original track only when it names that same language.
    original_codes = {
        key[: -len(ORIG_SUFFIX)] for key in auto if key.endswith(ORIG_SUFFIX)
    }
    declared = info.get("language")
    if isinstance(declared, str) and declared:
        original_codes.add(declared)

    selected: list[str] = []
    for language in languages:
        for variant in (language, *_regional_variants(manual | auto, language)):
            # One key per variant, best first, so the same track is not
            # downloaded twice: manual captions are authored (yt-dlp files
            # translations of them under automatic_captions instead), then the
            # explicit original marker, then an unsuffixed automatic track that
            # names the video's own audio language.
            candidates = (
                variant if variant in manual else None,
                f"{variant}{ORIG_SUFFIX}"
                if f"{variant}{ORIG_SUFFIX}" in auto
                else None,
                variant if variant in auto and variant in original_codes else None,
            )
            best = next((key for key in candidates if key is not None), None)
            if best is not None and best not in selected:
                selected.append(best)
    return selected


def _track_keys(tracks: Any) -> set[str]:
    """Return the language keys of one yt-dlp caption mapping."""

    if not isinstance(tracks, dict):
        return set()
    return {key for key in tracks if isinstance(key, str)}


def _regional_variants(keys: set[str], language: str) -> list[str]:
    """Return available regional refinements of a language tag, e.g. en-GB."""

    prefix = f"{language}-"
    return sorted(
        _strip_orig_suffix(key)
        for key in keys
        if key.startswith(prefix) and _strip_orig_suffix(key) != language
    )


def _strip_orig_suffix(language: str) -> str:
    """Remove yt-dlp's original-track marker from a caption language key."""

    if language.endswith(ORIG_SUFFIX):
        return language[: -len(ORIG_SUFFIX)] or language
    return language


def _find_subtitle_file(
    temp_dir: Path, video_id: str, languages: list[str]
) -> Path | None:
    """Find a downloaded subtitle, preferring JSON3 over VTT.

    Within a format, languages are tried in the caller's preference order, so
    ``en`` wins over ``en-GB`` even though ``-`` sorts before ``.``.
    """

    for extension in ("json3", "vtt"):
        for language in languages:
            candidate = temp_dir / f"{video_id}.{language}.{extension}"
            if candidate.is_file():
                return candidate
        matches = sorted(temp_dir.glob(f"{video_id}*.{extension}"))
        if matches:
            return matches[0]
    return None


def _language_from_path(path: Path, video_id: str) -> str:
    """Infer a subtitle language code from yt-dlp's output filename."""

    prefix = f"{video_id}."
    name_without_format = path.name[: -len(path.suffix)]
    if name_without_format.startswith(prefix):
        language = name_without_format[len(prefix) :].rstrip(".")
        if language:
            return language
    return "unknown"


def _ytdlp_caption_kind(info: Any, language_code: str) -> str:
    """Determine whether yt-dlp selected manual or generated captions."""

    if isinstance(info, dict):
        subtitles = info.get("subtitles")
        if isinstance(subtitles, dict) and language_code in subtitles:
            return "manual"
    return "auto-generated"
