"""验证 prn 的相关行为。"""

from unittest import mock

import pytest

from plum_tools.cli.prn import main
from plum_tools.utils.constants import LOCAL_HOST


@pytest.mark.parametrize("dry_run", [False, True])
def test_main_parses_dry_run(dry_run: bool) -> None:
    """使用真实参数解析器校验预览选项的默认值及传递。"""
    argv = ["prn", "--dry-run"] if dry_run else ["prn"]
    project_conf = {"src": ["/local"], "dest": ["/remote"]}
    with (
        mock.patch("sys.argv", argv),
        mock.patch("plum_tools.cli.prn.get_project_conf", return_value=project_conf),
        mock.patch("plum_tools.cli.prn.sync_files") as mock_sync,
    ):
        main()

    mock_sync.assert_called_once_with(
        [LOCAL_HOST],
        "default",
        "",
        0,
        "",
        [project_conf],
        False,
        False,
        ignore_rsync_path=False,
        ignore_exclude=False,
        exclude=[],
        include=[],
        dry_run=dry_run,
    )


@pytest.mark.parametrize("debug_args", [[], ["--debug"]])
def test_main_dry_run_previews_all_hosts_and_projects(
    capsys: pytest.CaptureFixture[str], debug_args: list[str]
) -> None:
    """从 CLI 入口校验多主机、多项目均只预览，且支持忽略 rsync-path。"""
    argv = ["prn", "--dry-run", "--ignore-rsync-path", "-s", LOCAL_HOST, "dev", "-p", "first", "second", *debug_args]
    projects_conf = [
        {"src": ["/local/a"], "dest": ["/remote/a"], "exclude": [], "delete": 0},
        {"src": ["/local/b"], "dest": ["/remote/b"], "exclude": [".git"], "delete": 1},
    ]
    with (
        mock.patch("sys.argv", argv),
        mock.patch("plum_tools.cli.prn.get_project_conf", side_effect=projects_conf),
        mock.patch(
            "plum_tools._prn.sync.merge_ssh_config",
            return_value={"hostname": "10.0.0.1", "user": "root", "port": 22, "identityfile": "id_rsa"},
        ) as mock_merge,
        mock.patch("plum_tools._prn.sync.os.path.isdir", return_value=False),
        mock.patch("plum_tools._prn.sync.run_cmd") as mock_run_cmd,
        mock.patch("plum_tools._prn.sync.subprocess.call") as mock_subprocess_call,
    ):
        main()

    mock_merge.assert_called_once_with("dev", "default", "", 0, "")
    mock_run_cmd.assert_not_called()
    mock_subprocess_call.assert_not_called()
    ssh_option = (
        '-e \'ssh -p 22 -i id_rsa -o "UserKnownHostsFile=/dev/null" '
        '-o "StrictHostKeyChecking no" -o "ConnectTimeout=10"\''
    )
    assert capsys.readouterr().out.splitlines() == [
        "rsync -rtlv /local/a /remote/a",
        "rsync -rtlv --delete --exclude '.git' /local/b /remote/b",
        f"rsync -rtlv {ssh_option} /local/a root@10.0.0.1:/remote/a",
        f"rsync -rtlv {ssh_option} --delete --exclude '.git' /local/b root@10.0.0.1:/remote/b",
    ]


def test_main_uses_localhost_when_servers_not_provided() -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock(
        servers=None,
        projects=["python"],
        default="default",
        download=True,
        identity_file="",
        user="",
        port=0,
        local=["/local"],
        remote=["/remote"],
        delete=None,
        exclude=[],
        include=[],
        debug=True,
        dry_run=False,
        ignore_rsync_path=True,
        ignore_exclude=False,
        version=False,
        type="default",
    )
    mock_parser.parse_args.return_value = mock_args

    with (
        mock.patch("plum_tools.cli.prn.get_base_parser", return_value=mock_parser),
        mock.patch(
            "plum_tools.cli.prn.get_project_conf", return_value={"src": ["/local"], "dest": ["/remote"]}
        ) as mock_project,
        mock.patch("plum_tools.cli.prn.sync_files") as mock_sync,
    ):
        main()

    mock_project.assert_called_once_with("python", ["/local"], ["/remote"], None, [], True)
    mock_sync.assert_called_once_with(
        [LOCAL_HOST],
        "default",
        "",
        0,
        "",
        [{"src": ["/local"], "dest": ["/remote"]}],
        True,
        True,
        ignore_rsync_path=True,
        ignore_exclude=False,
        exclude=[],
        include=[],
        dry_run=False,
    )


def test_main_rejects_multiple_local_and_remote_paths() -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock(
        servers=["dev"],
        projects=["python"],
        default="default",
        download=False,
        identity_file="",
        user="",
        port=0,
        local=["/local1", "/local2"],
        remote=["/remote1", "/remote2"],
        delete=None,
        exclude=[],
        debug=False,
        dry_run=False,
        ignore_rsync_path=False,
        version=False,
        type="default",
    )
    mock_parser.parse_args.return_value = mock_args

    with (
        mock.patch("plum_tools.cli.prn.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.cli.prn.print_error") as mock_print_error,
        mock.patch("plum_tools.cli.prn.get_project_conf") as mock_project,
        mock.patch("plum_tools.cli.prn.sync_files") as mock_sync,
    ):
        main()

    mock_print_error.assert_called_once_with("本地路径和目标路径不能同时传入多个值")
    mock_project.assert_not_called()
    mock_sync.assert_not_called()


def test_main() -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock(
        servers=["test", "dev"],
        projects=["test", "python"],
        default="default",
        download=False,
        identity_file="",
        user="",
        port=0,
        local="",
        remote="",
        delete=None,
        exclude=[],
        include=[],
        debug=False,
        dry_run=False,
        ignore_rsync_path=False,
        ignore_exclude=False,
        version=False,
    )
    mock_project_conf = mock.Mock()
    mock_parser.parse_args.return_value = mock_args
    with (
        mock.patch("plum_tools.cli.prn.get_base_parser", return_value=mock_parser) as mock_argparse,
        mock.patch("plum_tools.cli.prn.get_project_conf", return_value=mock_project_conf) as mock_project,
        mock.patch("plum_tools.cli.prn.sync_files") as mock_sync,
    ):
        main()
        mock_argparse.assert_called_once_with()
        mock_parser.add_argument.assert_has_calls(
            [
                mock.call(
                    "-s",
                    "--servers",
                    required=False,
                    action="store",
                    dest="servers",
                    nargs="+",
                    help="服务器 IP、IP 简写或 SSH 主机别名，可指定多个；默认在本机同步",
                ),
                mock.call(
                    "-p",
                    "--projects",
                    required=False,
                    action="store",
                    dest="projects",
                    nargs="+",
                    default=["default"],
                    help="配置中的项目名，可指定多个；默认 default，可选值由 projects 配置决定",
                ),
                mock.call(
                    "-t",
                    "--type",
                    action="store",
                    required=False,
                    dest="type",
                    default="default",
                    help="主机类型，默认 default；可选值由配置中的 host_type_<类型> 决定",
                ),
                mock.call(
                    "--download",
                    action="store_true",
                    required=False,
                    dest="download",
                    default=False,
                    help="从远端下载文件到本地，默认上传",
                ),
                mock.call(
                    "-i",
                    "--identityfile",
                    action="store",
                    required=False,
                    dest="identity_file",
                    default="",
                    help="SSH 私钥路径，默认读取 SSH 配置",
                ),
                mock.call(
                    "-u",
                    "--username",
                    action="store",
                    required=False,
                    dest="user",
                    default="",
                    help="SSH 登录用户名，默认读取 SSH 配置",
                ),
                mock.call(
                    "--port",
                    action="store",
                    required=False,
                    dest="port",
                    type=int,
                    default=0,
                    help="SSH 登录端口，默认读取 SSH 配置",
                ),
                mock.call(
                    "-l",
                    "--local",
                    action="store",
                    required=False,
                    dest="local",
                    nargs="+",
                    default="",
                    help="本地路径，可指定多个；默认读取项目的 src 配置",
                ),
                mock.call(
                    "-r",
                    "--remote",
                    action="store",
                    required=False,
                    dest="remote",
                    nargs="+",
                    default="",
                    help="远端路径，可指定多个；默认读取项目的 dest 配置",
                ),
                mock.call(
                    "-d",
                    "--delete",
                    action="store",
                    required=False,
                    dest="delete",
                    type=int,
                    default=None,
                    help="是否删除目标端多余文件：0 保留，1 删除；默认读取项目 delete 配置，未配置时为 0",
                ),
                mock.call(
                    "-e",
                    "--exclude",
                    action="store",
                    nargs="+",
                    required=False,
                    dest="exclude",
                    default=[],
                    help="追加排除的文件或目录，可指定多个；默认使用项目及全局排除配置",
                ),
                mock.call(
                    "--include",
                    action="store",
                    nargs="+",
                    required=False,
                    dest="include",
                    default=[],
                    help="取消指定文件或目录的排除，可指定多个；默认无覆盖项",
                ),
                mock.call(
                    "--debug",
                    action="store_true",
                    required=False,
                    dest="debug",
                    default=False,
                    help="显示完整 rsync 调试输出，默认关闭",
                ),
                mock.call(
                    "--dry-run",
                    action="store_true",
                    required=False,
                    dest="dry_run",
                    default=False,
                    help="仅打印将要执行的命令，默认关闭",
                ),
                mock.call(
                    "--ignore-rsync-path",
                    action="store_true",
                    required=False,
                    dest="ignore_rsync_path",
                    default=False,
                    help="不使用 --rsync-path 选项，默认使用该选项",
                ),
                mock.call(
                    "--ignore-exclude",
                    action="store_true",
                    required=False,
                    dest="ignore_exclude",
                    default=False,
                    help="忽略全部排除规则，默认应用排除规则",
                ),
            ]
        )
        mock_parser.parse_args.assert_called_once_with()
        assert mock_parser.add_argument.call_count == 16
        mock_project.assert_has_calls([mock.call(project, "", "", None, [], False) for project in ["test", "python"]])
        assert mock_project.call_count == 2
        mock_sync.assert_called_once_with(
            ["test", "dev"],
            mock_args.type,
            "",
            0,
            "",
            [mock_project_conf, mock_project_conf],
            False,
            False,
            ignore_rsync_path=False,
            ignore_exclude=False,
            exclude=[],
            include=[],
            dry_run=False,
        )


def test_main_with_ignore_rsync_path() -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock(
        servers=["test"],
        projects=["python"],
        default="default",
        download=False,
        identity_file="",
        user="",
        port=0,
        local="",
        remote="",
        delete=None,
        exclude=[],
        include=[],
        debug=False,
        dry_run=False,
        ignore_rsync_path=True,
        ignore_exclude=False,
        version=False,
        type="default",
    )
    mock_parser.parse_args.return_value = mock_args

    with (
        mock.patch("plum_tools.cli.prn.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.cli.prn.get_project_conf", return_value={}) as mock_project,
        mock.patch("plum_tools.cli.prn.sync_files") as mock_sync,
    ):
        main()

    mock_project.assert_called_once_with("python", "", "", None, [], False)
    mock_sync.assert_called_once_with(
        ["test"],
        "default",
        "",
        0,
        "",
        [{}],
        False,
        False,
        ignore_rsync_path=True,
        ignore_exclude=False,
        exclude=[],
        include=[],
        dry_run=False,
    )


def test_main_directory_target_skips_abspath() -> None:
    argv = ["prn", "-s", "/srv/app", "--dry-run"]
    project_conf = {"src": ["/tmp/src"], "dest": ["/srv/app/go"]}
    with (
        mock.patch("sys.argv", argv),
        mock.patch("plum_tools.cli.prn.get_project_conf", return_value=project_conf) as mock_project,
        mock.patch("plum_tools.cli.prn.sync_files") as mock_sync,
    ):
        main()

    call = mock_project.call_args
    assert call.args == ("default", "", "", None, [], False)
    assert call.kwargs == {"resolve_src": False}
    mock_sync.assert_called_once_with(
        ["/srv/app"],
        "default",
        "",
        0,
        "",
        [project_conf],
        False,
        False,
        ignore_rsync_path=False,
        ignore_exclude=False,
        exclude=[],
        include=[],
        dry_run=True,
    )
