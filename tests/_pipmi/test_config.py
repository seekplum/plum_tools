"""验证 config 的相关行为。"""

from unittest import mock

from plum_tools._pipmi.config import Parser, get_ipmi_ip, get_ssh_config
from plum_tools.utils.constants import PathConfig


def test_get_ssh_config_uses_defaults_when_values_missing() -> None:
    with mock.patch(
        "plum_tools._pipmi.config.YmlConfig.parse_config_yml",
        return_value={
            "default_ssh_conf": {
                "user": "root",
                "port": 22,
                "identityfile": "~/.ssh/id_rsa",
            }
        },
    ) as mock_parse:
        ssh_conf = get_ssh_config("10.0.0.1", "", 0, "", "secret")

    mock_parse.assert_called_once_with(PathConfig.PLUM_YML_PATH)
    assert ssh_conf == {
        "hostname": "10.0.0.1",
        "username": "root",
        "port": 22,
        "identityfile": "~/.ssh/id_rsa",
        "password": "secret",
    }


def test_get_ipmi_ip_adds_interval_to_last_octet() -> None:
    with (
        mock.patch(
            "plum_tools._pipmi.config.YmlConfig.parse_config_yml", return_value={"ipmi_interval": 100}
        ) as mock_parse,
        mock.patch("plum_tools._pipmi.config.get_host_ip", return_value="10.0.0.5") as mock_get_host_ip,
    ):
        assert get_ipmi_ip("5", "default") == "10.0.0.105"

    mock_parse.assert_called_once_with(PathConfig.PLUM_YML_PATH)
    mock_get_host_ip.assert_called_once_with("5", "default")


def test_parser_methods_delegate_to_helpers() -> None:
    args = mock.Mock(
        host="1",
        type="default",
        user="root",
        port=22,
        identityfile="~/.ssh/id_rsa",
        password="secret",
        servers=["2", "3"],
        Username="ADMIN",
        Password="12345678",
        command="power on",
    )
    parser = Parser(args)

    with (
        mock.patch("plum_tools._pipmi.config.get_host_ip", return_value="10.0.0.1") as mock_get_host_ip,
        mock.patch(
            "plum_tools._pipmi.config.get_ssh_config", return_value={"hostname": "10.0.0.1"}
        ) as mock_get_ssh_config,
        mock.patch("plum_tools._pipmi.config.get_ipmi_ip", return_value="10.0.0.101") as mock_get_ipmi_ip,
    ):
        assert parser.parser_ssh_conf() == {"hostname": "10.0.0.1"}
        assert parser.parser_ip_list() == ["2", "3"]
        assert parser.parser_ipmi_auth("2") == {
            "ip": "10.0.0.101",
            "user": "ADMIN",
            "password": "12345678",
            "command": "power on",
        }

    mock_get_host_ip.assert_called_once_with("1", "default")
    mock_get_ssh_config.assert_called_once_with("10.0.0.1", "root", 22, "~/.ssh/id_rsa", "secret")
    mock_get_ipmi_ip.assert_called_once_with("2", "default")
