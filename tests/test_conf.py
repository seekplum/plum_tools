# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_conf
#         Desc: 测试枚举
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-03 22:58
#=============================================================================
"""
import os
import six

import pytest

from plum_tools.conf import ReadOnlyClass
from plum_tools.conf import ClsReadOnlyClass
from plum_tools.conf import GitCommand
from plum_tools.conf import OsCommand
from plum_tools.conf import SSHConfig
from plum_tools.conf import Constant
from plum_tools.conf import PathConfig
from plum_tools.conf import generate_test_class


class TestClsReadOnlyClass(object):
    def test_bases_class(self):
        assert isinstance(ClsReadOnlyClass.__bases__[0], type)

    def test_variable_read_only(self):
        class MyClass(six.with_metaclass(ClsReadOnlyClass)):
            name = "test"
            value = "test"

            def __init__(self):
                self.name = None

        m = MyClass()
        m.name = "test2"
        m.new_name = "test2"

        with pytest.raises(ValueError) as err:
            MyClass.name = "tes2"
        assert err.value.args[0] == "name is read-only"


class TestReadOnlyClass(object):
    def test_bases_class(self):
        assert ReadOnlyClass.__class__ is ClsReadOnlyClass

    def test_variable_read_only(self):
        class MyClass(ReadOnlyClass):
            name = "test"
            value = "test"

        with pytest.raises(ValueError) as err:
            m = MyClass()
            m.name = "test2"
        assert err.value.args[0] == "name is read-only"

        with pytest.raises(ValueError) as err:
            m = MyClass()
            m.new_name = "test2"
        assert err.value.args[0] == "new_name is read-only"

        with pytest.raises(ValueError) as err:
            MyClass.name = "tes2"
        assert err.value.args[0] == "name is read-only"


class TestGitCommand(object):
    @classmethod
    def setup(cls):
        cls.g = GitCommand

    @classmethod
    def teardown(cls):
        del cls.g

    def test_pull_keyword(self):
        assert self.g.pull_keyword == '"git pull"'

    def test_push_keyword(self):
        assert self.g.push_keyword == '"git push"'

    def test_git_checkout(self):
        assert self.g.git_checkout == 'git checkout %s'

    def test_branch_abbrev(self):
        assert self.g.branch_abbrev == 'git rev-parse --abbrev-ref HEAD'

    def test_stash_list(self):
        assert self.g.stash_list == 'git stash list'

    def test_stash_pop(self):
        assert self.g.stash_pop == 'git stash pop --index %s'

    def test_stash_save(self):
        assert self.g.stash_save == 'git stash save "%s"'

    def test_status_default(self):
        assert self.g.status_default == 'git status'

    def test_status_short(self):
        assert self.g.status_short == 'git status -s'


class TestOsCommand(object):
    @classmethod
    def setup(cls):
        cls.o = OsCommand

    @classmethod
    def teardown(cls):
        del cls.o

    def test_find_command(self):
        assert self.o.find_command == 'find %s -name ".git"'

    def test_ipmi_command(self):
        assert self.o.ipmi_command == 'ipmitool -I lanplus -H %(ip)s -U %(user)s -P %(password)s %(command)s'

    def test_ping_command(self):
        assert self.o.ping_command == 'ping -W 3 -c 1 %s'

    def test_stat_command(self):
        assert self.o.stat_command == 'stat %s'


class TestSSHConfig(object):
    @classmethod
    def setup(cls):
        cls.s = SSHConfig

    @classmethod
    def teardown(cls):
        del cls.s

    def test_connect_timeout(self):
        assert self.s.connect_timeout == 3

    def test_default_ssh_port(self):
        assert self.s.default_ssh_port == 22


class TestConstant(object):
    @classmethod
    def setup(cls):
        cls.c = Constant

    @classmethod
    def teardown(cls):
        del cls.c

    def test_command_timeout(self):
        assert self.c.command_timeout == 3

    def test_processes_number(self):
        assert self.c.processes_number == 100

    def test_stash_uuid(self):
        assert self.c.stash_uuid == 'plum123456789987654321plum'


class TestPathConfig(object):
    @classmethod
    def setup(cls):
        cls.p = PathConfig

    @classmethod
    def teardown(cls):
        del cls.p

    def test_plum_yml_name(self):
        assert self.p.plum_yml_name == '.plum_tools.yaml'

    def test_ssh_config_name(self):
        assert self.p.ssh_config_name == '.ssh/config'

    def test_home(self):
        assert self.p.home == os.environ["HOME"]

    def test_plum_yml_path(self):
        assert self.p.plum_yml_path == os.path.join(self.p.home, self.p.plum_yml_name)

    def test_ssh_config_path(self):
        assert self.p.ssh_config_path == os.path.join(self.p.home, self.p.ssh_config_name)

    def test_root(self):
        current_path = os.path.dirname(os.path.abspath(__file__))
        assert self.p.root == os.path.join(os.path.dirname(current_path), "plum_tools")


def test_generate_test_class(capsys):
    context = """class TestConstant(object):
    @classmethod
    def setup(cls):
        cls.c = Constant

    @classmethod
    def teardown(cls):
        del cls.c

    def test_command_timeout(self):
        assert self.c.command_timeout == '3'

    def test_processes_number(self):
        assert self.c.processes_number == '100'

    def test_stash_uuid(self):
        assert self.c.stash_uuid == 'plum123456789987654321plum'

"""
    generate_test_class(Constant, "c")
    captured = capsys.readouterr()
    output = captured.out
    assert output == context
