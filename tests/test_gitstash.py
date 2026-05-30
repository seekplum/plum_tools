"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_gitstash
#         Desc: 测试gitstash模块
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 23:43
#=============================================================================
"""

from unittest import mock

import pytest

from plum_tools.conf import STASH_UUID, GitCommand
from plum_tools.exceptions import RunCmdError
from plum_tools.gitstash import GitCheckoutStash, main


def test_main() -> None:
    mock_parser = mock.Mock()
    mock_stash_instance = mock.Mock()
    mock_args = mock.Mock(branch="test")
    mock_parser.parse_args.return_value = mock_args
    with (
        mock.patch("plum_tools.gitstash.get_base_parser", return_value=mock_parser) as mock_argparse,
        mock.patch("plum_tools.gitstash.get_current_branch_name", return_value="master") as mock_current_branch,
        mock.patch("plum_tools.gitstash.GitCheckoutStash", return_value=mock_stash_instance) as mock_git_stash,
    ):
        main()
        mock_argparse.assert_called_once_with()
        mock_parser.add_argument.assert_called_once_with(dest="branch", action="store", help="specify branch")
        mock_parser.parse_args.assert_called_once_with()
        mock_current_branch.assert_called_once_with()
        mock_git_stash.assert_called_once_with("master", "test")
        mock_stash_instance.checkout.assert_called_once_with()


def test_git_checkout_stash_skips_checkout_when_branch_matches() -> None:
    stash = GitCheckoutStash("master", "master")

    with (
        mock.patch.object(stash, "_stash") as mock_stash,
        mock.patch.object(stash, "_checkout") as mock_checkout,
        mock.patch.object(stash, "_apply") as mock_apply,
    ):
        stash.checkout()

    mock_stash.assert_not_called()
    mock_checkout.assert_not_called()
    mock_apply.assert_not_called()


def test_git_checkout_stash_stashes_when_repository_has_changes() -> None:
    stash = GitCheckoutStash("master", "feature")
    expected_cmd = GitCommand.STASH_SAVE % f"master-{STASH_UUID}"

    with (
        mock.patch("plum_tools.gitstash.check_repository_modify_status", return_value=(True, "M test")) as mock_status,
        mock.patch("plum_tools.gitstash.run_cmd") as mock_run_cmd,
    ):
        stash._stash()

    mock_status.assert_called_once_with(stash._current_path)
    mock_run_cmd.assert_called_once_with(expected_cmd)


def test_git_checkout_stash_does_not_stash_clean_repository() -> None:
    stash = GitCheckoutStash("master", "feature")

    with (
        mock.patch("plum_tools.gitstash.check_repository_modify_status", return_value=(False, "")) as mock_status,
        mock.patch("plum_tools.gitstash.run_cmd") as mock_run_cmd,
    ):
        stash._stash()

    mock_status.assert_called_once_with(stash._current_path)
    mock_run_cmd.assert_not_called()


def test_git_checkout_stash_applies_matching_stash_entry() -> None:
    stash = GitCheckoutStash("master", "feature")
    stash_out = "stash@{0}: On feature-plum123456789987654321plum\nstash@{1}: On master-other\n"

    with (
        mock.patch("plum_tools.gitstash.check_repository_stash", return_value=(True, stash_out)) as mock_check_stash,
        mock.patch("plum_tools.gitstash.run_cmd") as mock_run_cmd,
    ):
        stash._apply()

    mock_check_stash.assert_called_once_with(stash._current_path)
    mock_run_cmd.assert_called_once_with(GitCommand.STASH_POP % "stash@{0}")


def test_git_checkout_stash_applies_only_latest_matching_stash_entry() -> None:
    stash = GitCheckoutStash("master", "feature")
    stash_out = "\n".join(
        [
            "stash@{0}: On feature-plum123456789987654321plum",
            "stash@{1}: On feature-plum123456789987654321plum",
        ]
    )

    with (
        mock.patch("plum_tools.gitstash.check_repository_stash", return_value=(True, stash_out)) as mock_check_stash,
        mock.patch("plum_tools.gitstash.run_cmd") as mock_run_cmd,
    ):
        stash._apply()

    mock_check_stash.assert_called_once_with(stash._current_path)
    mock_run_cmd.assert_called_once_with(GitCommand.STASH_POP % "stash@{0}")


def test_git_checkout_stash_ignores_missing_stash_entries() -> None:
    stash = GitCheckoutStash("master", "feature")

    with (
        mock.patch("plum_tools.gitstash.check_repository_stash", return_value=(False, "")) as mock_check_stash,
        mock.patch("plum_tools.gitstash.run_cmd") as mock_run_cmd,
    ):
        stash._apply()

    mock_check_stash.assert_called_once_with(stash._current_path)
    mock_run_cmd.assert_not_called()


def test_git_checkout_stash_checkout_runs_git_checkout() -> None:
    stash = GitCheckoutStash("master", "feature")

    with mock.patch("plum_tools.gitstash.run_cmd") as mock_run_cmd:
        stash._checkout()

    mock_run_cmd.assert_called_once_with(GitCommand.GIT_CHECKOUT % "feature")


def test_git_checkout_stash_runs_full_flow_when_switching_branch() -> None:
    stash = GitCheckoutStash("master", "feature")

    with (
        mock.patch.object(stash, "_stash") as mock_stash,
        mock.patch.object(stash, "_checkout") as mock_checkout,
        mock.patch.object(stash, "_apply") as mock_apply,
    ):
        stash.checkout()

    mock_stash.assert_called_once_with()
    mock_checkout.assert_called_once_with()
    mock_apply.assert_called_once_with()


def test_main_exits_when_not_in_git_repository() -> None:
    mock_parser = mock.Mock()
    mock_parser.parse_args.return_value = mock.Mock(branch="test")

    with (
        mock.patch("plum_tools.gitstash.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.gitstash.get_current_branch_name", side_effect=RunCmdError("fail", "", "")),
        mock.patch("plum_tools.gitstash.print_warn") as mock_print_warn,
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    mock_print_warn.assert_called_once_with("当前目录不是一个git仓库")
