"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_prn
#         Desc: 测试prn模块
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 16:24
#=============================================================================
"""

from typing import cast
from unittest import mock

import pytest

from plum_tools.conf import LOCAL_HOST, PathConfig
from plum_tools.exceptions import RunCmdError, SystemTypeError
from plum_tools.prn import (
    SyncFiles,
    get_project_conf,
    main,
    process_path,
    process_paths,
    process_remote_paths,
    sync_files,
)


@pytest.mark.parametrize(
    "project, src, dest, delete, exclude",
    [
        ("plum", "/tmp", "/tmp", 0, []),
        ("plum", "/tmp", "/tmp", 0, [".git"]),
        ("2", "/tmp", "/tmp", 1, [".git"]),
        ("1", "/tmp/1", "/tmp/2", 1, [".git", "*.pyc"]),
        ("1", "/tmp/1", "/tmp/2", None, [".git", "*.pyc"]),
        ("xxx", "/tmp/1", "/tmp/2", None, []),
    ],
)
def test_get_project_conf(project: str, src: str, dest: str, delete: int | None, exclude: list[str]) -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={
                "projects": {
                    project: {
                        "src": "/tmp",
                        "dest": "/tmp",
                        "delete": None,
                        "exclude": [],
                    }
                }
            },
        ) as p,
        mock.patch("plum_tools.prn.get_file_abspath", side_effect=lambda x: x),
    ):
        data = get_project_conf(project, [src], [dest], delete, exclude)
        assert data == {
            "exclude": exclude,
            "delete": delete,
            "src": [src],
            "dest": [dest],
        }
        p.assert_called_with(PathConfig.PLUM_YML_PATH)


def test_get_project_conf_does_not_mutate_yaml_project_config() -> None:
    yml_data = {"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}}

    with (
        mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value=yml_data),
        mock.patch("plum_tools.prn.get_file_abspath", side_effect=lambda value: f"abs:{value}"),
    ):
        data = get_project_conf("demo", [], [], None, [])

    assert data == {"src": ["abs:/tmp/src"], "dest": ["/tmp/dest"], "exclude": [], "delete": 0}
    assert yml_data == {"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}}


def test_get_project_conf_uses_yaml_defaults_and_normalizes_to_lists() -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}},
        ) as mock_parse,
        mock.patch(
            "plum_tools.prn.get_file_abspath", side_effect=lambda value: f"abs:{value}"
        ) as mock_get_file_abspath,
    ):
        data = get_project_conf("demo", [], [], None, [])

    mock_parse.assert_called_once_with(PathConfig.PLUM_YML_PATH)
    mock_get_file_abspath.assert_called_once_with("/tmp/src")
    assert data == {"src": ["abs:/tmp/src"], "dest": ["/tmp/dest"], "exclude": [], "delete": 0}


def test_get_project_conf_skips_abspath_for_download() -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}},
        ),
        mock.patch("plum_tools.prn.get_file_abspath") as mock_get_file_abspath,
    ):
        data = get_project_conf("demo", [], [], None, [], True)

    mock_get_file_abspath.assert_not_called()
    assert data == {"src": ["/tmp/src"], "dest": ["/tmp/dest"], "exclude": [], "delete": 0}


def test_get_project_conf_exits_when_project_missing_without_paths() -> None:
    with (
        mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value={"projects": {}}),
        mock.patch("plum_tools.prn.print_error") as mock_print_error,
    ):
        with pytest.raises(SystemExit) as exc_info:
            get_project_conf("missing", [], [], None, [])

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with(f"yml文件: {PathConfig.PLUM_YML_PATH} 中没有配置项目: missing 的信息")


@pytest.mark.parametrize(
    ("side_effect", "message"),
    [
        (RunCmdError("fail", "", "stderr"), "/tmp/src 文件/目录不存在"),
        (SystemTypeError("unsupported"), "unsupported"),
    ],
)
def test_get_project_conf_exits_when_local_path_resolution_fails(side_effect: Exception, message: str) -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}},
        ),
        mock.patch("plum_tools.prn.get_file_abspath", side_effect=side_effect),
        mock.patch("plum_tools.prn.print_error") as mock_print_error,
    ):
        with pytest.raises(SystemExit) as exc_info:
            get_project_conf("demo", [], [], None, [])

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with(message)


def test_process_path_and_helpers() -> None:
    with mock.patch("plum_tools.prn.os.path.isdir", side_effect=lambda path: path == "/tmp/dir"):
        assert process_path("/tmp/dir", is_local=True) == "/tmp/dir/"
        assert process_path("/tmp/file", is_local=True) == "/tmp/file"

    assert process_path("/remote/path/", is_local=False) == "/remote/path"
    assert process_paths(["/tmp/a", "/tmp/b/"], is_local=False) == "/tmp/a /tmp/b"
    assert process_paths("/tmp/a", is_local=True) == "/tmp/a"
    assert process_remote_paths(["/a/", "/b"], "user@host:", "") == "user@host:/a/ user@host:/b"


def test_sync_files_builds_localhost_and_remote_syncs() -> None:
    projects_conf = [
        {"src": "/tmp/a", "dest": "/remote/a", "exclude": [], "delete": 0},
        {"src": "/tmp/b", "dest": "/remote/b", "exclude": [".git"], "delete": 1},
    ]
    sync_instances = [mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock()]

    with (
        mock.patch(
            "plum_tools.prn.merge_ssh_config",
            return_value={"hostname": "10.0.0.1", "user": "root", "port": 22, "identityfile": "id_rsa"},
        ) as mock_merge,
        mock.patch("plum_tools.prn.SyncFiles", side_effect=sync_instances) as mock_sync_files,
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

    with mock.patch("plum_tools.prn.subprocess.call", return_value=0) as mock_subprocess_call:
        sync.translate()

    mock_subprocess_call.assert_called_once_with(
        "rsync -rtlv --delete --exclude '.git' /remote/a/ /remote/b /local/file",
        shell=True,  # nosec: B604
    )
    captured = capsys.readouterr()
    assert "从 本地机器 下载 /remote/a/ /remote/b 到本地 /local/file 成功" in captured.out


def test_translate_reports_run_cmd_error(capsys: pytest.CaptureFixture[str]) -> None:
    sync = SyncFiles("1.1.1.1", "user", 22, "", "/tmp/src", "/tmp/dest", [], 0)

    with mock.patch("plum_tools.prn.run_cmd", side_effect=RunCmdError("fail", "", "boom")):
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
        mock.patch("plum_tools.prn.os.path.isdir", return_value=True),
        mock.patch("plum_tools.prn.run_cmd") as mock_run_cmd,
        mock.patch("plum_tools.prn.subprocess.call") as mock_subprocess_call,
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


@pytest.mark.parametrize("dry_run", [False, True])
def test_main_parses_dry_run(dry_run: bool) -> None:
    """使用真实参数解析器校验预览选项的默认值及传递。"""
    argv = ["prn", "--dry-run"] if dry_run else ["prn"]
    project_conf = {"src": ["/local"], "dest": ["/remote"]}
    with (
        mock.patch("sys.argv", argv),
        mock.patch("plum_tools.prn.get_project_conf", return_value=project_conf),
        mock.patch("plum_tools.prn.sync_files") as mock_sync,
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
        mock.patch("plum_tools.prn.get_project_conf", side_effect=projects_conf),
        mock.patch(
            "plum_tools.prn.merge_ssh_config",
            return_value={"hostname": "10.0.0.1", "user": "root", "port": 22, "identityfile": "id_rsa"},
        ) as mock_merge,
        mock.patch("plum_tools.prn.os.path.isdir", return_value=False),
        mock.patch("plum_tools.prn.run_cmd") as mock_run_cmd,
        mock.patch("plum_tools.prn.subprocess.call") as mock_subprocess_call,
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
        mock.patch("plum_tools.prn.get_base_parser", return_value=mock_parser),
        mock.patch(
            "plum_tools.prn.get_project_conf", return_value={"src": ["/local"], "dest": ["/remote"]}
        ) as mock_project,
        mock.patch("plum_tools.prn.sync_files") as mock_sync,
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
        mock.patch("plum_tools.prn.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.prn.print_error") as mock_print_error,
        mock.patch("plum_tools.prn.get_project_conf") as mock_project,
        mock.patch("plum_tools.prn.sync_files") as mock_sync,
    ):
        main()

    mock_print_error.assert_called_once_with("本地路径和目标路径不能同时传入多个值")
    mock_project.assert_not_called()
    mock_sync.assert_not_called()


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
    with mock.patch("plum_tools.prn.run_cmd") as m:
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

    with mock.patch("plum_tools.prn.run_cmd") as m:
        u.translate()
        m.assert_called_once_with(
            'rsync -rtlv -e \'ssh -p 22 -i  -o "UserKnownHostsFile=/dev/null" '
            '-o "StrictHostKeyChecking no" -o "ConnectTimeout=10"\' /tmp/ user@1.1.1.1:/tmp'
        )

    captured = capsys.readouterr()
    assert captured.out == "[32m上传 /tmp/ 到 user@1.1.1.1 服务器(端口: 22) /tmp 成功[0m\n"


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
        mock.patch("plum_tools.prn.get_base_parser", return_value=mock_parser) as mock_argparse,
        mock.patch("plum_tools.prn.get_project_conf", return_value=mock_project_conf) as mock_project,
        mock.patch("plum_tools.prn.sync_files") as mock_sync,
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
        mock.patch("plum_tools.prn.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.prn.get_project_conf", return_value={}) as mock_project,
        mock.patch("plum_tools.prn.sync_files") as mock_sync,
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
    from plum_tools.prn import SyncFiles

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
        mock.patch("plum_tools.prn.process_paths", side_effect=lambda path, **kwargs: path),
        mock.patch("plum_tools.prn.process_remote_paths", side_effect=lambda path, prefix: path),
        mock.patch("plum_tools.prn.call_process", return_value=1),
        mock.patch("plum_tools.prn.print_text"),
        mock.patch("plum_tools.prn.print_error") as mock_print_error,
        mock.patch("plum_tools.prn.print_ok"),
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
