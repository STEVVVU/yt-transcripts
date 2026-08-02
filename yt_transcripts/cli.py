"""Command-line interface for downloading YouTube transcripts."""

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import random
import sys
import time

from yt_transcripts.playlist import (
    PlaylistError,
    enumerate_playlist,
    get_video_title,
)
from yt_transcripts.textout import safe_filename, write_transcript
from yt_transcripts.transcript import (
    IpBlocked,
    RequestBlocked,
    TranscriptError,
    TranscriptResult,
    fetch_transcript,
)
from yt_transcripts.urls import parse_input


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoJob:
    """A video queued for transcript retrieval."""

    video_id: str
    title: str | None


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""

    parser = argparse.ArgumentParser(
        prog="yt-transcripts",
        description="Write plain-text transcripts for YouTube videos and playlists.",
    )
    parser.add_argument("inputs", nargs="+", metavar="URL_OR_ID")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("./transcripts"),
        metavar="DIR",
        help="output directory (default: ./transcripts)",
    )
    parser.add_argument(
        "--langs",
        default="en,en-US,en-GB",
        help="comma-separated language preferences",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="prefer list= when a URL also identifies a single video",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing non-empty transcript files",
    )
    parser.add_argument(
        "--keep-markers",
        action="store_true",
        help="keep bracketed markers such as [Music]",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="disable the yt-dlp subtitle fallback",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="suppress diagnostics"
    )
    verbosity.add_argument(
        "-v", "--verbose", action="store_true", help="enable debug diagnostics"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.quiet, args.verbose)

    languages = [lang.strip() for lang in args.langs.split(",") if lang.strip()]
    if not languages:
        parser.error("--langs must contain at least one language code")

    refs = []
    for raw in args.inputs:
        try:
            refs.append(parse_input(raw, force_playlist=args.playlist))
        except ValueError as exc:
            parser.error(str(exc))

    args.output.mkdir(parents=True, exist_ok=True)
    jobs: list[VideoJob] = []
    expansion_failures = 0
    for ref in refs:
        if ref.kind == "video":
            jobs.append(VideoJob(ref.value, None))
            continue
        try:
            entries = enumerate_playlist(ref.value)
        except PlaylistError as exc:
            expansion_failures += 1
            LOGGER.error("%s", exc)
            continue
        jobs.extend(VideoJob(video_id, title) for video_id, title in entries)

    written = 0
    skipped = 0
    failed = expansion_failures
    total = len(jobs)
    for index, job in enumerate(jobs, start=1):
        fetched = False
        existing = _existing_transcript(args.output, job.video_id)
        if existing is not None and not args.overwrite:
            skipped += 1
            _progress(index, total, "SKIP", job.video_id, existing.name)
        else:
            title = job.title or _title_or_id(job.video_id)
            target = args.output / safe_filename(title, job.video_id)
            if (
                target.exists()
                and target.stat().st_size > 0
                and not args.overwrite
            ):
                skipped += 1
                _progress(index, total, "SKIP", job.video_id, target.name)
            else:
                fetched = True
                result = _fetch_with_backoff(job.video_id, languages, args)
                if result is None:
                    failed += 1
                    _progress(index, total, "FAIL", job.video_id, "")
                else:
                    write_transcript(
                        target,
                        title,
                        job.video_id,
                        result.language_code,
                        result.caption_kind,
                        result.text,
                    )
                    written += 1
                    detail = f"{result.caption_kind}, {result.language_code}"
                    _progress(index, total, "OK", job.video_id, detail)

        # Jitter only paces real network traffic; resuming a mostly-complete
        # playlist must not sleep between skips.
        if fetched and total > 1 and index < total:
            time.sleep(random.uniform(1.5, 3.0))

    count = total + expansion_failures
    print(
        f"{count} videos: {written} ok, {skipped} skipped, {failed} failed",
        file=sys.stderr,
    )
    return exit_code(written=written, skipped=skipped, failed=failed)


def exit_code(*, written: int, skipped: int, failed: int) -> int:
    """Map a run's per-video tallies to a process exit code.

    Producing nothing at all -- an empty playlist, or one whose videos were all
    unavailable -- is a failure, so it must not exit 0 just because no
    individual video raised.
    """

    if failed:
        return 1
    if written == 0 and skipped == 0:
        return 1
    return 0


def _configure_logging(quiet: bool, verbose: bool) -> None:
    """Configure diagnostic logging for the requested verbosity."""

    level = (
        logging.CRITICAL + 1
        if quiet
        else logging.DEBUG
        if verbose
        else logging.WARNING
    )
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _existing_transcript(output_dir: Path, video_id: str) -> Path | None:
    """Find a non-empty transcript already written for a video."""

    candidates = list(output_dir.glob(f"*-{video_id}.txt"))
    candidates.append(output_dir / f"{video_id}.txt")
    return next(
        (
            path
            for path in candidates
            if path.is_file() and path.stat().st_size > 0
        ),
        None,
    )


def _title_or_id(video_id: str) -> str:
    """Retrieve a title, falling back to the video ID on metadata errors."""

    try:
        return get_video_title(video_id)
    except PlaylistError as exc:
        LOGGER.warning("%s; using the video ID as its title", exc)
        return video_id


def _fetch_with_backoff(
    video_id: str, languages: list[str], args: argparse.Namespace
) -> TranscriptResult | None:
    """Fetch a transcript, retrying blocked requests twice."""

    for attempt in range(3):
        try:
            return fetch_transcript(
                video_id,
                languages,
                allow_fallback=not args.no_fallback,
                keep_markers=args.keep_markers,
            )
        except (RequestBlocked, IpBlocked) as exc:
            if attempt == 2:
                LOGGER.error(
                    "Video %s remained blocked after two retries: %s",
                    video_id,
                    exc,
                )
                return None
            delay = 60 * (2**attempt)
            LOGGER.warning(
                "Video %s was blocked; retrying in %d seconds",
                video_id,
                delay,
            )
            time.sleep(delay)
        except TranscriptError as exc:
            LOGGER.error("%s", exc)
            return None
        except Exception as exc:
            LOGGER.exception("Unexpected failure for video %s: %s", video_id, exc)
            return None
    return None


def _progress(
    index: int, total: int, status: str, video_id: str, detail: str
) -> None:
    """Write one per-video progress line to stderr."""

    suffix = f"  ({detail})" if detail else ""
    print(
        f"[{index}/{total}] {status:<4} {video_id}{suffix}",
        file=sys.stderr,
    )
