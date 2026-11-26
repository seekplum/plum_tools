"""验证 sync 的相关行为。"""

from typing import cast
from unittest import mock

import pytest

from plum_tools._prn.sync import SyncFiles, sync_files
from plum_tools.utils.constants import LOCAL_HOST
from plum_tools.utils.exceptions import RunCmdError


def test_sync_files_builds_localhost_and_remote_syncs() -> None:
    projects_conf = [
        {"src": "/tmp/a", "dest": "/remote/a", "exclude": [], "delete": 0},
        {"src": "/tmp/b", "dest": "/remote/b", "exclude": [".git"], "delete": 1},
    ]
    sync_instances = [mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock()]

    with (
        mock.patch(
            "plum_tools._prn.sync.merge_ssh_config",
            return_value={"hostname": "10.0.0.1", "user": "root", "port": 22, "identityfile": "id_rsa"},
        ) as mock_merge,
        mock.patch("plum_tools._prn.sync.SyncFiles", side_effect=sync_instances) as mock_sync_files,
    ):
        sync_files([LOCAL_HOST, "dev"], "default", "root", 22, "id_rsa", projects_conf, True, True, True)

    mock_merge.assert_called_once_with("dev", "default", "root", 22, "id_rsa")
    assert projects_conf == [
        {"src": "/tmp/a", "dest": "/remote/a", "exclude": [], "delete": 0},
        {"src": "/tmp/b", "dest": "/remote/b", "exclude": [".git"], "delete": 1},
    ]
    assert mock_sync_files.call_count == 4
    sync_instances[0].translate.assert_called_once_with()
    sync_instances[1].translate.assert_called_once_with()
    sync_instances[2].translate.assert_called_once_with()
    sync_instances[3].translate.assert_called_once_with()


def test_translate_download_debug_and_localhost_paths(capsys: pytest.CaptureFixture[str]) -> None:
    sync = SyncFiles(
        LOCAL_HOST,
        "",
        0,
        "",
        "/local/file",
        cast(str, ["/remote/a/", "/remote/b"]),
        [".git"],
        1,
        True,
        True,
    )

    with mock.patch("plum_tools._prn.sync.subprocess.call", return_value=0) as mock_subprocess_call:
        sync.translate()

    mock_subprocess_call.assert_called_once_with(
        "rsync -rtlv --delete --exclude '.git' /remote/a/ /remote/b /local/file",
        shell=True,  # nosec: B604
    )
    captured = capsys.readouterr()
    assert "从 本地机器 下载 /remote/a/ /remote/b 到本地 /local/file 成功" in captured.out


def test_translate_reports_run_cmd_error(capsys: pytest.CaptureFixture[str]) -> None:
    sync = SyncFiles("1.1.1.1", "user", 22, "", "/tmp/src", "/tmp/dest", [], 0)

    with mock.patch("plum_tools._prn.sync.run_cmd", side_effect=RunCmdError("fail", "", "boom")):
        sync.translate()

    captured = capsys.readouterr()
    assert "上传 /tmp/src 到 user@1.1.1.1 服务器(端口: 22) /tmp/dest 失败, 失败原因: boom" in captured.out


@pytest.mark.parametrize("is_debug", [False, True])
@pytest.mark.parametrize("is_download", [False, True])
@pytest.mark.parametrize("hostname", [LOCAL_HOST, "1.1.1.1"])
def test_translate_dry_run_prints_command_without_syncing(
    capsys: pytest.CaptureFixture[str], hostname: str, is_download: bool, is_debug: bool
) -> None:
    """预览上传、下载及本地同步命令，并确保 debug 模式不会触发执行。"""
    sync = SyncFiles(
        hostname,
        "user",
        22,
        "id_rsa",
        "/local/project",
        "/remote/project",
        [".git", "node_modules"],
        1,
        is_download=is_download,
        is_debug=is_debug,
        include=["node_modules"],
        dry_run=True,
    )

    with (
        mock.patch("plum_tools._prn.sync.os.path.isdir", return_value=True),
        mock.patch("plum_tools._prn.sync.run_cmd") as mock_run_cmd,
        mock.patch("plum_tools._prn.sync.subprocess.call") as mock_subprocess_call,
    ):
        sync.translate()

    mock_run_cmd.assert_not_called()
    mock_subprocess_call.assert_not_called()
    directory = "/local" if is_download else "/remote"
    ssh_option = ""
    user_prefix = ""
    if hostname != LOCAL_HOST:
        ssh_option = (
            ' -e \'ssh -p 22 -i id_rsa -o "UserKnownHostsFile=/dev/null" '
            '-o "StrictHostKeyChecking no" -o "ConnectTimeout=10"\''
        )
        user_prefix = "user@1.1.1.1:"
    paths = (
        f"{user_prefix}/remote/project /local/project"
        if is_download
        else f"/local/project/ {user_prefix}/remote/project"
    )
    rsync_path = "" if is_download or hostname == LOCAL_HOST else f" '--rsync-path=mkdir -p {directory} && rsync'"
    assert capsys.readouterr().out == (f"rsync -rtlv{rsync_path}{ssh_option} --delete --exclude '.git' {paths}\n")


def test_translate(capsys: pytest.CaptureFixture) -> None:
    hostname, user, port, identityfile, src, dest, delete = (
        "1.1.1.1",
        "user",
        22,
        "",
        "/tmp",
        "/tmp",
        0,
    )
    exclude: list[str] = []
    u = SyncFiles(hostname, user, port, identityfile, src, dest, exclude, delete)
    with mock.patch("plum_tools._prn.sync.run_cmd") as m:
        u.translate()
        m.assert_called_once_with(
            "rsync -rtlv '--rsync-path=mkdir -p / && rsync' -e "
            '\'ssh -p 22 -i  -o "UserKnownHostsFile=/dev/null" '
            '-o "StrictHostKeyChecking no" -o "ConnectTimeout=10"\' /tmp/ user@1.1.1.1:/tmp'
        )
        captured = capsys.readouterr()
        output = captured.out
        assert output == "[32m上传 /tmp/ 到 user@1.1.1.1 服务器(端口: 22) /tmp 成功[0m\n"


def test_translate_ignore_rsync_path(capsys: pytest.CaptureFixture) -> None:
    u = SyncFiles(
        "1.1.1.1",
        "user",
        22,
        "",
        "/tmp",
        "/tmp",
        [],
        0,
        ignore_rsync_path=True,
    )

    with mock.patch("plum_tools._prn.sync.run_cmd") as m:
        u.translate()
        m.assert_called_once_with(
            'rsync -rtlv -e \'ssh -p 22 -i  -o "UserKnownHostsFile=/dev/null" '
            '-o "StrictHostKeyChecking no" -o "ConnectTimeout=10"\' /tmp/ user@1.1.1.1:/tmp'
        )

    captured = capsys.readouterr()
    assert captured.out == "[32m上传 /tmp/ 到 user@1.1.1.1 服务器(端口: 22) /tmp 成功[0m\n"


def test_get_sync_option_uses_dest_when_no_directory() -> None:
    """验证当 dest 没有目录部分时使用 dest 作为目录。"""
    sync = SyncFiles(
        hostname="10.0.0.1",
        user="root",
        port=0,
        identityfile="",
        src="/tmp/src",
        dest="file.txt",  # 没有目录部分
        exclude=[],
        delete=0,
        ignore_rsync_path=False,
    )

    option = sync._get_sync_option()  # pylint: disable=protected-access

    # 应使用 dest 作为目录
    assert "--rsync-path=mkdir -p file.txt" in option


def test_translate_debug_mode_with_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """验证调试模式下命令执行失败时打印错误信息。"""
    from plum_tools._prn.sync import SyncFiles

    sync = SyncFiles(
        hostname="10.0.0.1",
        user="root",
        port=0,
        identityfile="",
        src="/tmp/src",
        dest="/tmp/dest",
        exclude=[],
        delete=0,
        is_debug=True,
    )

    with (
        mock.patch("plum_tools._prn.sync.process_paths", side_effect=lambda path, **kwargs: path),
        mock.patch("plum_tools._prn.sync.process_remote_paths", side_effect=lambda path, prefix: path),
        mock.patch("plum_tools._prn.sync.call_process", return_value=1),
        mock.patch("plum_tools._prn.sync.print_text"),
        mock.patch("plum_tools._prn.sync.print_error") as mock_print_error,
        mock.patch("plum_tools._prn.sync.print_ok"),
    ):
        sync.translate()

        # 应打印错误信息
        mock_print_error.assert_called_once()
        call_args = mock_print_error.call_args[0][0]
        assert "失败" in call_args
        assert "错误码: 1" in call_args


def test_get_sync_option_skips_rsync_path_in_download_mode() -> None:
    """下载模式下 _get_sync_option 不应生成 --rsync-path，且使用 10 秒连接超时。"""
    sync = SyncFiles(
        hostname="10.0.0.1",
        user="root",
        port=22,
        identityfile="id_rsa",
        src="/local/dest",
        dest="/remote/src",
        exclude=[],
        delete=0,
        is_download=True,
    )

    option = sync._get_sync_option()  # pylint: disable=protected-access

    assert "--rsync-path" not in option
    assert "ConnectTimeout=10" in option


def test_translate_download_skips_rsync_path(capsys: pytest.CaptureFixture[str]) -> None:
    """下载模式的命令不应包含 --rsync-path，避免远端执行本地路径的 mkdir。"""
    sync = SyncFiles(
        hostname="1.1.1.1",
        user="user",
        port=22,
        identityfile="id_rsa",
        src="/local/dest",
        dest="/remote/src/",
        exclude=[],
        delete=0,
        is_download=True,
        dry_run=True,
    )

    sync.translate()

    command = capsys.readouterr().out
    assert "--rsync-path" not in command
    assert "ConnectTimeout=10" in command


def test_get_sync_option_ignore_exclude_keeps_cli_exclude() -> None:
    """--ignore-exclude 时仅保留命令行传入的 exclude，忽略配置中的排除项。"""
    sync = SyncFiles(
        hostname="10.0.0.1",
        user="root",
        port=22,
        identityfile="id_rsa",
        src="/local/src",
        dest="/remote/dest",
        exclude=[".git", "node_modules", "*.log"],
        delete=0,
        ignore_exclude=True,
        cli_exclude=["node_modules"],
    )

    option = sync._get_sync_option()  # pylint: disable=protected-access

    assert "--exclude 'node_modules'" in option
    assert ".git" not in option
    assert "*.log" not in option


def test_get_sync_option_ignore_exclude_without_cli_exclude() -> None:
    """--ignore-exclude 且无命令行 exclude 时，不生成任何 --exclude。"""
    sync = SyncFiles(
        hostname="10.0.0.1",
        user="root",
        port=22,
        identityfile="id_rsa",
        src="/local/src",
        dest="/remote/dest",
        exclude=[".git"],
        delete=0,
        ignore_exclude=True,
        cli_exclude=[],
    )

    option = sync._get_sync_option()  # pylint: disable=protected-access

    assert "--exclude" not in option


def test_translate_directory_upload(capsys: pytest.CaptureFixture[str]) -> None:
    sync = SyncFiles(LOCAL_HOST, "", 0, "", "/tmp/src", "/srv/app/go", [], 0, directory_root="/srv/app")

    with (
        mock.patch("plum_tools._prn.sync.os.path.lexists", return_value=True),
        mock.patch("plum_tools._prn.sync.os.path.isdir", return_value=False),
        mock.patch("plum_tools._prn.sync.os.makedirs") as mock_makedirs,
        mock.patch("plum_tools._prn.sync.run_cmd") as mock_run_cmd,
    ):
        sync.translate()

    mock_run_cmd.assert_called_once_with("rsync -rtlv /tmp/src /srv/app/srv/app/go")
    mock_makedirs.assert_called_once_with("/srv/app/srv/app", exist_ok=True)
    assert "同步 /tmp/src 到 /srv/app/srv/app/go 成功" in capsys.readouterr().out


def test_translate_directory_download(capsys: pytest.CaptureFixture[str]) -> None:
    sync = SyncFiles(
        LOCAL_HOST, "", 0, "", "/tmp/src", "/srv/app/go", [], 0, is_download=True, directory_root="/srv/app"
    )

    with (
        mock.patch("plum_tools._prn.sync.os.path.lexists", return_value=True),
        mock.patch("plum_tools._prn.sync.os.path.isdir", return_value=False),
        mock.patch("plum_tools._prn.sync.os.makedirs") as mock_makedirs,
        mock.patch("plum_tools._prn.sync.run_cmd") as mock_run_cmd,
    ):
        sync.translate()

    mock_run_cmd.assert_called_once_with("rsync -rtlv /srv/app/srv/app/go /tmp/src")
    mock_makedirs.assert_called_once_with("/tmp", exist_ok=True)
    assert "同步 /srv/app/srv/app/go 到 /tmp/src 成功" in capsys.readouterr().out


def test_translate_directory_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    sync = SyncFiles(LOCAL_HOST, "", 0, "", "/tmp/src", "/srv/app/go", [], 0, dry_run=True, directory_root="/srv/app")

    with (
        mock.patch("plum_tools._prn.sync.os.path.lexists", return_value=True),
        mock.patch("plum_tools._prn.sync.os.path.isdir", return_value=False),
        mock.patch("plum_tools._prn.sync.os.makedirs") as mock_makedirs,
        mock.patch("plum_tools._prn.sync.run_cmd") as mock_run_cmd,
    ):
        sync.translate()

    mock_run_cmd.assert_not_called()
    mock_makedirs.assert_not_called()
    assert capsys.readouterr().out == "rsync -rtlv /tmp/src /srv/app/srv/app/go\n"


def test_translate_directory_multiple_dest_exits() -> None:
    sync = SyncFiles(
        LOCAL_HOST, "", 0, "", "/tmp/src", cast(str, ["/srv/app/go1", "/srv/app/go2"]), [], 0, directory_root="/srv/app"
    )

    # fmt: off
    with (
        mock.patch("plum_tools._prn.sync.print_error") as mock_print_error,
    ):
        # fmt: on
        with pytest.raises(SystemExit) as exc_info:
            sync.translate()

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with("目录模式只能指定一个目标路径")


def test_translate_directory_skips_missing_source(capsys: pytest.CaptureFixture[str]) -> None:
    sync = SyncFiles(
        LOCAL_HOST, "", 0, "", cast(str, ["/tmp/missing", "/tmp/src"]), "/srv/app/go", [], 0, directory_root="/srv/app"
    )

    def lexists(path: str) -> bool:
        return path == "/tmp/src"

    with (
        mock.patch("plum_tools._prn.sync.os.path.lexists", side_effect=lexists),
        mock.patch("plum_tools._prn.sync.os.path.isdir", return_value=False),
        mock.patch("plum_tools._prn.sync.os.makedirs") as mock_makedirs,
        mock.patch("plum_tools._prn.sync.run_cmd") as mock_run_cmd,
        mock.patch("plum_tools._prn.sync.print_warn") as mock_print_warn,
    ):
        sync.translate()

    mock_run_cmd.assert_called_once_with("rsync -rtlv /tmp/src /srv/app/srv/app/go")
    mock_print_warn.assert_called_once_with("源文件或目录不存在：/tmp/missing，跳过")
    mock_makedirs.assert_called_once_with("/srv/app/srv/app", exist_ok=True)


def test_translate_directory_exits_on_out_of_root() -> None:
    sync = SyncFiles(LOCAL_HOST, "", 0, "", "/tmp/src", "/../../etc", [], 0, directory_root="/srv/app")

    # fmt: off
    with (
        mock.patch("plum_tools._prn.sync.print_error") as mock_print_error,
    ):
        # fmt: on
        with pytest.raises(SystemExit) as exc_info:
            sync.translate()

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with("配置路径超出目录根路径：/../../etc")


def test_sync_files_directory_root_uses_local() -> None:
    projects_conf = [{"src": "/tmp/src", "dest": "/srv/app/go", "exclude": [], "delete": 0}]
    sync_instances = [mock.Mock()]

    with (
        mock.patch("plum_tools._prn.sync.merge_ssh_config") as mock_merge,
        mock.patch("plum_tools._prn.sync.SyncFiles", side_effect=sync_instances) as mock_sync_files,
    ):
        sync_files(["/srv/app"], "default", "root", 22, "id_rsa", projects_conf)

    mock_merge.assert_not_called()
    sync_instances[0].translate.assert_called_once_with()
    kwargs = mock_sync_files.call_args.kwargs
    assert kwargs["directory_root"] == "/srv/app"
    assert kwargs["hostname"] == LOCAL_HOST
