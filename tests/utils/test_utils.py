"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_utils
#         Desc: 测试项目中工具包
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 23:42
#=============================================================================
"""

from pathlib import Path
from typing import Any, cast
from unittest import mock

import pytest

from plum_tools.conf import OsCommand, PathConfig
from plum_tools.exceptions import SystemTypeError
from plum_tools.utils.utils import GlobalConf, SSHConf, YmlConfig, ensure_str, get_file_abspath


def test_global_conf_get_data_merges_dynamic_data() -> None:
    conf = GlobalConf(
        default_ssh_conf=SSHConf(user="root", port=22, identityfile="~/.ssh/id_rsa"),
        ipmi_interval=100,
        projects=[],
        host_type_default=cast(Any, "10.0.0"),
    )

    assert conf.get_data() == {
        "default_ssh_conf": {"user": "root", "port": 22, "identityfile": "~/.ssh/id_rsa"},
        "ipmi_interval": 100,
        "projects": [],
        "host_type_default": "10.0.0",
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"type_default": cast(Any, "10.0.0")}, "key: type_default 必须以 type_ 开头"),
        ({"host_type_default": cast(Any, 123)}, "key:host_type_default value: 123 必须为字符串"),
    ],
)
def test_global_conf_validates_dynamic_data(kwargs: dict[str, Any], message: str) -> None:
    conf = GlobalConf(
        default_ssh_conf=SSHConf(user="root", port=22, identityfile="~/.ssh/id_rsa"),
        ipmi_interval=100,
        projects=[],
        **kwargs,
    )

    with pytest.raises(TypeError, match=message):
        conf.get_data()


def test_parse_config_yml_returns_cached_data(tmp_path: Path) -> None:
    yml_path = tmp_path / "config.yml"
    # flake8: noqa: E501
    yml_path.write_text(
        "default_ssh_conf:\n  user: root\n  port: 22\n  identityfile: ~/.ssh/id_rsa\nipmi_interval: 100\nprojects: []\nhost_type_default: 10.0.0\n",
        encoding="utf-8",
    )
    YmlConfig._yml_data = {}

    data = YmlConfig.parse_config_yml(str(yml_path))
    cached = YmlConfig.parse_config_yml(str(yml_path))

    assert data == cached
    assert data["host_type_default"] == "10.0.0"


def test_parse_config_yml_exits_when_yaml_format_is_invalid(tmp_path: Path) -> None:
    yml_path = tmp_path / "config.yml"
    yml_path.write_text("default_ssh_conf: {}\nprojects: []\n", encoding="utf-8")
    YmlConfig._yml_data = {}

    open_mock = mock.mock_open()
    open_mock.side_effect = [
        mock.mock_open(read_data=yml_path.read_text(encoding="utf-8")).return_value,
        mock.mock_open(read_data="template").return_value,
    ]

    with (
        mock.patch("builtins.open", open_mock),
        mock.patch("plum_tools.utils.utils.print_error") as mock_print_error,
        mock.patch("plum_tools.utils.utils.print_text") as mock_print_text,
    ):
        with pytest.raises(SystemExit) as exc_info:
            YmlConfig.parse_config_yml(str(yml_path))

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once()
    mock_print_text.assert_called_once_with("template")


def test_parse_config_yml_exits_when_file_is_missing() -> None:
    YmlConfig._yml_data = {}

    with mock.patch("plum_tools.utils.utils.print_error") as mock_print_error:
        with pytest.raises(SystemExit) as exc_info:
            YmlConfig.parse_config_yml("/missing/config.yml")

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with(f"yml文件: {PathConfig.PLUM_YML_PATH} 不存在")


def test_ensure_str_supports_str_and_bytes() -> None:
    assert ensure_str("abc") == "abc"
    assert ensure_str(b"abc") == "abc"

    with pytest.raises(TypeError, match="not expecting type"):
        ensure_str(1)


def test_get_file_abspath_returns_existing_path(tmp_path: Path) -> None:
    file_path = tmp_path / "demo.txt"
    file_path.write_text("demo", encoding="utf-8")

    assert get_file_abspath(str(file_path)) == str(file_path)


def test_get_file_abspath_parses_linux_stat_output() -> None:
    with (
        mock.patch("plum_tools.utils.utils.os.path.exists", return_value=False),
        mock.patch("plum_tools.utils.utils.run_cmd", return_value="  File: /tmp/demo file\n") as mock_run_cmd,
        mock.patch("plum_tools.utils.utils.platform.system", return_value="Linux"),
    ):
        assert get_file_abspath("/tmp/demo file") == "/tmp/demo\\ file"

    mock_run_cmd.assert_called_once_with(OsCommand.STAT_COMMAND % "/tmp/demo\\ file")


def test_get_file_abspath_parses_darwin_stat_output() -> None:
    with (
        mock.patch("plum_tools.utils.utils.os.path.exists", return_value=False),
        mock.patch(
            "plum_tools.utils.utils.run_cmd",
            return_value='" 1 2 3 /tmp/demo file\n',
        ),
        mock.patch("plum_tools.utils.utils.platform.system", return_value="Darwin"),
    ):
        assert get_file_abspath("/tmp/demo file") == "/tmp/demo\\ file"


def test_get_file_abspath_rejects_unsupported_system() -> None:
    with (
        mock.patch("plum_tools.utils.utils.os.path.exists", return_value=False),
        mock.patch("plum_tools.utils.utils.run_cmd", return_value=""),
        mock.patch("plum_tools.utils.utils.platform.system", return_value="Windows"),
    ):
        with pytest.raises(SystemTypeError, match=r"此项功能仅支持 Linux / Darwin\(mac\)"):
            get_file_abspath("/tmp/demo")


def test_get_file_abspath_raises_when_path_cannot_be_found() -> None:
    with (
        mock.patch("plum_tools.utils.utils.os.path.exists", return_value=False),
        mock.patch("plum_tools.utils.utils.run_cmd", return_value="no match"),
        mock.patch("plum_tools.utils.utils.platform.system", return_value="Linux"),
    ):
        with pytest.raises(FileNotFoundError, match="文件: /tmp/demo 不存在"):
            get_file_abspath("/tmp/demo")


def test_get_file_abspath_preserves_escaped_space_in_missing_path() -> None:
    with (
        mock.patch("plum_tools.utils.utils.os.path.exists", return_value=False),
        mock.patch("plum_tools.utils.utils.run_cmd", return_value="no match"),
        mock.patch("plum_tools.utils.utils.platform.system", return_value="Linux"),
    ):
        with pytest.raises(FileNotFoundError, match=r"文件: /tmp/demo\\ file 不存在"):
            get_file_abspath("/tmp/demo file")
