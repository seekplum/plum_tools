"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_sshconf
#         Desc: 测试解析ssh配置模块
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 23:42
#=============================================================================
"""

from pathlib import Path
from unittest import mock

import pytest

from plum_tools.conf import PathConfig
from plum_tools.utils.sshconf import SSHConf, get_host_ip, get_prefix_host_ip, get_ssh_alias_conf, merge_ssh_config


class TestSSHConf:
    @pytest.mark.parametrize(
        "host, user, port, identityfile",
        [
            ("1", None, None, None),
            ("2", "", "", ""),
            ("3.1", "", 0, False),
        ],
    )
    def test_get_ssh_conf_with_empty(self, host: str, user: str, port: int, identityfile: str) -> None:
        s = SSHConf(user, port, identityfile)
        with mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={
                "default_ssh_conf": {
                    "user": "root",
                    "port": 22,
                    "identityfile": "~/.ssh/id_rsa",
                }
            },
        ) as p:
            ssh_conf = s.get_ssh_conf(host)
            p.assert_called_with(PathConfig.PLUM_YML_PATH)
        assert ssh_conf["hostname"] == host
        assert ssh_conf["user"] == "root"
        assert ssh_conf["port"] == 22
        assert ssh_conf["identityfile"] == "~/.ssh/id_rsa"

    @pytest.mark.parametrize(
        "host, user, port, identityfile",
        [
            ("1", "mysql", 3306, "/tmp/id_rsa"),
            ("1.1", "oracle", 1521, "/tmp/id_dsa"),
        ],
    )
    def test_get_ssh_conf(self, host: str, user: str, port: int, identityfile: str) -> None:
        s = SSHConf(user, port, identityfile)
        with mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={
                "default_ssh_conf": {
                    "user": "root",
                    "port": 22,
                    "identityfile": "~/.ssh/id_rsa",
                }
            },
        ) as p:
            ssh_conf = s.get_ssh_conf(host)
            p.assert_called_with(PathConfig.PLUM_YML_PATH)
        assert ssh_conf["hostname"] == host
        assert ssh_conf["user"] == user
        assert ssh_conf["port"] == port
        assert ssh_conf["identityfile"] == identityfile

    def test_get_ssh_conf_does_not_mutate_default_config(self) -> None:
        default_conf = {
            "default_ssh_conf": {
                "user": "root",
                "port": 22,
                "identityfile": "~/.ssh/id_rsa",
            }
        }
        with mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value=default_conf):
            SSHConf("oracle", 0, "").get_ssh_conf("host1")
            ssh_conf = SSHConf("", 0, "").get_ssh_conf("host2")

        assert ssh_conf == {"hostname": "host2", "user": "root", "port": 22, "identityfile": "~/.ssh/id_rsa"}
        assert default_conf["default_ssh_conf"] == {"user": "root", "port": 22, "identityfile": "~/.ssh/id_rsa"}

    @pytest.mark.parametrize("alias_conf", [{}])
    def test_merge_ssh_conf_with_raise(self, alias_conf: dict) -> None:
        s = SSHConf("", 22, "")
        with mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={
                "default_ssh_conf": {
                    "user": "root",
                    "port": 22,
                    "identityfile": "~/.ssh/id_rsa",
                }
            },
        ) as p:
            with pytest.raises(KeyError):
                _ = s.merge_ssh_conf(alias_conf)
                p.assert_called_with(PathConfig.PLUM_YML_PATH)

    @pytest.mark.parametrize("alias_conf", [{"hostname": "1.1.1.1"}])
    def test_merge_ssh_conf_with_empty(self, alias_conf: dict) -> None:
        s = SSHConf("", 22, "")
        with mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={
                "default_ssh_conf": {
                    "user": "root",
                    "port": 22,
                    "identityfile": "~/.ssh/id_rsa",
                }
            },
        ) as p:
            ssh_conf = s.merge_ssh_conf(alias_conf)
            p.assert_called_with(PathConfig.PLUM_YML_PATH)

            assert ssh_conf["hostname"] == alias_conf["hostname"]
            assert ssh_conf["user"] == "root"
            assert ssh_conf["port"] == 22
            assert ssh_conf["identityfile"] == "~/.ssh/id_rsa"

    def test_merge_ssh_conf_with_alias(self) -> None:
        alias_conf = {
            "hostname": "1.1.1.1",
            "user": "oracle",
            "port": 1521,
            "identityfile": "~/.ssh/oracle",
        }
        s = SSHConf("", 0, "")
        with mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={
                "default_ssh_conf": {
                    "user": "root",
                    "port": 22,
                    "identityfile": "~/.ssh/id_rsa",
                }
            },
        ) as p:
            ssh_conf = s.merge_ssh_conf(alias_conf)
            p.assert_called_with(PathConfig.PLUM_YML_PATH)

            assert ssh_conf["hostname"] == alias_conf["hostname"]
            assert ssh_conf["user"] == alias_conf["user"]
            assert ssh_conf["port"] == alias_conf["port"]
            assert ssh_conf["identityfile"] == alias_conf["identityfile"]

    def test_merge_ssh_conf(self) -> None:
        alias_conf = {
            "hostname": "1.1.1.1",
            "user": "oracle",
            "port": 1521,
            "identityfile": "~/.ssh/oracle",
        }
        user, port, identityfile = "mysql", 3306, "~/.ss/mysql"
        s = SSHConf(user, port, identityfile)
        with mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={
                "default_ssh_conf": {
                    "user": "root",
                    "port": 22,
                    "identityfile": "~/.ssh/id_rsa",
                }
            },
        ) as p:
            ssh_conf = s.merge_ssh_conf(alias_conf)
            p.assert_called_with(PathConfig.PLUM_YML_PATH)

            assert ssh_conf["hostname"] == alias_conf["hostname"]
            assert ssh_conf["user"] == user
            assert ssh_conf["port"] == port
            assert ssh_conf["identityfile"] == identityfile


@pytest.mark.parametrize("host_type, result", [(1, "1.1.1"), (2, "2.2.2."), ("test", "3.3.3")])
def test_get_prefix_host_ip(host_type: str, result: list) -> None:
    with mock.patch(
        "plum_tools.utils.utils.YmlConfig.parse_config_yml",
        return_value={
            "host_type_1": "1.1.1",
            "host_type_2": "2.2.2.",
            "host_type_test": "3.3.3",
        },
    ) as p:
        assert get_prefix_host_ip(host_type) == result
        p.assert_called_with(PathConfig.PLUM_YML_PATH)


def test_get_prefix_host_ip_with_raise() -> None:
    # 命令行直接运行是OK的，没有编码问题，通过 ctx.run 运行有UnicodeEncodeError:, 需要排查 encoding
    with mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value={}) as p:
        with pytest.raises(SystemExit):
            get_prefix_host_ip("test")
        p.assert_called_with(PathConfig.PLUM_YML_PATH)


@pytest.mark.parametrize(
    "host, host_type, result",
    [
        ("1", "1", "1.1.1.1"),
        ("2", "1", "1.1.1.2"),
        ("2.1", "1", "1.1.2.1"),
        ("2.2", "1", "1.1.2.2"),
    ],
)
def test_get_host_ip(host: str, host_type: str, result: str) -> None:
    with mock.patch(
        "plum_tools.utils.utils.YmlConfig.parse_config_yml",
        return_value={
            "host_type_1": "1.1.1",
            "host_type_2": "2.2.2.",
            "host_type_test": "3.3.3",
        },
    ) as p:
        assert get_host_ip(host, host_type) == result
        p.assert_called_with(PathConfig.PLUM_YML_PATH)


def test_get_host_ip_returns_full_ip_unchanged() -> None:
    with mock.patch("plum_tools.utils.sshconf.get_prefix_host_ip") as mock_prefix:
        assert get_host_ip("1.2.3.4", "default") == "1.2.3.4"

    mock_prefix.assert_not_called()


def test_get_ssh_alias_conf_reads_matching_alias(tmp_path: Path) -> None:
    config_path = tmp_path / "config"
    config_path.write_text(
        "Host dev\n  HostName 10.0.0.1\n  User root\n  Port 22\n\nHost other\n  HostName 10.0.0.2\n",
        encoding="utf-8",
    )

    with mock.patch("builtins.open", mock.mock_open(read_data=config_path.read_text(encoding="utf-8"))):
        ssh_conf = get_ssh_alias_conf("dev")

    assert ssh_conf == {"host": "dev", "hostname": "10.0.0.1", "user": "root", "port": "22"}


def test_get_ssh_alias_conf_exits_when_alias_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "config"
    config_path.write_text("Host dev\n  HostName 10.0.0.1\n", encoding="utf-8")

    with mock.patch("builtins.open", mock.mock_open(read_data=config_path.read_text(encoding="utf-8"))):
        with pytest.raises(SystemExit) as exc_info:
            get_ssh_alias_conf("missing")

    assert exc_info.value.code == 1


def test_merge_ssh_config_for_ip_path() -> None:
    with (
        mock.patch("plum_tools.utils.sshconf.get_host_ip", return_value="10.0.0.1") as mock_get_host_ip,
        mock.patch.object(SSHConf, "get_ssh_conf", return_value={"hostname": "10.0.0.1"}) as mock_get_ssh_conf,
        mock.patch("plum_tools.utils.sshconf.get_ssh_alias_conf") as mock_get_alias,
    ):
        result = merge_ssh_config("1", "default", "root", 22, "~/.ssh/id_rsa")

    assert result == {"hostname": "10.0.0.1"}
    mock_get_host_ip.assert_called_once_with("1", "default")
    mock_get_ssh_conf.assert_called_once_with("10.0.0.1")
    mock_get_alias.assert_not_called()


def test_merge_ssh_config_for_alias_path() -> None:
    alias_conf = {"hostname": "10.0.0.2", "user": "root", "port": "22", "identityfile": "~/.ssh/id_rsa"}
    with (
        mock.patch("plum_tools.utils.sshconf.get_ssh_alias_conf", return_value=alias_conf) as mock_get_alias,
        mock.patch.object(SSHConf, "merge_ssh_conf", return_value={"hostname": "10.0.0.2"}) as mock_merge_ssh_conf,
        mock.patch("plum_tools.utils.sshconf.get_host_ip") as mock_get_host_ip,
    ):
        result = merge_ssh_config("dev", "default", "root", 22, "~/.ssh/id_rsa")

    assert result == {"hostname": "10.0.0.2"}
    mock_get_alias.assert_called_once_with("dev")
    mock_merge_ssh_conf.assert_called_once_with(alias_conf)
    mock_get_host_ip.assert_not_called()
