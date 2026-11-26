"""验证 pclean 的相关行为。"""

from __future__ import annotations

from unittest import mock

import pytest

from plum_tools._cleanup.constants import (
    PROJECT_CATEGORIES,
    Command,
)
from plum_tools.cli.pclean import main

# ---------- pclean.py: main ----------


def test_main_unsupported_platform(capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch("plum_tools.cli.pclean.sys.platform", "win32"):
        code = main()
    assert code == 2
    assert "macOS/Linux" in capsys.readouterr().err


def test_main_trash_import_error(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SCAN
    args.categories = set()
    with (
        mock.patch("plum_tools.cli.pclean.sys.platform", "darwin"),
        mock.patch("plum_tools.cli.pclean.parse_args", return_value=args),
        mock.patch("plum_tools.cli.pclean.Trash", side_effect=ImportError("boom")),
    ):
        code = main()
    assert code == 2
    assert "trash-cli" in capsys.readouterr().err


def test_main_missing_git(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SCAN
    args.categories = PROJECT_CATEGORIES
    with (
        mock.patch("plum_tools.cli.pclean.sys.platform", "darwin"),
        mock.patch("plum_tools.cli.pclean.parse_args", return_value=args),
        mock.patch("plum_tools.cli.pclean.Trash"),
        mock.patch("plum_tools.cli.pclean.shutil.which", return_value=None),
    ):
        code = main()
    assert code == 2
    assert "Git" in capsys.readouterr().err


def test_main_run_oserror_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SCAN
    args.categories = set()
    with (
        mock.patch("plum_tools.cli.pclean.sys.platform", "darwin"),
        mock.patch("plum_tools.cli.pclean.parse_args", return_value=args),
        mock.patch("plum_tools.cli.pclean.Trash"),
        mock.patch("plum_tools.cli.pclean.run", side_effect=OSError("boom")),
    ):
        code = main()
    assert code == 1
    assert "已停止" in capsys.readouterr().err


def test_main_run_eoferror_returns_130(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SCAN
    args.categories = set()
    with (
        mock.patch("plum_tools.cli.pclean.sys.platform", "darwin"),
        mock.patch("plum_tools.cli.pclean.parse_args", return_value=args),
        mock.patch("plum_tools.cli.pclean.Trash"),
        mock.patch("plum_tools.cli.pclean.run", side_effect=EOFError()),
    ):
        code = main()
    assert code == 130
    assert "已取消" in capsys.readouterr().err


def test_main_prune_skips_trash() -> None:
    args = mock.MagicMock()
    args.command = Command.PRUNE
    args.categories = set()
    with (
        mock.patch("plum_tools.cli.pclean.sys.platform", "darwin"),
        mock.patch("plum_tools.cli.pclean.parse_args", return_value=args),
        mock.patch("plum_tools.cli.pclean.Trash") as mock_trash,
        mock.patch("plum_tools.cli.pclean.run", return_value=0) as mock_run,
    ):
        code = main()
    assert code == 0
    mock_trash.assert_not_called()
    mock_run.assert_called_once()
