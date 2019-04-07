# -*- coding: utf-8 -*-

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
import mock
import pytest

from plum_tools.conf import PathConfig
from plum_tools.utils.sshconf import SSHConf


class TestSSHConf(object):

    @pytest.mark.parametrize("host, user, port, identityfile", [
        (1, None, None, None),
        (2, "", "", ""),
        (3.1, "", 0, False),
    ])
    def test_get_ssh_conf_with_empty(self, host, user, port, identityfile):
        s = SSHConf(user, port, identityfile)
        with mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value={
            "default_ssh_conf": {
                "user": "root",
                "port": 22,
                "identityfile": "~/.ssh/id_rsa"
            }
        }) as p:
            ssh_conf = s.get_ssh_conf(host)
            p.assert_called_with(PathConfig.plum_yml_path)
        assert ssh_conf["hostname"] == host
        assert ssh_conf["user"] == "root"
        assert ssh_conf["port"] == 22
        assert ssh_conf["identityfile"] == "~/.ssh/id_rsa"

    @pytest.mark.parametrize("host, user, port, identityfile", [
        (1, "mysql", 3306, "/tmp/id_rsa"),
        (1.1, "oracle", 1521, "/tmp/id_dsa"),
    ])
    def test_get_ssh_conf(self, host, user, port, identityfile):
        s = SSHConf(user, port, identityfile)
        with mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value={
            "default_ssh_conf": {
                "user": "root",
                "port": 22,
                "identityfile": "~/.ssh/id_rsa"
            }
        }) as p:
            ssh_conf = s.get_ssh_conf(host)
            p.assert_called_with(PathConfig.plum_yml_path)
        assert ssh_conf["hostname"] == host
        assert ssh_conf["user"] == user
        assert ssh_conf["port"] == port
        assert ssh_conf["identityfile"] == identityfile

    @pytest.mark.parametrize("alias_conf", [
        {}
    ])
    def test_merge_ssh_conf_with_raise(self, alias_conf):
        s = SSHConf("", 22, "")
        with mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value={
            "default_ssh_conf": {
                "user": "root",
                "port": 22,
                "identityfile": "~/.ssh/id_rsa"
            }
        }) as p:
            with pytest.raises(KeyError):
                _ = s.merge_ssh_conf(alias_conf)
                p.assert_called_with(PathConfig.plum_yml_path)

    @pytest.mark.parametrize("alias_conf", [
        {"hostname": "1.1.1.1"}
    ])
    def test_merge_ssh_conf_with_empty(self, alias_conf):
        s = SSHConf("", 22, "")
        with mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value={
            "default_ssh_conf": {
                "user": "root",
                "port": 22,
                "identityfile": "~/.ssh/id_rsa"
            }
        }) as p:
            ssh_conf = s.merge_ssh_conf(alias_conf)
            p.assert_called_with(PathConfig.plum_yml_path)

            assert ssh_conf["hostname"] == alias_conf["hostname"]
            assert ssh_conf["user"] == "root"
            assert ssh_conf["port"] == 22
            assert ssh_conf["identityfile"] == "~/.ssh/id_rsa"
