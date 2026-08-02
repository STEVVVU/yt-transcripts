"""Unit tests for the CLI's exit-code contract."""

import pytest

from yt_transcripts.cli import build_parser, exit_code


def test_exit_code_all_written_is_success() -> None:
    """A clean run exits 0."""

    assert exit_code(written=3, skipped=0, failed=0) == 0


def test_exit_code_skips_only_is_success() -> None:
    """A fully resumed run produced its files on an earlier invocation."""

    assert exit_code(written=0, skipped=5, failed=0) == 0


def test_exit_code_nothing_produced_is_failure() -> None:
    """An empty or fully unavailable playlist must not report success."""

    assert exit_code(written=0, skipped=0, failed=0) == 1


def test_exit_code_mixed_success_and_failure_is_failure() -> None:
    """Partial success is still a failure so scripts can notice it."""

    assert exit_code(written=2, skipped=1, failed=1) == 1


def test_exit_code_all_failed_is_failure() -> None:
    """A run where every video failed exits non-zero."""

    assert exit_code(written=0, skipped=0, failed=4) == 1


def test_usage_error_exits_two() -> None:
    """argparse reserves exit code 2 for usage errors."""

    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args([])
    assert excinfo.value.code == 2
