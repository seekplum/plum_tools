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
        "rsync -rtv '--rsync-path=mkdir -p /local && rsync'  --delete --exclude '.git' /remote/a/ /remote/b /local/file",
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
        debug=True,
        ignore_rsync_path=True,
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
        [LOCAL_HOST], "default", "", 0, "", [{"src": ["/local"], "dest": ["/remote"]}], True, True, True
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
            "rsync -rtv '--rsync-path=mkdir -p / && rsync' -e "
            '\'ssh -p 22 -i  -o "UserKnownHostsFile=/dev/null" '
            '-o "StrictHostKeyChecking no" -o "ConnectTimeout=2"\' /tmp/ user@1.1.1.1:/tmp'
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
            'rsync -rtv -e \'ssh -p 22 -i  -o "UserKnownHostsFile=/dev/null" '
            '-o "StrictHostKeyChecking no" -o "ConnectTimeout=2"\' /tmp/ user@1.1.1.1:/tmp'
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
        debug=False,
        ignore_rsync_path=False,
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
                    help="specify server",
                ),
                mock.call(
                    "-p",
                    "--projects",
                    required=False,
                    action="store",
                    dest="projects",
                    nargs="+",
                    default=["default"],
                    help="specify project",
                ),
                mock.call(
                    "-t",
                    "--type",
                    action="store",
                    required=False,
                    dest="type",
                    default="default",
                    help="host type",
                ),
                mock.call(
                    "--download",
                    action="store_true",
                    required=False,
                    dest="download",
                    default=False,
                    help="Download the file locally",
                ),
                mock.call(
                    "-i",
                    "--identityfile",
                    action="store",
                    required=False,
                    dest="identity_file",
                    default="",
                    help="ssh login identityfile path",
                ),
                mock.call(
                    "-u",
                    "--username",
                    action="store",
                    required=False,
                    dest="user",
                    default="",
                    help="ssh login username",
                ),
                mock.call(
                    "--port",
                    action="store",
                    required=False,
                    dest="port",
                    type=int,
                    default=0,
                    help="ssh login port",
                ),
                mock.call(
                    "-l",
                    "--local",
                    action="store",
                    required=False,
                    dest="local",
                    nargs="+",
                    default="",
                    help="local path",
                ),
                mock.call(
                    "-r",
                    "--remote",
                    action="store",
                    required=False,
                    dest="remote",
                    nargs="+",
                    default="",
                    help="remote path",
                ),
                mock.call(
                    "-d",
                    "--delete",
                    action="store",
                    required=False,
                    dest="delete",
                    type=int,
                    default=None,
                    help="delete remote path other file",
                ),
                mock.call(
                    "-e",
                    "--exclude",
                    action="store",
                    nargs="+",
                    required=False,
                    dest="exclude",
                    default=[],
                    help="exclude file",
                ),
                mock.call(
                    "--debug",
                    action="store_true",
                    required=False,
                    dest="debug",
                    default=False,
                    help="debug output from parser",
                ),
                mock.call(
                    "--ignore-rsync-path",
                    action="store_true",
                    required=False,
                    dest="ignore_rsync_path",
                    default=False,
                    help="ignore rsync-path option",
                ),
            ]
        )
        mock_parser.parse_args.assert_called_once_with()
        mock_project.assert_has_calls([mock.call(project, "", "", None, [], False) for project in ["test", "python"]])
        mock_sync.assert_called_once_with(
            ["test", "dev"],
            mock_args.type,
            "",
            0,
            "",
            [mock_project_conf, mock_project_conf],
            False,
            False,
            False,
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
        debug=False,
        ignore_rsync_path=True,
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
        True,
    )
