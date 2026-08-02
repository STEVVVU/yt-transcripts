"""Unit tests for transcript source selection.

These tests are offline: they exercise the pure helpers that choose which
caption track to request and which downloaded file to read.
"""

from pathlib import Path

from yt_transcripts.transcript import (
    _find_subtitle_file,
    _select_original_langs,
    _subtitle_pattern,
)


VIDEO_ID = "dQw4w9WgXcQ"
LANGUAGES = ["en", "en-US", "en-GB"]


def test_find_subtitle_file_honors_language_preference(tmp_path: Path) -> None:
    """``en`` wins over ``en-GB`` and ``en-orig`` despite sorting after them."""

    for name in (
        f"{VIDEO_ID}.en-GB.json3",
        f"{VIDEO_ID}.en-orig.json3",
        f"{VIDEO_ID}.en.json3",
    ):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    found = _find_subtitle_file(tmp_path, VIDEO_ID, LANGUAGES)
    assert found == tmp_path / f"{VIDEO_ID}.en.json3"


def test_find_subtitle_file_falls_back_to_second_preference(
    tmp_path: Path,
) -> None:
    """With ``en`` absent, the next requested tag is used, not the sort order."""

    for name in (f"{VIDEO_ID}.en-GB.json3", f"{VIDEO_ID}.en-US.json3"):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    found = _find_subtitle_file(tmp_path, VIDEO_ID, LANGUAGES)
    assert found == tmp_path / f"{VIDEO_ID}.en-US.json3"


def test_find_subtitle_file_accepts_unrequested_tag_as_last_resort(
    tmp_path: Path,
) -> None:
    """A downloaded file under an unlisted tag is still better than nothing."""

    (tmp_path / f"{VIDEO_ID}.en-orig.json3").write_text("{}", encoding="utf-8")

    found = _find_subtitle_file(tmp_path, VIDEO_ID, LANGUAGES)
    assert found == tmp_path / f"{VIDEO_ID}.en-orig.json3"


def test_find_subtitle_file_prefers_json3_over_vtt(tmp_path: Path) -> None:
    """JSON3 is structured, so it beats a VTT of a more preferred language."""

    (tmp_path / f"{VIDEO_ID}.en-GB.json3").write_text("{}", encoding="utf-8")
    (tmp_path / f"{VIDEO_ID}.en.vtt").write_text("WEBVTT\n", encoding="utf-8")

    found = _find_subtitle_file(tmp_path, VIDEO_ID, LANGUAGES)
    assert found == tmp_path / f"{VIDEO_ID}.en-GB.json3"


def test_find_subtitle_file_returns_none_when_empty(tmp_path: Path) -> None:
    """An empty download directory yields no candidate."""

    assert _find_subtitle_file(tmp_path, VIDEO_ID, LANGUAGES) is None


def test_select_original_langs_skips_translated_track() -> None:
    """A Spanish video's translated ``en`` auto-caption is never requested."""

    info = {
        "language": "es",
        "subtitles": {},
        "automatic_captions": {"es": {}, "es-orig": {}, "en": {}, "fr": {}},
    }
    assert _select_original_langs(info, LANGUAGES) == []


def test_select_original_langs_prefers_orig_variant() -> None:
    """The explicit ``-orig`` key identifies the original auto-caption track."""

    info = {
        "language": "en",
        "subtitles": {},
        "automatic_captions": {"en": {}, "en-orig": {}, "de": {}},
    }
    assert _select_original_langs(info, LANGUAGES) == ["en-orig"]


def test_select_original_langs_prefers_manual_captions() -> None:
    """Manual captions are authored, so they are requested ahead of ASR."""

    info = {
        "language": "en",
        "subtitles": {"en": {}},
        "automatic_captions": {"en": {}, "en-orig": {}},
    }
    assert _select_original_langs(info, LANGUAGES) == ["en"]


def test_select_original_langs_accepts_manual_regional_variant() -> None:
    """A manual en-GB track satisfies a request for ``en``."""

    info = {
        "language": "en",
        "subtitles": {"en-GB": {}},
        "automatic_captions": {},
    }
    assert _select_original_langs(info, ["en"]) == ["en-GB"]


def test_select_original_langs_ignores_non_dict_info() -> None:
    """A missing or malformed info dict selects nothing rather than raising."""

    assert _select_original_langs(None, LANGUAGES) == []


def test_subtitle_pattern_does_not_widen_to_a_wildcard() -> None:
    """A wildcard would re-match machine-translated tracks (yt-dlp #13831)."""

    assert _subtitle_pattern("en") == "en"
    assert _subtitle_pattern("en-GB") == r"en\-GB"
